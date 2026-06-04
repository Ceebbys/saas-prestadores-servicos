"""Entradas de alto nível das integrações (o que os hooks chamam).

NENHUMA destas funções faz chamada de rede neste round: se não houver conexão
ativa do tenant (sempre, por enquanto), retornam um ProviderResult
"not_configured" e logam em debug — nunca levantam exceção. É o único ponto que
uma rodada futura troca para a integração real.
"""
from __future__ import annotations

import logging

from .models import IntegrationConnection
from .providers import ProviderResult
from .providers.google import GoogleCalendarProvider, GoogleStorageProvider
from .providers.microsoft import MicrosoftCalendarProvider, MicrosoftStorageProvider

logger = logging.getLogger(__name__)

_CALENDAR = {
    IntegrationConnection.Provider.GOOGLE: GoogleCalendarProvider,
    IntegrationConnection.Provider.MICROSOFT: MicrosoftCalendarProvider,
}
_STORAGE = {
    IntegrationConnection.Provider.GOOGLE: GoogleStorageProvider,
    IntegrationConnection.Provider.MICROSOFT: MicrosoftStorageProvider,
}


def get_connection(empresa, provider) -> IntegrationConnection | None:
    return IntegrationConnection.objects.filter(
        empresa=empresa, provider=provider,
    ).first()


def _first_connected(empresa, capability):
    # Checa a capacidade em Python (no máx. 2 conexões por tenant) para ser
    # compatível com SQLite (dev) e Postgres (prod) — o lookup JSON `contains`
    # não é suportado no SQLite.
    for conn in IntegrationConnection.objects.filter(
        empresa=empresa, status=IntegrationConnection.Status.CONNECTED,
    ):
        if conn.has_capability(capability):
            return conn
    return None


def get_calendar_provider(empresa, provider=None):
    conn = (
        get_connection(empresa, provider) if provider
        else _first_connected(empresa, IntegrationConnection.Capability.CALENDAR)
    )
    if not conn or not conn.is_connected:
        return None
    cls = _CALENDAR.get(conn.provider)
    return cls(conn) if cls else None


def get_storage_provider(empresa, provider=None):
    conn = (
        get_connection(empresa, provider) if provider
        else _first_connected(empresa, IntegrationConnection.Capability.DRIVE)
    )
    if not conn or not conn.is_connected:
        return None
    cls = _STORAGE.get(conn.provider)
    return cls(conn) if cls else None


# --- Stubs de conveniência usados pelos hooks documentados -------------------

def create_calendar_event_for_followup(
    lead_contact, *, when, title="", description="",
) -> ProviderResult:
    """Cria um evento de agenda para um lembrete de follow-up (item 6.2).

    Sem provedor conectado → no-op seguro (status "not_configured"). Quando há
    Google conectado, cria um bloco de 30 min na agenda do tenant.
    """
    import datetime as _dt

    empresa = getattr(getattr(lead_contact, "lead", None), "empresa", None) or getattr(
        lead_contact, "empresa", None
    )
    provider = get_calendar_provider(empresa) if empresa else None
    if provider is None:
        logger.debug("integrations: nenhum provedor de calendário conectado")
        return ProviderResult(status="not_configured", integration_ready=False)

    end = when
    if isinstance(when, _dt.datetime):
        end = when + _dt.timedelta(minutes=30)
    return provider.create_event(
        title=title or "Follow-up de lead",
        start=when, end=end, description=description,
    )


def create_workorder_folder(work_order) -> ProviderResult:
    """STUB: cria pasta de projeto no armazenamento do tenant (Epic 7).
    Sem provedor conectado → no-op seguro."""
    provider = get_storage_provider(getattr(work_order, "empresa", None))
    if provider is None:
        logger.debug("integrations: nenhum provedor de armazenamento conectado")
        return ProviderResult(status="not_configured", integration_ready=False)
    return provider.create_folder(name=f"{work_order.number} - {work_order.title}")


# --- Sync bidirecional de agenda (Epic 7) -----------------------------------

def list_calendar_events(empresa, *, time_min, time_max) -> list[dict]:
    """RV07 (Epic 7) — Eventos da agenda Google conectada no intervalo.

    Leitura (Google → sistema), usada pelo Calendário. Cacheada por alguns
    minutos por (empresa, intervalo) p/ não bater na API a cada navegação.
    Sem provedor / falha → lista vazia (o Calendário segue mostrando as OS).
    """
    from django.core.cache import cache

    if empresa is None:
        return []
    provider = get_calendar_provider(empresa)
    if provider is None:
        return []

    cache_key = f"gcal:{empresa.pk}:{time_min.isoformat()}:{time_max.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        result = provider.list_events(time_min=time_min, time_max=time_max)
    except Exception:  # noqa: BLE001
        logger.exception("integrations: list_events falhou empresa=%s", empresa.pk)
        return []
    items = result.get("items", []) if result.get("status") == "ok" else []
    cache.set(cache_key, items, 120)
    return items


def sync_work_order_to_calendar(work_order) -> ProviderResult:
    """RV07 (Epic 7) — Espelha a OS na agenda Google (criar/atualizar/remover).

    Idempotente via ``work_order.google_event_id``. Sem provedor → no-op seguro.
    Grava o id com ``.update()`` (NÃO ``.save()``) p/ não re-disparar o post_save
    (evita loop). Eventos são all-day (fim exclusivo → +1 dia).
    """
    import datetime as _dt

    from apps.operations.models import WorkOrder

    empresa = getattr(work_order, "empresa", None)
    provider = get_calendar_provider(empresa) if empresa else None
    if provider is None:
        return ProviderResult(status="not_configured", integration_ready=False)

    def _store(event_id: str) -> None:
        WorkOrder.objects.filter(pk=work_order.pk).update(google_event_id=event_id)

    if work_order.scheduled_date:
        start = work_order.scheduled_date
        end_base = work_order.expected_end_date or work_order.scheduled_date
        end = end_base + _dt.timedelta(days=1)  # all-day: fim é exclusivo
        title = (f"{work_order.number} — {work_order.title}").strip(" —")
        description = work_order.location or ""

        if work_order.google_event_id:
            res = provider.update_event(
                work_order.google_event_id, title=title, start=start,
                end=end, description=description,
            )
            if res.get("detail") == "not_found":
                # evento sumiu no Google → recria
                res = provider.create_event(
                    title=title, start=start, end=end, description=description,
                )
                if res.get("status") == "ok":
                    _store(res.get("event_id", ""))
            return res

        res = provider.create_event(
            title=title, start=start, end=end, description=description,
        )
        if res.get("status") == "ok" and res.get("event_id"):
            _store(res["event_id"])
        return res

    # OS sem data agendada → remove o evento espelhado, se houver
    if work_order.google_event_id:
        res = provider.delete_event(work_order.google_event_id)
        _store("")
        return res
    return ProviderResult(status="ok", integration_ready=True, detail="nothing_to_sync")


def upload_file_to_workorder_drive(
    work_order, *, filename, content, mime="application/octet-stream",
) -> ProviderResult:
    """RV07 (Epic 7) — Sobe um arquivo pro Drive conectado, numa pasta da OS.

    Cria a pasta da OS no 1º upload e reaproveita depois (via
    ``work_order.google_drive_folder_id``); sobe o arquivo, gera link
    compartilhável e anexa ``{url, label}`` em ``cloud_storage_links`` (via
    ``.update()`` — não dispara post_save). Sem provedor → no-op (not_configured).
    """
    from apps.operations.models import WorkOrder

    empresa = getattr(work_order, "empresa", None)
    provider = get_storage_provider(empresa) if empresa else None
    if provider is None:
        return ProviderResult(status="not_configured", integration_ready=False)

    # 1) pasta da OS (cria-ou-reaproveita)
    folder_id = work_order.google_drive_folder_id
    if not folder_id:
        fres = provider.create_folder(
            name=f"{work_order.number} — {work_order.title}".strip(" —"),
        )
        if fres.get("status") != "ok" or not fres.get("file_id"):
            return fres
        folder_id = fres["file_id"]
        WorkOrder.objects.filter(pk=work_order.pk).update(
            google_drive_folder_id=folder_id,
        )
        work_order.google_drive_folder_id = folder_id

    # 2) upload do arquivo
    ures = provider.upload_file(
        folder_id=folder_id, filename=filename, content=content, mime=mime,
    )
    if ures.get("status") != "ok" or not ures.get("file_id"):
        return ures

    # 3) link compartilhável (anyone-with-link)
    sres = provider.share_link(file_or_folder_id=ures["file_id"])
    link = sres.get("web_link") or ures.get("web_link") or ""

    # 4) anexa em cloud_storage_links sem disparar signals
    links = list(work_order.cloud_storage_links or [])
    links.append({"url": link, "label": filename})
    WorkOrder.objects.filter(pk=work_order.pk).update(cloud_storage_links=links)
    work_order.cloud_storage_links = links

    return ProviderResult(
        status="ok", integration_ready=True, web_link=link, label=filename,
    )

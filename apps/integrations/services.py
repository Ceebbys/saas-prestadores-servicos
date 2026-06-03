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

def create_calendar_event_for_followup(lead_contact, *, when, title="") -> ProviderResult:
    """STUB: cria evento de calendário para um lembrete de follow-up (item 6.2).
    Sem provedor conectado → no-op seguro."""
    empresa = getattr(getattr(lead_contact, "lead", None), "empresa", None) or getattr(
        lead_contact, "empresa", None
    )
    provider = get_calendar_provider(empresa) if empresa else None
    if provider is None:
        logger.debug("integrations: nenhum provedor de calendário conectado")
        return ProviderResult(status="not_configured", integration_ready=False)
    return provider.create_event(title=title, start=when, end=when)


def create_workorder_folder(work_order) -> ProviderResult:
    """STUB: cria pasta de projeto no armazenamento do tenant (Epic 7).
    Sem provedor conectado → no-op seguro."""
    provider = get_storage_provider(getattr(work_order, "empresa", None))
    if provider is None:
        logger.debug("integrations: nenhum provedor de armazenamento conectado")
        return ProviderResult(status="not_configured", integration_ready=False)
    return provider.create_folder(name=f"{work_order.number} - {work_order.title}")

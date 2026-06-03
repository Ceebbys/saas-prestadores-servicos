"""Services centralizados para Contato.

Toda regra de negócio que envolva busca, criação ou vinculação de Contato
deve passar por aqui — evita lógica duplicada nas views, signals e webhook.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet

from apps.core.validators import mask_document, normalize_document

from .models import Contato

logger = logging.getLogger(__name__)


def find_contato_by_document(empresa, document: str) -> Contato | None:
    """Return the Contato in `empresa` whose normalized doc matches, else None."""
    digits = normalize_document(document or "")
    if not digits:
        return None
    return Contato.objects.filter(
        empresa=empresa, cpf_cnpj_normalized=digits
    ).first()


def get_or_create_contato_by_document(
    empresa, document: str, defaults: dict[str, Any] | None = None
) -> tuple[Contato, bool]:
    """Find existing Contato by document, or create one with `defaults`.

    Always normalizes the document. Returns (contato, created_bool).
    Logs with masked document for safe auditing.
    """
    digits = normalize_document(document or "")
    defaults = dict(defaults or {})
    if not digits:
        # Without a document, we cannot deduplicate by it — fall back to
        # creating a contact only if name is provided.
        name = (defaults.get("name") or "").strip()
        if not name:
            raise ValueError(
                "Cannot create Contato without document or name."
            )
        contato = Contato.objects.create(empresa=empresa, **defaults)
        logger.info(
            "contacts: created Contato id=%s without document (name=%r)",
            contato.pk,
            contato.name,
        )
        return contato, True

    with transaction.atomic():
        existing = (
            Contato.objects.select_for_update()
            .filter(empresa=empresa, cpf_cnpj_normalized=digits)
            .first()
        )
        if existing:
            logger.info(
                "contacts: reused Contato id=%s for doc=%s",
                existing.pk,
                mask_document(digits),
            )
            return existing, False

        defaults.setdefault("cpf_cnpj", document)
        contato = Contato.objects.create(empresa=empresa, **defaults)
        logger.info(
            "contacts: created Contato id=%s for doc=%s",
            contato.pk,
            mask_document(digits),
        )
        return contato, True


def parse_telefones_json(raw) -> list[dict]:
    """RV07 (4.2) — Parse + valida o JSON do editor de telefones (Alpine).

    Formato: ``[{"id"?, "tipo", "numero", "is_principal"}]``. Aceita string JSON
    ou lista já parseada. Retorna lista limpa (números vazios ignorados, tipo
    inválido vira 'celular', no máximo 1 principal). Compartilhado por
    ContatoForm e pela criação inline de contato (Lead/Oportunidade).
    """
    import json

    from .models import ContatoTelefone

    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        try:
            items = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(items, list):
        return []

    valid_tipos = {c[0] for c in ContatoTelefone.Tipo.choices}
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        numero = (item.get("numero") or "").strip()
        if not numero:
            continue
        tipo = item.get("tipo")
        if tipo not in valid_tipos:
            tipo = ContatoTelefone.Tipo.CELULAR
        entry = {
            "tipo": tipo,
            "numero": numero[:20],
            "is_principal": bool(item.get("is_principal", False)),
        }
        raw_id = item.get("id")
        if raw_id not in (None, "", 0):
            try:
                entry["id"] = int(raw_id)
            except (TypeError, ValueError):
                pass
        cleaned.append(entry)

    principal_seen = False
    for entry in cleaned:
        if entry["is_principal"] and not principal_seen:
            principal_seen = True
        elif entry["is_principal"]:
            entry["is_principal"] = False
    if cleaned and not principal_seen:
        cleaned[0]["is_principal"] = True
    return cleaned


def derive_primary_phones(tels) -> tuple[str, str]:
    """RV07 (4.2) — (phone, whatsapp) principais (denormalizados) a partir da
    lista de telefones, para compatibilidade com busca/autocomplete."""
    phone = ""
    whatsapp = ""
    principal = next((t for t in tels if t.get("is_principal")), None)
    whats = next(
        (t for t in tels if t.get("tipo") == "whatsapp" and t.get("numero")), None,
    )
    if principal and principal.get("numero"):
        phone = principal["numero"]
    elif tels:
        phone = tels[0].get("numero", "")
    if whats:
        whatsapp = whats["numero"]
    return phone[:20], whatsapp[:20]


def sync_contato_telefones(contato, tels, *, update_primary=True) -> None:
    """RV07 (4.2) — Reconcilia ContatoTelefone do contato com `tels` (mantém IDs
    presentes, deleta removidos, cria novos). Se ``update_primary``, sincroniza
    phone/whatsapp denormalizados. ``contato`` precisa ter pk."""
    from .models import ContatoTelefone

    kept_ids = {t["id"] for t in tels if "id" in t}
    contato.telefones.exclude(id__in=kept_ids).delete()
    existing = {o.id: o for o in contato.telefones.filter(id__in=kept_ids)}
    for idx, t in enumerate(tels):
        tid = t.get("id")
        if tid and tid in existing:
            obj = existing[tid]
            obj.tipo = t["tipo"]
            obj.numero = t["numero"]
            obj.is_principal = t["is_principal"]
            obj.order = idx
            obj.save(update_fields=[
                "tipo", "numero", "is_principal", "order", "updated_at",
            ])
        else:
            ContatoTelefone.objects.create(
                contato=contato, tipo=t["tipo"], numero=t["numero"],
                is_principal=t["is_principal"], order=idx,
            )
    if update_primary:
        phone, whatsapp = derive_primary_phones(tels)
        if (contato.phone or "") != phone or (contato.whatsapp or "") != whatsapp:
            contato.phone = phone
            contato.whatsapp = whatsapp
            contato.save(update_fields=["phone", "whatsapp", "updated_at"])


def resolve_contato_from_mode(
    empresa,
    *,
    mode: str,
    contato: Contato | None = None,
    new_name: str = "",
    new_document: str = "",
    new_phone: str = "",
    new_email: str = "",
    source: str = "",
    telefones_json=None,
) -> Contato | None:
    """RV07 — Resolve/cria o Contato a partir do modo dual (search/new).

    Centraliza a regra usada por LeadForm e OpportunityForm (item 5.1) para
    não duplicar a criação/vinculação de contato. RV07 (4.2): ``telefones_json``
    permite criar o contato já com múltiplos telefones (editor inline).

    - ``mode == 'new'``: cria (ou reaproveita por documento) um Contato.
    - qualquer outro modo ('search'): retorna o ``contato`` já selecionado.
    """
    if mode != "new":
        return contato

    tels = parse_telefones_json(telefones_json) if telefones_json else []
    if tels:
        phone, whatsapp = derive_primary_phones(tels)
    else:
        # fallback para o campo único legado quando não há editor de telefones
        phone = (new_phone or "").strip()
        whatsapp = phone

    new_doc = (new_document or "").strip()
    defaults = {
        "name": (new_name or "").strip(),
        "phone": phone,
        "whatsapp": whatsapp,
        "email": (new_email or "").strip(),
        "source": source or "",
    }
    created = True
    if new_doc:
        obj, created = get_or_create_contato_by_document(
            empresa, new_doc, defaults=defaults,
        )
    else:
        obj = Contato.objects.create(empresa=empresa, **defaults)

    # Cria os ContatoTelefone só se o contato foi CRIADO agora (não sobrescreve
    # os telefones de um contato existente reaproveitado por documento).
    if tels and created:
        sync_contato_telefones(obj, tels, update_primary=False)
    return obj


def get_or_create_contato_for_phone(
    empresa, phone: str, name: str | None = None,
) -> tuple[Contato, bool]:
    """RV06 — Encontra ou cria Contato pelo phone (WhatsApp inbound).

    Quando um cliente novo manda mensagem WhatsApp, queremos criar:
    - Lead (lazy) — já existe via _resolve_or_create_lead_lazy
    - Contato (NOVO) — esta função

    Estratégia:
    1. Procura Contato existente com phone OR whatsapp matching (case-tolerant)
    2. Se não existe, cria com phone+whatsapp preenchidos
    3. Sem CPF/CNPJ — pode ser preenchido depois quando o bot perguntar

    Retorna: (contato, created_bool). Idempotente.
    """
    phone_digits = "".join(c for c in (phone or "") if c.isdigit())
    if not phone_digits:
        raise ValueError("phone vazio — não dá pra criar Contato sem identificação")

    safe_name = (name or "").strip() or f"WhatsApp {phone_digits}"

    with transaction.atomic():
        # Tenta match por phone OU whatsapp (cobertura completa)
        existing = (
            Contato.objects.select_for_update()
            .filter(empresa=empresa)
            .filter(
                Q(phone__icontains=phone_digits)
                | Q(whatsapp__icontains=phone_digits)
            )
            .order_by("-updated_at")
            .first()
        )
        if existing is not None:
            logger.debug(
                "contacts: reused Contato id=%s for phone=%s (empresa=%s)",
                existing.pk, phone_digits, empresa.pk,
            )
            return existing, False

        contato = Contato.objects.create(
            empresa=empresa,
            name=safe_name,
            phone=phone_digits,
            whatsapp=phone_digits,
            source=Contato.Source.WHATSAPP,
        )
        logger.info(
            "contacts: created Contato id=%s via WhatsApp lazy phone=%s empresa=%s",
            contato.pk, phone_digits, empresa.pk,
        )
        return contato, True


def link_contato_to_lead(contato: Contato, lead) -> None:
    """Attach `contato` to `lead` if not already set. Skips cross-tenant."""
    if lead.contato_id == contato.pk:
        return
    if lead.empresa_id != contato.empresa_id:
        logger.warning(
            "contacts: refusing cross-tenant link contato=%s lead=%s",
            contato.pk,
            lead.pk,
        )
        return
    lead.contato = contato
    lead.save(update_fields=["contato", "updated_at"])


def link_contato_to_session(contato: Contato, session) -> None:
    """Persist contato_id in ChatbotSession.lead_data for downstream lookups."""
    if not session:
        return
    data = session.lead_data or {}
    if data.get("contato_id") == contato.pk:
        return
    data["contato_id"] = contato.pk
    data.setdefault("name", contato.name)
    data.setdefault("phone", contato.whatsapp_or_phone)
    data.setdefault("email", contato.email)
    session.lead_data = data
    session.save(update_fields=["lead_data", "updated_at"])


def search_contatos(empresa, query: str, limit: int = 20) -> QuerySet[Contato]:
    """Free-text search by name, document, phone or email — scoped to empresa."""
    qs = Contato.objects.filter(empresa=empresa, is_active=True)
    query = (query or "").strip()
    if not query:
        return qs.order_by("name")[:limit]

    digits = normalize_document(query)
    filters = (
        Q(name__icontains=query)
        | Q(phone__icontains=query)
        | Q(whatsapp__icontains=query)
        | Q(email__icontains=query)
        | Q(company__icontains=query)
    )
    if digits:
        filters |= Q(cpf_cnpj_normalized__startswith=digits)

    return qs.filter(filters).order_by("name")[:limit]

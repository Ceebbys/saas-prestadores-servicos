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

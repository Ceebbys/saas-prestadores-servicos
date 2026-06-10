"""RV08 (3.2) — Helper único para registrar eventos na timeline do Lead.

Chamado nos pontos que já centralizam os eventos (notificações de pipeline em
``communications.notifications_events._emit``, signals do CRM e a view de
registro de contato). Best-effort: nunca derruba a operação que o originou.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def log_lead_event(
    lead,
    event_type: str,
    title: str,
    *,
    description: str = "",
    actor=None,
    icon: str = "",
    metadata: dict | None = None,
):
    """Cria um ``LeadEvent``. Retorna o evento criado, ou ``None`` se sem lead."""
    if lead is None:
        return None
    from .models import LeadEvent

    safe_actor = actor if (actor is not None and getattr(actor, "is_authenticated", False)) else None
    try:
        return LeadEvent.objects.create(
            empresa=lead.empresa,
            lead=lead,
            event_type=event_type or LeadEvent.Type.OTHER,
            title=(title or "")[:200],
            description=(description or "")[:500],
            actor=safe_actor,
            icon=icon or "",
            metadata=metadata or {},
        )
    except Exception:  # noqa: BLE001
        logger.exception("log_lead_event_failed type=%s lead=%s", event_type, getattr(lead, "pk", None))
        return None

"""Celery tasks do chatbot.

Mantém as tarefas finas — toda regra de negócio fica em services.py.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps.accounts.models import Empresa

from .services import dispatch_inactivity_flows

logger = logging.getLogger(__name__)


@shared_task(name="apps.chatbot.tasks.run_triggers")
def run_triggers() -> dict:
    """Verifica fluxos de inatividade para todas as empresas ativas.

    Executado periodicamente por Celery beat (default: a cada 5 min).
    Idempotente: o cooldown e o lock por sender impedem disparos duplicados.
    """
    total = 0
    per_empresa: dict[str, int] = {}
    for empresa in Empresa.objects.all():
        try:
            dispatched = dispatch_inactivity_flows(empresa)
        except Exception:
            logger.exception(
                "chatbot: dispatch_inactivity_flows failed for empresa=%s",
                empresa.pk,
            )
            continue
        if dispatched:
            per_empresa[empresa.slug or empresa.name] = dispatched
            total += dispatched
    logger.info("chatbot.run_triggers: dispatched=%s per_empresa=%s", total, per_empresa)
    return {"dispatched": total, "per_empresa": per_empresa}

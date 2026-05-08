"""Signals da app proposals.

Captura `post_init` (memoriza status original) + `post_save` (compara e dispara
eventos de automação). Cobre TODOS os caminhos de mudança de status (view,
service, admin, etc.) sem ter que duplicar lógica em cada um.

Recursão é prevenida pela flag `_suppress_automation` no instance.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from apps.proposals.models import Proposal

logger = logging.getLogger(__name__)


# Atributo simples (sem double-underscore) para evitar name mangling em
# code paths fora de classes — o receiver é função de módulo.
_ORIGINAL_STATUS_ATTR = "_proposal_original_status"


@receiver(post_init, sender=Proposal)
def _proposal_post_init(sender, instance, **kwargs):
    """Memoriza o status original do banco para detectar transições."""
    setattr(instance, _ORIGINAL_STATUS_ATTR, instance.status)


@receiver(post_save, sender=Proposal)
def _proposal_post_save(sender, instance, created, **kwargs):
    """Dispara automações em criação e em transição de status."""
    # Defesa de recursão / casos especiais (seeds, imports)
    if getattr(instance, "_suppress_automation", False):
        return

    event = None
    if created:
        from apps.automation.models import PipelineAutomationRule
        event = PipelineAutomationRule.Event.PROPOSTA_CRIADA
    else:
        old = getattr(instance, _ORIGINAL_STATUS_ATTR, None)
        new = instance.status
        if old and old != new:
            from apps.automation.services import PROPOSAL_STATUS_TO_EVENT
            event = PROPOSAL_STATUS_TO_EVENT.get(new)

    if event:
        # Roda APÓS commit — falha em automação não desfaz o save do status.
        def _run():
            from apps.automation.services import execute_proposal_event
            execute_proposal_event(instance, event)

        transaction.on_commit(_run)

    # Atualiza estado memorizado para refletir o pós-save.
    setattr(instance, _ORIGINAL_STATUS_ATTR, instance.status)

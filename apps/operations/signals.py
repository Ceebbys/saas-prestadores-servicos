"""RV10 — Signals para disparar PipelineAutomationRule a partir de OS.

Cliente reportou: "vou encerrar um serviço aqui ele vai entrar no
pos-venda. então tipo na hr q eu apertar concluir OS teria q mudar na
pipeline". Hoje só eventos de proposta moviam o pipeline.

Padrão: pre_save captura status anterior, post_save dispara o evento
correspondente APÓS o commit (para que falhas em automação não desfaçam
o save do status).
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.operations.models import WorkOrder

logger = logging.getLogger(__name__)

_PREVIOUS_STATUS_ATTR = "_workorder_previous_status"


@receiver(pre_save, sender=WorkOrder)
def _capture_previous_status(sender, instance: WorkOrder, **kwargs) -> None:
    """Lê o status atual no DB para detectar transições no post_save."""
    if not instance.pk:
        setattr(instance, _PREVIOUS_STATUS_ATTR, None)
        return
    try:
        prev = WorkOrder.objects.only("status").get(pk=instance.pk)
        setattr(instance, _PREVIOUS_STATUS_ATTR, prev.status)
    except WorkOrder.DoesNotExist:
        setattr(instance, _PREVIOUS_STATUS_ATTR, None)


@receiver(post_save, sender=WorkOrder)
def _dispatch_pipeline_event(sender, instance: WorkOrder, created: bool, **kwargs) -> None:
    """RV10 — Dispara regra de PipelineAutomationRule no commit.

    - Em criação: dispara OS_CRIADA
    - Em transição de status: dispara o evento mapeado em WORK_ORDER_STATUS_TO_EVENT
      (os_agendada, os_iniciada, os_pausada, os_concluida, os_cancelada)

    Defesas:
    - flag `_suppress_automation` previne loops (improvável aqui, mas defensivo)
    - on_commit garante que rollback descarta o dispatch
    - import lazy para evitar circular
    """
    if getattr(instance, "_suppress_automation", False):
        return

    from apps.automation.models import PipelineAutomationRule
    from apps.automation.services import (
        WORK_ORDER_STATUS_TO_EVENT,
        execute_work_order_event,
    )

    if created:
        event = PipelineAutomationRule.Event.OS_CRIADA
    else:
        previous = getattr(instance, _PREVIOUS_STATUS_ATTR, None)
        if previous == instance.status:
            return
        event = WORK_ORDER_STATUS_TO_EVENT.get(instance.status)

    if not event:
        return

    def _run():
        execute_work_order_event(instance, event)

    transaction.on_commit(_run)

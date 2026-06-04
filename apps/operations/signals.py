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
_PREV_SCHED_ATTR = "_workorder_prev_sched"  # (scheduled_date, expected_end_date, title)


@receiver(pre_save, sender=WorkOrder)
def _capture_previous_status(sender, instance: WorkOrder, **kwargs) -> None:
    """Lê status + campos de agenda atuais no DB p/ detectar mudanças no post_save."""
    if not instance.pk:
        setattr(instance, _PREVIOUS_STATUS_ATTR, None)
        setattr(instance, _PREV_SCHED_ATTR, None)
        return
    try:
        prev = WorkOrder.objects.only(
            "status", "scheduled_date", "expected_end_date", "title",
        ).get(pk=instance.pk)
        setattr(instance, _PREVIOUS_STATUS_ATTR, prev.status)
        setattr(instance, _PREV_SCHED_ATTR, (
            prev.scheduled_date, prev.expected_end_date, prev.title,
        ))
    except WorkOrder.DoesNotExist:
        setattr(instance, _PREVIOUS_STATUS_ATTR, None)
        setattr(instance, _PREV_SCHED_ATTR, None)


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


@receiver(post_save, sender=WorkOrder)
def _sync_work_order_to_google(sender, instance: WorkOrder, created: bool, **kwargs) -> None:
    """RV07 (Epic 7) — espelha a OS na agenda Google quando o agendamento muda.

    Só dispara quando há algo a sincronizar (OS agendada, ou evento órfão a
    remover) E quando campos de agenda/título mudaram — evita chamar a API do
    Google em toda troca de status. No-op seguro quando não há integração
    conectada. A gravação do id é feita com .update() lá no service, então
    isto NÃO entra em loop.
    """
    if getattr(instance, "_suppress_calendar_sync", False):
        return

    prev = getattr(instance, _PREV_SCHED_ATTR, None)
    cur = (instance.scheduled_date, instance.expected_end_date, instance.title)
    if not created and prev == cur:
        return  # nada relevante de agenda mudou
    if not instance.scheduled_date and not instance.google_event_id:
        return  # nada a criar nem a remover

    def _run():
        try:
            from apps.integrations.services import sync_work_order_to_calendar
            sync_work_order_to_calendar(instance)
        except Exception:  # noqa: BLE001
            logger.exception("wo google calendar sync failed wo=%s", instance.pk)

    transaction.on_commit(_run)

"""RV05-F + RV10 — Signals para auditoria de mudança de status do Contract.

RV05-F: captura `from_status` no pre_save, cria `ContractStatusHistory`
no post_save se o status mudou.

RV10: também dispara regras de PipelineAutomationRule quando o status
muda. Cliente pediu: 'qualquer evento deveria poder mover o pipeline'.

O autor (`changed_by`) NÃO vem do signal — é setado opcionalmente pela
view que dispara a mudança via `contract._status_changed_by = request.user`
antes do .save(). Sem isso, fica null (admin/management commands).
"""
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.contracts.models import Contract, ContractStatusHistory


_PREVIOUS_STATUS_ATTR = "_contracts_previous_status"


@receiver(pre_save, sender=Contract)
def _capture_previous_status(sender, instance: Contract, **kwargs) -> None:
    """Antes de salvar, lê o status no DB (ou marca como None se for novo)."""
    if not instance.pk:
        setattr(instance, _PREVIOUS_STATUS_ATTR, None)
        return
    try:
        prev = Contract.all_objects.only("status").get(pk=instance.pk)
        setattr(instance, _PREVIOUS_STATUS_ATTR, prev.status)
    except Contract.DoesNotExist:
        setattr(instance, _PREVIOUS_STATUS_ATTR, None)


@receiver(post_save, sender=Contract)
def _record_status_change(sender, instance: Contract, created: bool, **kwargs) -> None:
    """Após salvar, registra ContractStatusHistory se houve mudança de status.

    Em criação: registra a transição ∅ → status_atual.
    Em update: registra prev → atual apenas se diferentes.
    """
    previous = getattr(instance, _PREVIOUS_STATUS_ATTR, None)
    if created:
        # Primeiro registro: from_status="" para indicar criação
        ContractStatusHistory.objects.create(
            contract=instance,
            from_status="",
            to_status=instance.status,
            changed_by=getattr(instance, "_status_changed_by", None),
            note=getattr(instance, "_status_change_note", "") or "",
        )
        # RV10 — dispara automação de pipeline para CONTRATO_CRIADO
        _dispatch_pipeline_event(instance, created=True, previous=None)
        return
    if previous == instance.status:
        return
    ContractStatusHistory.objects.create(
        contract=instance,
        from_status=previous or "",
        to_status=instance.status,
        changed_by=getattr(instance, "_status_changed_by", None),
        note=getattr(instance, "_status_change_note", "") or "",
    )
    # RV10 — dispara automação de pipeline para a transição de status
    _dispatch_pipeline_event(instance, created=False, previous=previous)
    # RV07 (6.2) — notifica contrato enviado/assinado
    from apps.communications.notifications_events import (
        notify_contract_sent,
        notify_contract_signed,
    )
    if instance.status == Contract.Status.SENT:
        notify_contract_sent(instance)
    elif instance.status == Contract.Status.SIGNED:
        notify_contract_signed(instance)


def _dispatch_pipeline_event(instance: Contract, *, created: bool, previous) -> None:
    """RV10 — Dispara regras de PipelineAutomationRule no commit.

    Roda APÓS o commit para que falhas em automação não desfaçam o save.
    Flag `_suppress_automation` previne loops (signal de Lead movido pela
    automação não re-dispara isso).
    """
    if getattr(instance, "_suppress_automation", False):
        return
    from apps.automation.models import PipelineAutomationRule
    from apps.automation.services import (
        CONTRACT_STATUS_TO_EVENT,
        execute_contract_event,
    )

    if created:
        event = PipelineAutomationRule.Event.CONTRATO_CRIADO
    else:
        event = CONTRACT_STATUS_TO_EVENT.get(instance.status)
    if not event:
        return

    def _run():
        execute_contract_event(instance, event)

    transaction.on_commit(_run)

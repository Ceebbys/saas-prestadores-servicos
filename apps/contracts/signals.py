"""RV05-F — Signals para auditoria de mudança de status do Contract.

Espelha o padrão usado em ProposalStatusSignal: captura `from_status` no
pre_save, cria `ContractStatusHistory` no post_save se o status mudou.

O autor (`changed_by`) NÃO vem do signal — é setado opcionalmente pela
view que dispara a mudança via `contract._status_changed_by = request.user`
antes do .save(). Sem isso, fica null (admin/management commands).
"""
from __future__ import annotations

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

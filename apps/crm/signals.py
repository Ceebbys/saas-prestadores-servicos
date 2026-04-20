"""Signals do módulo CRM.

Mantém coerência entre Lead, Opportunity, PipelineStage e LeadContact:

- Ao criar um Lead, garante que ele tenha uma pipeline_stage válida e cria
  automaticamente uma Opportunity na mesma stage (conversão automática).
- Ao mudar a stage de um Lead, sincroniza as Opportunities vinculadas.
- Ao mudar o current_stage de uma Opportunity, sincroniza o Lead associado.
- Ao deletar uma PipelineStage, reatribui os leads órfãos para a stage
  anterior (ou a primeira stage como fallback), evitando SET_NULL silencioso.
- Ao concluir uma ChatbotSession com Lead vinculado, registra um LeadContact
  automaticamente (canal CHATBOT), de forma idempotente via external_ref.
"""

from __future__ import annotations

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import Lead, LeadContact, Opportunity, Pipeline, PipelineStage


def _get_default_first_stage(empresa) -> PipelineStage | None:
    pipeline = Pipeline.objects.filter(empresa=empresa, is_default=True).first()
    if not pipeline:
        pipeline = Pipeline.objects.filter(empresa=empresa).first()
    if not pipeline:
        return None
    return pipeline.stages.order_by("order").first()


@receiver(post_save, sender=Lead)
def lead_post_save(sender, instance: Lead, created: bool, **kwargs):
    """On create: ensure stage + auto-create Opportunity.
    On update: if pipeline_stage changed, sync Opportunities.
    """
    if created:
        if instance.pipeline_stage_id is None:
            stage = _get_default_first_stage(instance.empresa)
            if stage is not None:
                Lead.objects.filter(pk=instance.pk).update(pipeline_stage=stage)
                instance.pipeline_stage = stage

        if instance.pipeline_stage_id and not instance.opportunities.exists():
            Opportunity.objects.create(
                empresa=instance.empresa,
                lead=instance,
                pipeline=instance.pipeline_stage.pipeline,
                current_stage=instance.pipeline_stage,
                title=instance.name,
                value=0,
                assigned_to=instance.assigned_to,
            )
        return

    # Update: sync downstream opportunities if stage changed
    if instance.pipeline_stage_id:
        instance.opportunities.exclude(
            current_stage_id=instance.pipeline_stage_id
        ).update(current_stage_id=instance.pipeline_stage_id)


@receiver(post_save, sender=Opportunity)
def opportunity_post_save(sender, instance: Opportunity, created: bool, **kwargs):
    """Keep Lead.pipeline_stage aligned with Opportunity.current_stage.

    Only syncs when lead and opportunity belong to the same empresa, to
    avoid cross-tenant data corruption if form filtering is ever bypassed.
    """
    if not (instance.current_stage_id and instance.lead_id):
        return
    lead = instance.lead
    if lead.empresa_id != instance.empresa_id:
        return
    if lead.pipeline_stage_id != instance.current_stage_id:
        Lead.objects.filter(pk=lead.pk).update(
            pipeline_stage_id=instance.current_stage_id
        )


@receiver(pre_delete, sender=PipelineStage)
def pipeline_stage_pre_delete(sender, instance: PipelineStage, **kwargs):
    """Reassign leads to the previous stage before the FK goes NULL."""
    affected_leads = Lead.objects.filter(pipeline_stage=instance)
    if not affected_leads.exists():
        return

    fallback = (
        instance.pipeline.stages.exclude(pk=instance.pk)
        .filter(order__lte=instance.order)
        .order_by("-order")
        .first()
        or instance.pipeline.stages.exclude(pk=instance.pk).order_by("order").first()
    )
    if fallback:
        affected_leads.update(pipeline_stage=fallback)


def _chatbot_session_completed(sender, instance, created: bool, **kwargs):
    """Create LeadContact (channel=CHATBOT) when a session reaches COMPLETED."""
    if not instance.lead_id:
        return
    try:
        completed_value = sender.Status.COMPLETED.value
    except AttributeError:
        completed_value = "completed"
    if instance.status != completed_value:
        return

    lead = instance.lead
    ref = str(instance.session_key)
    LeadContact.objects.get_or_create(
        empresa=lead.empresa,
        lead=lead,
        external_ref=ref,
        defaults={
            "channel": LeadContact.Channel.CHATBOT,
            "note": "Sessão do chatbot concluída.",
        },
    )


def register_chatbot_signal():
    """Ligado em runtime para evitar import circular no app chatbot."""
    try:
        from apps.chatbot.models import ChatbotSession
    except Exception:
        return
    post_save.connect(
        _chatbot_session_completed,
        sender=ChatbotSession,
        dispatch_uid="crm.leadcontact_from_chatbot_session",
    )


register_chatbot_signal()

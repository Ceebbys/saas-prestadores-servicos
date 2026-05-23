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

import logging

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import Lead, LeadContact, Opportunity, Pipeline, PipelineStage

logger = logging.getLogger(__name__)


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

    RV06 — Sempre que o Lead estiver em uma stage com is_won=True,
    dispara generate_entry_from_lead_won (idempotente — só cria 1 entry).
    Cobre o caso de negócio fechado SEM proposta/contrato formal
    (ex.: acordo via WhatsApp), pedido do cliente.
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
        # Lead criado já em stage de ganho? gera entry mesmo assim
        _maybe_generate_finance_entry(instance)
        return

    # Update: sync downstream opportunities if stage changed
    if instance.pipeline_stage_id:
        instance.opportunities.exclude(
            current_stage_id=instance.pipeline_stage_id
        ).update(current_stage_id=instance.pipeline_stage_id)

    # RV06 — Gera entry financeira se virou WON (idempotente)
    _maybe_generate_finance_entry(instance)


def _maybe_generate_finance_entry(lead: Lead) -> None:
    """Cria FinancialEntry se o Lead está em stage is_won=True.

    Idempotente: o helper generate_entry_from_lead_won não duplica.
    Erros são logados mas não propagam (não bloqueia o save do Lead).
    """
    try:
        if not lead.pipeline_stage_id:
            return
        # Carrega stage com is_won (evita query extra se já estiver na FK)
        stage = lead.pipeline_stage
        if not stage or not stage.is_won:
            return
        from apps.finance.services import generate_entry_from_lead_won
        generate_entry_from_lead_won(lead)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Erro ao gerar FinancialEntry para Lead %s (won-stage trigger)",
            lead.pk,
        )


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
    """Captura IDs e fallback para re-atribuição em post_delete.

    Não atualiza aqui: o Django já agendou um SET_NULL via on_delete que vai
    rodar APÓS o pre_delete, sobrescrevendo qualquer update prematuro. Por
    isso capturamos o snapshot e aplicamos a re-atribuição no post_delete,
    quando o SET_NULL já ocorreu.
    """
    affected_ids = list(
        Lead.objects.filter(pipeline_stage=instance).values_list("pk", flat=True)
    )
    fallback = (
        instance.pipeline.stages.exclude(pk=instance.pk)
        .filter(order__lte=instance.order)
        .order_by("-order")
        .first()
        or instance.pipeline.stages.exclude(pk=instance.pk).order_by("order").first()
    )
    instance._affected_lead_ids = affected_ids
    instance._fallback_stage_id = fallback.pk if fallback else None


from django.db.models.signals import post_delete  # noqa: E402


@receiver(post_delete, sender=PipelineStage)
def pipeline_stage_post_delete(sender, instance: PipelineStage, **kwargs):
    """Aplica fallback para leads que ficaram com pipeline_stage=NULL após
    SET_NULL."""
    affected = getattr(instance, "_affected_lead_ids", None)
    fallback_id = getattr(instance, "_fallback_stage_id", None)
    if affected and fallback_id:
        Lead.objects.filter(pk__in=affected, pipeline_stage__isnull=True).update(
            pipeline_stage_id=fallback_id,
        )


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
    # Defesa em profundidade: garante que session.flow e lead pertencem
    # à mesma empresa antes de criar LeadContact (evita cross-tenant leak
    # caso uma session seja manipulada para apontar para um lead de outra
    # empresa).
    flow_empresa_id = getattr(getattr(instance, "flow", None), "empresa_id", None)
    if flow_empresa_id is not None and flow_empresa_id != lead.empresa_id:
        logger.warning(
            "crm: refusing cross-tenant LeadContact (flow.empresa=%s lead.empresa=%s)",
            flow_empresa_id, lead.empresa_id,
        )
        return

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

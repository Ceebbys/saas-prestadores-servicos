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
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from .models import Lead, LeadContact, Opportunity, Pipeline, PipelineStage

logger = logging.getLogger(__name__)


_LEAD_PREVIOUS_STAGE_ATTR = "_lead_previous_stage_id"


@receiver(pre_save, sender=Lead)
def _lead_capture_previous_stage(sender, instance: Lead, **kwargs) -> None:
    """RV10 — Lê o pipeline_stage_id anterior para detectar transições.

    Necessário no post_save para decidir se dispara LEAD_GANHO/LEAD_PERDIDO
    (transições para stage com is_won/is_lost).
    """
    if not instance.pk:
        setattr(instance, _LEAD_PREVIOUS_STAGE_ATTR, None)
        return
    try:
        prev = Lead.objects.only("pipeline_stage_id").get(pk=instance.pk)
        setattr(instance, _LEAD_PREVIOUS_STAGE_ATTR, prev.pipeline_stage_id)
    except Lead.DoesNotExist:
        setattr(instance, _LEAD_PREVIOUS_STAGE_ATTR, None)


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

        # RV07 — `_suppress_auto_opportunity` permite que a OpportunityForm
        # crie o Lead inline (item 5.1) SEM gerar uma 2ª oportunidade — a
        # própria form já cria a oportunidade configurada pelo usuário.
        if (
            instance.pipeline_stage_id
            and not instance.opportunities.exists()
            and not getattr(instance, "_suppress_auto_opportunity", False)
        ):
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
        # RV10 — dispara automação de pipeline (LEAD_CRIADO + possível LEAD_GANHO)
        _maybe_dispatch_lead_pipeline_event(instance, created=True, previous_stage_id=None)
        return

    # Update: sync downstream opportunities if stage changed
    if instance.pipeline_stage_id:
        instance.opportunities.exclude(
            current_stage_id=instance.pipeline_stage_id
        ).update(current_stage_id=instance.pipeline_stage_id)

    # RV06 — Gera entry financeira se virou WON (idempotente)
    _maybe_generate_finance_entry(instance)
    # RV10 — dispara automação de pipeline em update (LEAD_GANHO/LEAD_PERDIDO)
    previous_stage_id = getattr(instance, _LEAD_PREVIOUS_STAGE_ATTR, None)
    _maybe_dispatch_lead_pipeline_event(
        instance, created=False, previous_stage_id=previous_stage_id,
    )


def _maybe_dispatch_lead_pipeline_event(
    lead: Lead, *, created: bool, previous_stage_id,
) -> None:
    """RV10 — Dispara eventos de pipeline para o próprio Lead.

    Eventos:
    - LEAD_CRIADO: na criação do lead
    - LEAD_GANHO: ao entrar em stage com is_won=True (transição)
    - LEAD_PERDIDO: ao entrar em stage com is_lost=True (transição)

    Defesas:
    - `_suppress_automation` previne loop quando a própria regra mudou o stage
    - on_commit garante que rollback descarta o dispatch
    - falhas no fetch da stage_atual NÃO derrubam o save (try/except)
    """
    if getattr(lead, "_suppress_automation", False):
        return
    try:
        from apps.automation.models import PipelineAutomationRule
        from apps.automation.services import execute_lead_event
    except Exception:  # noqa: BLE001
        logger.exception("RV10: falha importando services de automação")
        return

    events_to_fire: list[str] = []
    if created:
        events_to_fire.append(PipelineAutomationRule.Event.LEAD_CRIADO)

    # Detecta transição won/lost (vale tanto para create quanto update)
    stage_changed = (
        created and lead.pipeline_stage_id is not None
    ) or (
        not created and previous_stage_id != lead.pipeline_stage_id
    )
    if stage_changed and lead.pipeline_stage_id:
        try:
            stage = lead.pipeline_stage
            if stage and stage.is_won:
                events_to_fire.append(PipelineAutomationRule.Event.LEAD_GANHO)
            elif stage and stage.is_lost:
                events_to_fire.append(PipelineAutomationRule.Event.LEAD_PERDIDO)
            # RV07 (6.2) — "lead movimentado" só em transições reais de etapa
            # que NÃO sejam ganho/perdido (won já notifica LEAD_WON) e nunca na
            # criação. Como estamos após o guard de `_suppress_automation`, um
            # movimento feito por regra de automação não gera dupla notificação.
            elif not created and stage:
                from apps.communications.notifications_events import (
                    notify_lead_moved,
                )
                notify_lead_moved(lead, None, stage)
        except Exception:  # noqa: BLE001
            logger.exception(
                "RV10: falha lendo pipeline_stage para detectar won/lost (lead=%s)",
                lead.pk,
            )

    if not events_to_fire:
        return

    def _run():
        for ev in events_to_fire:
            execute_lead_event(lead, ev)

    transaction.on_commit(_run)


def _maybe_generate_finance_entry(lead: Lead) -> None:
    """Cria FinancialEntry se o Lead está em stage is_won=True.

    Idempotente: o helper generate_entry_from_lead_won não duplica.
    Erros são logados mas não propagam (não bloqueia o save do Lead).

    RV10 — Respeita APENAS `_suppress_finance_entry` (flag dedicada para
    scripts/seeds que querem evitar criação automática).

    IMPORTANTE: NÃO respeita `_suppress_automation`. Esse último é usado
    pelo `automation._apply_rule` para prevenir loop de pipeline e NÃO
    deve impedir criação de entry — senão, ao mover lead via regra de
    automação (ex.: "Proposta Aceita → Ganho"), nenhuma entry é gerada
    e o cliente vê o banner de "leads pendentes" no /finance/ (quebra
    o fluxo principal do RV10).
    """
    if getattr(lead, "_suppress_finance_entry", False):
        return
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

    RV07 — Também propaga o valor da oportunidade (Opportunity.value),
    digitado na Pipeline, para o Lead (estimated_value) quando o lead ainda
    não tem valor próprio. Sem isso o lançamento financeiro automático (que
    lê lead.estimated_value) nascia com R$ 0,00 mesmo com o valor informado
    no card da pipeline. Além disso, se a oportunidade entrou numa etapa de
    ganho, garante a geração da entry financeira (idempotente): o sync de
    stage usa .update(), que NÃO dispara o post_save do Lead, então sem isto
    mover pelo board de oportunidades não criava o lançamento.
    """
    if not (instance.current_stage_id and instance.lead_id):
        return
    lead = instance.lead
    if lead.empresa_id != instance.empresa_id:
        return

    update_fields: dict = {}
    if lead.pipeline_stage_id != instance.current_stage_id:
        update_fields["pipeline_stage_id"] = instance.current_stage_id

    # Coerção defensiva: instance.value pode ser str (atribuído antes da
    # coerção do DB, ex.: Opportunity(value="1500")) — normaliza para Decimal
    # antes de comparar, senão `str > 0` levanta TypeError e derruba o save.
    opp_value = instance.value
    if opp_value is not None and not isinstance(opp_value, Decimal):
        try:
            opp_value = Decimal(str(opp_value))
        except (InvalidOperation, ValueError, TypeError):
            opp_value = None
    lead_value = lead.estimated_value
    if (
        opp_value
        and opp_value > 0
        and (lead_value is None or lead_value <= 0)
    ):
        update_fields["estimated_value"] = opp_value

    if not update_fields:
        return

    Lead.objects.filter(pk=lead.pk).update(**update_fields)
    # Reflete o novo estado no objeto em memória p/ o gerador de entry ler
    if "pipeline_stage_id" in update_fields:
        lead.pipeline_stage_id = instance.current_stage_id
        lead.pipeline_stage = instance.current_stage
    if "estimated_value" in update_fields:
        lead.estimated_value = update_fields["estimated_value"]

    # Oportunidade entrou em etapa de ganho? Garante a entry financeira
    # (idempotente — generate_entry_from_lead_won não duplica).
    if instance.current_stage and instance.current_stage.is_won:
        _maybe_generate_finance_entry(lead)


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

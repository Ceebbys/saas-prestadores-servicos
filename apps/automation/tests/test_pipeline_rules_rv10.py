"""RV10 — Eventos de OS/Contrato/Lead nas regras de automação de pipeline.

Cliente reportou: "vou encerrar um serviço aqui ele vai entrar no pos-venda.
então tipo na hr q eu apertar concluir OS teria q mudar na pipeline".
Hoje só eventos de proposta moviam o pipeline. Agora também Contrato, OS
e o próprio Lead disparam regras.

Cobre:
- execute_work_order_event move lead quando OS muda status
- execute_contract_event move lead quando contrato muda status
- execute_lead_event move lead em LEAD_CRIADO/LEAD_GANHO/LEAD_PERDIDO
- Signals disparam automaticamente nas transições reais
- Recursão prevenida pela flag _suppress_automation
- Múltiplas regras: cada uma é avaliada isoladamente
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.automation.models import AutomationLog, PipelineAutomationRule
from apps.automation.services import (
    execute_contract_event,
    execute_lead_event,
    execute_work_order_event,
)
from apps.contracts.models import Contract
from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.operations.models import WorkOrder
from apps.proposals.models import Proposal
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _setup(empresa):
    create_pipeline_for_empresa(empresa)
    pipeline = Pipeline.objects.filter(empresa=empresa, is_default=True).first()
    stages = list(pipeline.stages.order_by("order"))
    return pipeline, stages


class WorkOrderEventTests(TestCase):
    """RV10 — Direct call de execute_work_order_event move lead."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("a@t.com", "A", self.empresa)
        self.pipeline, self.stages = _setup(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente",
            pipeline_stage=self.stages[0],
        )
        self.work_order = WorkOrder.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="OS Topografia",
            priority=WorkOrder.Priority.MEDIUM,
        )

    def test_os_concluida_moves_lead(self):
        target = self.stages[-1]  # última stage = pós-venda
        PipelineAutomationRule.objects.create(
            empresa=self.empresa,
            name="Concluir OS → Pós-Venda",
            event=PipelineAutomationRule.Event.OS_CONCLUIDA,
            target_pipeline=self.pipeline, target_stage=target,
            is_active=True,
        )
        execute_work_order_event(
            self.work_order,
            PipelineAutomationRule.Event.OS_CONCLUIDA,
        )
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, target.pk)
        # Log foi criado com source_entity_type='work_order'
        log = AutomationLog.objects.filter(
            entity_type=AutomationLog.EntityType.LEAD,
            entity_id=self.lead.pk,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.source_entity_type, "work_order")
        self.assertEqual(log.source_entity_id, self.work_order.pk)

    def test_inactive_rule_does_not_move_lead(self):
        target = self.stages[-1]
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Inativa",
            event=PipelineAutomationRule.Event.OS_CONCLUIDA,
            target_pipeline=self.pipeline, target_stage=target,
            is_active=False,
        )
        execute_work_order_event(
            self.work_order,
            PipelineAutomationRule.Event.OS_CONCLUIDA,
        )
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, self.stages[0].pk)

    def test_os_without_lead_logs_skip(self):
        target = self.stages[-1]
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="X",
            event=PipelineAutomationRule.Event.OS_CONCLUIDA,
            target_pipeline=self.pipeline, target_stage=target,
            is_active=True,
        )
        # OS sem lead
        orphan = WorkOrder.objects.create(
            empresa=self.empresa, title="OS Sem Lead",
            priority=WorkOrder.Priority.MEDIUM,
        )
        execute_work_order_event(
            orphan, PipelineAutomationRule.Event.OS_CONCLUIDA,
        )
        log = AutomationLog.objects.filter(
            entity_type=AutomationLog.EntityType.WORK_ORDER,
            entity_id=orphan.pk,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get("skipped"), "no_lead")


class WorkOrderSignalIntegrationTests(TestCase):
    """RV10 — Mudar status da OS dispara regra via signal automaticamente."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("s@t.com", "S", self.empresa)
        self.pipeline, self.stages = _setup(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Lead",
            pipeline_stage=self.stages[0],
        )
        self.target = self.stages[-1]
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Concluir OS",
            event=PipelineAutomationRule.Event.OS_CONCLUIDA,
            target_pipeline=self.pipeline, target_stage=self.target,
            is_active=True,
        )

    def test_concluir_os_via_save_dispara_signal(self):
        """Smoke: salvar OS com status=completed move lead."""
        wo = WorkOrder.objects.create(
            empresa=self.empresa, lead=self.lead, title="OS",
            priority=WorkOrder.Priority.MEDIUM,
            status=WorkOrder.Status.IN_PROGRESS,
        )
        with self.captureOnCommitCallbacks(execute=True):
            wo.status = WorkOrder.Status.COMPLETED
            wo.completed_at = timezone.now()
            wo.save()
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, self.target.pk)


class ContractEventTests(TestCase):
    """RV10 — Eventos de Contrato disparam movimentação de pipeline."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("c@t.com", "C", self.empresa)
        self.pipeline, self.stages = _setup(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente",
            pipeline_stage=self.stages[0],
        )

    def test_contrato_assinado_moves_lead(self):
        target = self.stages[2]
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Assinar → Execução",
            event=PipelineAutomationRule.Event.CONTRATO_ASSINADO,
            target_pipeline=self.pipeline, target_stage=target,
            is_active=True,
        )
        contract = Contract.objects.create(
            empresa=self.empresa, lead=self.lead, title="C",
            content="x", value=Decimal("1000"),
            status=Contract.Status.DRAFT,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=365),
        )
        execute_contract_event(
            contract, PipelineAutomationRule.Event.CONTRATO_ASSINADO,
        )
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, target.pk)


class ContractSignalIntegrationTests(TestCase):
    """RV10 — Mudar status do contrato via .save() dispara regra."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("sc@t.com", "SC", self.empresa)
        self.pipeline, self.stages = _setup(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="L",
            pipeline_stage=self.stages[0],
        )
        self.target = self.stages[2]
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Assinar",
            event=PipelineAutomationRule.Event.CONTRATO_ASSINADO,
            target_pipeline=self.pipeline, target_stage=self.target,
            is_active=True,
        )

    def test_assinar_contrato_via_save_dispara_signal(self):
        contract = Contract.objects.create(
            empresa=self.empresa, lead=self.lead, title="C",
            content="x", value=Decimal("1000"),
            status=Contract.Status.DRAFT,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=365),
        )
        with self.captureOnCommitCallbacks(execute=True):
            contract.status = Contract.Status.SIGNED
            contract.save()
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, self.target.pk)


class LeadEventTests(TestCase):
    """RV10 — Eventos do próprio Lead (LEAD_GANHO, LEAD_PERDIDO, LEAD_CRIADO)."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("l@t.com", "L", self.empresa)
        self.pipeline, self.stages = _setup(self.empresa)
        # Marca a última stage como is_won pra testar LEAD_GANHO
        self.won_stage = self.stages[-1]
        self.won_stage.is_won = True
        self.won_stage.save()
        # Stage extra que NÃO é won/lost
        self.intermediate = self.stages[2]

    def test_lead_criado_dispara_evento_via_signal(self):
        """Lead novo dispara LEAD_CRIADO automaticamente."""
        target = self.intermediate
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Lead novo",
            event=PipelineAutomationRule.Event.LEAD_CRIADO,
            target_pipeline=self.pipeline, target_stage=target,
            is_active=True,
        )
        with self.captureOnCommitCallbacks(execute=True):
            lead = Lead.objects.create(
                empresa=self.empresa, name="Novo Lead",
                pipeline_stage=self.stages[0],
            )
        lead.refresh_from_db()
        self.assertEqual(lead.pipeline_stage_id, target.pk)

    def test_lead_ganho_dispara_via_transition_para_won_stage(self):
        """Mover lead para stage com is_won=True dispara LEAD_GANHO."""
        target = self.intermediate  # destino quando ganha
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Ganhou → Intermediate",
            event=PipelineAutomationRule.Event.LEAD_GANHO,
            target_pipeline=self.pipeline, target_stage=target,
            is_active=True,
        )
        lead = Lead.objects.create(
            empresa=self.empresa, name="Lead",
            pipeline_stage=self.stages[0],
        )
        # Move pra won_stage (deve disparar LEAD_GANHO)
        with self.captureOnCommitCallbacks(execute=True):
            lead.pipeline_stage = self.won_stage
            lead.save()
        lead.refresh_from_db()
        # LEAD_GANHO disparou → regra move pra `target` (intermediate)
        # Mas só se o `_suppress_automation` não estiver setado.
        # Como a regra move + seta a flag, o próximo signal não re-dispara.
        self.assertEqual(lead.pipeline_stage_id, target.pk)

    def test_execute_lead_event_direct_call(self):
        """Smoke: chamar execute_lead_event diretamente."""
        target = self.intermediate
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Direct",
            event=PipelineAutomationRule.Event.LEAD_CRIADO,
            target_pipeline=self.pipeline, target_stage=target,
            is_active=True,
        )
        lead = Lead.objects.create(
            empresa=self.empresa, name="L",
            pipeline_stage=self.stages[0],
        )
        # Bypass signal (já rodou no create) — chama direto
        # E reseta stage para testar
        lead._suppress_automation = True
        lead.pipeline_stage = self.stages[0]
        lead.save()
        # Call direto
        execute_lead_event(lead, PipelineAutomationRule.Event.LEAD_CRIADO)
        lead.refresh_from_db()
        self.assertEqual(lead.pipeline_stage_id, target.pk)


class CrossSourceTests(TestCase):
    """RV10 — Mistura: regra para evento de OS coexiste com regra para proposta."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("x@t.com", "X", self.empresa)
        self.pipeline, self.stages = _setup(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="L",
            pipeline_stage=self.stages[0],
        )

    def test_proposta_e_os_movem_para_etapas_diferentes(self):
        """Regra de proposta aceita move para X; regra de OS concluída move para Y."""
        stage_negociacao = self.stages[1]
        stage_pos_venda = self.stages[-1]
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Aceita → Negociação",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=self.pipeline, target_stage=stage_negociacao,
            is_active=True,
        )
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="OS Concluída → Pós-Venda",
            event=PipelineAutomationRule.Event.OS_CONCLUIDA,
            target_pipeline=self.pipeline, target_stage=stage_pos_venda,
            is_active=True,
        )

        # 1. Aceita proposta → Lead vai para Negociação
        proposal = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="P",
            discount_percent=Decimal("0"),
        )
        with self.captureOnCommitCallbacks(execute=True):
            proposal.status = Proposal.Status.ACCEPTED
            proposal.save()
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, stage_negociacao.pk)

        # 2. Conclui OS → Lead vai para Pós-Venda
        wo = WorkOrder.objects.create(
            empresa=self.empresa, lead=self.lead, title="OS",
            priority=WorkOrder.Priority.MEDIUM,
            status=WorkOrder.Status.IN_PROGRESS,
        )
        with self.captureOnCommitCallbacks(execute=True):
            wo.status = WorkOrder.Status.COMPLETED
            wo.save()
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, stage_pos_venda.pk)

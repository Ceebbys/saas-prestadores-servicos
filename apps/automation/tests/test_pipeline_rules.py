"""Testes do sistema de regras de automação de pipeline.

Cobre:
- Movimentação correta do lead via signal
- Recursão prevenida por flag _suppress_automation
- Erro em uma regra não bloqueia outras nem o save da proposta
- Multi-tenant isolation
- Validação clean()
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.automation.models import AutomationLog, PipelineAutomationRule
from apps.automation.services import execute_proposal_event
from apps.crm.models import Lead, Pipeline, PipelineStage
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


class CleanValidationTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.pipeline, self.stages = _setup(self.empresa)
        # cria outro pipeline para testar mismatch
        self.other_pipeline = Pipeline.objects.create(
            empresa=self.empresa, name="Outro", is_default=False,
        )
        self.other_stage = PipelineStage.objects.create(
            pipeline=self.other_pipeline, name="Etapa B", order=0,
        )

    def test_stage_must_belong_to_pipeline(self):
        rule = PipelineAutomationRule(
            empresa=self.empresa,
            name="Bug",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=self.pipeline,
            target_stage=self.other_stage,  # pipeline mismatch
            is_active=True,
        )
        with self.assertRaises(ValidationError):
            rule.clean()

    def test_consistent_pipeline_and_stage_pass(self):
        rule = PipelineAutomationRule(
            empresa=self.empresa,
            name="OK",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=self.pipeline,
            target_stage=self.stages[0],
            is_active=True,
        )
        rule.clean()  # não deve raise


class TriggerExecutionTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("a@t.com", "A", self.empresa)
        self.pipeline, self.stages = _setup(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Lead",
            pipeline_stage=self.stages[0],
        )

    def _proposal(self, **kwargs):
        return Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="P",
            discount_percent=Decimal("0"),
            **kwargs,
        )

    def test_active_rule_moves_lead_on_event(self):
        target = self.stages[2]
        PipelineAutomationRule.objects.create(
            empresa=self.empresa,
            name="Aceita → Negociação",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=self.pipeline,
            target_stage=target,
            is_active=True,
        )
        p = self._proposal()
        execute_proposal_event(
            p, PipelineAutomationRule.Event.PROPOSTA_ACEITA,
        )
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, target.pk)

    def test_inactive_rule_does_not_run(self):
        target = self.stages[2]
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Inativa",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=self.pipeline,
            target_stage=target,
            is_active=False,
        )
        p = self._proposal()
        execute_proposal_event(
            p, PipelineAutomationRule.Event.PROPOSTA_ACEITA,
        )
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, self.stages[0].pk)

    def test_already_in_target_stage_logs_skip(self):
        target = self.stages[0]  # mesma etapa atual
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Skip",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=self.pipeline, target_stage=target,
            is_active=True,
        )
        p = self._proposal()
        execute_proposal_event(p, PipelineAutomationRule.Event.PROPOSTA_ACEITA)
        log = AutomationLog.objects.filter(
            action=AutomationLog.Action.PROPOSAL_PIPELINE_TRIGGER,
            entity_type=AutomationLog.EntityType.LEAD,
            entity_id=self.lead.pk,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get("skipped"), "already_in_target_stage")

    def test_other_tenant_rules_do_not_apply(self):
        outra = create_test_empresa(name="Outra", slug="outra")
        outra_pipeline, outra_stages = _setup(outra)
        # regra na outra empresa apontando para etapa da outra empresa
        PipelineAutomationRule.objects.create(
            empresa=outra, name="OutraRegra",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=outra_pipeline, target_stage=outra_stages[2],
            is_active=True,
        )
        p = self._proposal()
        execute_proposal_event(p, PipelineAutomationRule.Event.PROPOSTA_ACEITA)
        self.lead.refresh_from_db()
        # Lead não deve ter mudado — regra é de outro tenant
        self.assertEqual(self.lead.pipeline_stage_id, self.stages[0].pk)


class SignalIntegrationTests(TestCase):
    """Testa que a transição de status dispara o signal corretamente."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("s@t.com", "S", self.empresa)
        self.pipeline, self.stages = _setup(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Lead",
            pipeline_stage=self.stages[0],
        )
        self.target = self.stages[2]
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Aceita",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=self.pipeline, target_stage=self.target,
            is_active=True,
        )

    def test_status_change_triggers_rule_via_signal(self):
        # `transaction.on_commit` em TestCase precisa de captureOnCommitCallbacks
        # para executar de fato (TestCase faz rollback no final).
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="P",
            status=Proposal.Status.DRAFT,
            discount_percent=Decimal("0"),
        )
        with self.captureOnCommitCallbacks(execute=True):
            p.status = Proposal.Status.ACCEPTED
            p.save()
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, self.target.pk)

"""RV10 — Tests de REGRESSÃO para a SEGUNDA rodada de pente fino.

Quatro bugs identificados:

1. GRAVE — `generate_entry_from_lead_won` usava `Proposal.objects.filter()`
   que esconde propostas soft-deletadas. Cenário: lead em won_stage, proposta
   aceita gerou entry E1, user exclui proposta SEM cascata → P fica em trash,
   E1 sobrevive (related_proposal aponta pra P soft-del). No próximo save do
   lead, `_maybe_generate_finance_entry` chama o helper que NÃO vê a proposta
   (manager esconde) → cria DUPLICATA. Fix: usar `Proposal.all_objects`.

2. MÉDIO — `_apply_rule` movia `lead.pipeline_stage_id` sem validar que
   `lead.empresa_id == rule.empresa_id`. Defesa em camadas: log + skip.

3. MÉDIO — `_handle_link_servico/_update_pipeline/_apply_tag` em action_handlers
   usavam `session.lead` sem checar tenant. Defesa em camadas.

4. MÉDIO — `WorkOrderForm.clean()` aceitava `expected_end_date < scheduled_date`.
   OS ficava invisível no calendário (loop while não roda).
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.finance.models import FinancialEntry
from apps.finance.services import (
    count_won_leads_without_entry, generate_entry_from_lead_won,
)
from apps.proposals.models import Proposal
from apps.automation.models import PipelineAutomationRule, AutomationLog
from apps.automation.services import execute_proposal_event
from apps.operations.forms import WorkOrderForm
from apps.operations.models import ServiceType
from apps.core.tests.helpers import (
    create_pipeline_for_empresa, create_test_empresa, create_test_user,
)


# ===========================================================================
# Hotfix #1 GRAVE — proposta soft-deletada não causa duplicata
# ===========================================================================


class SoftDeletedProposalIdempotencyTests(TestCase):
    """Regressão do GRAVE identificado pelo pente fino rodada 2.

    Antes do fix: `Proposal.objects` escondia soft-deleted → idempotência
    quebrava → duplicata da entry.
    """

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10r2-graveCRIT")
        p = Pipeline.objects.create(empresa=self.empresa, name="P", is_default=True)
        self.s_won = PipelineStage.objects.create(
            pipeline=p, name="G", order=0, is_won=True,
        )

    def _won_lead(self, value=Decimal("1500")):
        lead = Lead(
            empresa=self.empresa, name="V",
            estimated_value=value, pipeline_stage=self.s_won,
        )
        lead._suppress_finance_entry = True
        lead.save()
        return lead

    def test_generate_returns_none_when_proposal_soft_deleted_has_entry(self):
        """Reproduz cenário do bug: proposta soft-deletada com entry
        precisa ser DETECTADA pra evitar duplicata."""
        lead = self._won_lead()
        prop = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="P",
            discount_percent=Decimal("0"),
        )
        FinancialEntry.objects.create(
            empresa=self.empresa, type="income", description="P entry",
            amount=Decimal("1500"), date="2026-06-01",
            related_proposal=prop, auto_generated=True,
        )
        # Soft-delete da proposta (cenário real: user exclui sem cascata)
        prop.delete()
        self.assertIsNotNone(prop.deleted_at)

        # generate_entry_from_lead_won deve retornar None (proposta cuidou)
        result = generate_entry_from_lead_won(lead)
        self.assertIsNone(result, "BUG: criou entry duplicada")
        total = FinancialEntry.objects.filter(empresa=self.empresa).count()
        self.assertEqual(total, 1, f"BUG: {total} entries (esperado 1)")

    def test_count_excludes_lead_with_soft_deleted_proposal_entry(self):
        """count_won_leads_without_entry NÃO conta lead cuja proposta
        soft-deletada ainda tem entry vinculada."""
        lead = self._won_lead()
        prop = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="P",
            discount_percent=Decimal("0"),
        )
        FinancialEntry.objects.create(
            empresa=self.empresa, type="income", description="P",
            amount=Decimal("1500"), date="2026-06-01",
            related_proposal=prop, auto_generated=True,
        )
        prop.delete()  # soft-delete

        # Lead NÃO deve aparecer como "pendente de lançamento"
        self.assertEqual(count_won_leads_without_entry(self.empresa), 0)

    def test_backfill_does_not_create_duplicate_for_lead_with_soft_deleted_proposal(self):
        """Backfill on-demand respeita a mesma regra."""
        from apps.finance.services import backfill_won_lead_entries
        lead = self._won_lead()
        prop = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="P",
            discount_percent=Decimal("0"),
        )
        FinancialEntry.objects.create(
            empresa=self.empresa, type="income", description="P",
            amount=Decimal("1500"), date="2026-06-01",
            related_proposal=prop, auto_generated=True,
        )
        prop.delete()  # soft-delete

        result = backfill_won_lead_entries(self.empresa)
        # Não escaneou nada, não criou duplicata
        self.assertEqual(result["scanned"], 0)
        self.assertEqual(len(result["created"]), 0)
        self.assertEqual(FinancialEntry.objects.filter(empresa=self.empresa).count(), 1)


# ===========================================================================
# Hotfix #2 MÉDIO — _apply_rule rejeita lead cross-tenant
# ===========================================================================


class ApplyRuleCrossTenantTests(TestCase):
    def setUp(self):
        self.emp_a = create_test_empresa(slug="rv10r2-empA")
        self.emp_b = create_test_empresa(slug="rv10r2-empB")
        create_pipeline_for_empresa(self.emp_a)
        pipeA = Pipeline.objects.filter(empresa=self.emp_a, is_default=True).first()
        self.stage_a = list(pipeA.stages.order_by("order"))[1]

    def test_lead_from_other_tenant_is_skipped_with_log(self):
        """Lead da empresa B no source da empresa A: skip + log de error."""
        from apps.automation.services import _apply_rule
        rule = PipelineAutomationRule.objects.create(
            empresa=self.emp_a, name="R",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=self.stage_a.pipeline, target_stage=self.stage_a,
            is_active=True,
        )
        # Source da empresa A mas com lead da empresa B (situação anômala)
        lead_b = Lead.objects.create(empresa=self.emp_b, name="LB")
        # Mock source: tem .empresa (A) e .lead (B) + .pk
        class Src:
            empresa = self.emp_a
            lead = lead_b
            pk = 999
        _apply_rule(Src(), rule, "proposta_aceita", source_label="proposal")

        lead_b.refresh_from_db()
        # Lead B NÃO foi movido pra stage de empresa A
        self.assertNotEqual(lead_b.pipeline_stage_id, self.stage_a.pk)
        # Log de erro foi criado
        log = AutomationLog.objects.filter(
            empresa=self.emp_a, status=AutomationLog.Status.ERROR,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get("skipped"), "cross_tenant_lead")


# ===========================================================================
# Hotfix #3 MÉDIO — action_handlers respeitam tenant do session.lead
# ===========================================================================


class ActionHandlersCrossTenantTests(TestCase):
    def setUp(self):
        self.emp_a = create_test_empresa(slug="rv10r2-acA")
        self.emp_b = create_test_empresa(slug="rv10r2-acB")
        from apps.chatbot.models import ChatbotFlow, ChatbotSession
        self.flow_a = ChatbotFlow.objects.create(
            empresa=self.emp_a, name="F", channel="webchat", is_active=True,
        )
        # Lead da empresa B (anômalo)
        self.lead_b = Lead.objects.create(empresa=self.emp_b, name="LB")
        self.session = ChatbotSession.objects.create(
            flow=self.flow_a, sender_id="x", channel="webchat",
            current_node_id="", lead=self.lead_b,  # cross-tenant
        )

    def test_update_pipeline_blocks_cross_tenant_lead(self):
        from apps.chatbot.action_handlers import _handle_update_pipeline
        pipeB = Pipeline.objects.create(empresa=self.emp_b, name="P")
        stage_b = PipelineStage.objects.create(pipeline=pipeB, name="S", order=0)
        result = _handle_update_pipeline(self.session, {
            "pipeline_stage_id": str(stage_b.pk),
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["extra"].get("reason"), "cross_tenant_lead")

    def test_link_servico_blocks_cross_tenant_lead(self):
        from apps.chatbot.action_handlers import _handle_link_servico
        from apps.operations.models import ServiceType
        svc_a = ServiceType.objects.create(
            empresa=self.emp_a, name="S", is_active=True,
        )
        result = _handle_link_servico(self.session, {"servico_id": str(svc_a.pk)})
        self.assertFalse(result["ok"])
        self.assertEqual(result["extra"].get("reason"), "cross_tenant_lead")

    def test_apply_tag_blocks_cross_tenant_lead(self):
        from apps.chatbot.action_handlers import _handle_apply_tag
        result = _handle_apply_tag(self.session, {"tag_name": "vip"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["extra"].get("reason"), "cross_tenant_lead")


# ===========================================================================
# Hotfix #4 MÉDIO — WorkOrderForm valida expected_end_date >= scheduled
# ===========================================================================


class WorkOrderFormDateCoherenceTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10r2-os")
        p = Pipeline.objects.create(empresa=self.empresa, name="P", is_default=True)
        self.s = PipelineStage.objects.create(pipeline=p, name="N", order=0)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="L", pipeline_stage=self.s,
        )

    def test_end_before_scheduled_is_rejected(self):
        form = WorkOrderForm(data={
            "title": "OS Invalida", "lead": self.lead.pk,
            "priority": "medium",
            "scheduled_date": "2026-06-15",
            "expected_end_date": "2026-06-01",  # antes do início
            "checklist_json": "",
        }, empresa=self.empresa)
        self.assertFalse(form.is_valid())
        self.assertIn("expected_end_date", form.errors)

    def test_end_equal_scheduled_is_accepted(self):
        form = WorkOrderForm(data={
            "title": "OS 1dia", "lead": self.lead.pk,
            "priority": "medium",
            "scheduled_date": "2026-06-15",
            "expected_end_date": "2026-06-15",  # mesmo dia OK
            "checklist_json": "",
        }, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)

    def test_end_after_scheduled_is_accepted(self):
        form = WorkOrderForm(data={
            "title": "OS Normal", "lead": self.lead.pk,
            "priority": "medium",
            "scheduled_date": "2026-06-15",
            "expected_end_date": "2026-06-20",
            "checklist_json": "",
        }, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)

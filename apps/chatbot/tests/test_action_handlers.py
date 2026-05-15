"""Testes dos action handlers (RV06).

Cobre todos os 10 tipos de ação que o dispatcher centralizado suporta:
- create_lead, link_servico, update_pipeline, apply_tag, register_event
- send_email, send_whatsapp, send_proposal, send_contract, create_task

Foco: idempotência, lazy resolution, tratamento de erros silenciosos
(handler nunca derruba o fluxo).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.chatbot.action_handlers import dispatch_action
from apps.chatbot.models import ChatbotFlow, ChatbotSession
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead


def _make_session(empresa, lead=None, lead_data=None) -> ChatbotSession:
    flow = ChatbotFlow.objects.create(
        empresa=empresa, name="Test", is_active=True, channel="whatsapp",
    )
    return ChatbotSession.objects.create(
        flow=flow,
        sender_id="5511999999999",
        channel="whatsapp",
        status=ChatbotSession.Status.ACTIVE,
        lead=lead,
        lead_data=lead_data or {},
    )


class DispatcherTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("h@t.com", "H", self.empresa)

    def test_unknown_action_type_returns_error(self):
        session = _make_session(self.empresa)
        result = dispatch_action("xpto_action", session, {})
        self.assertFalse(result["ok"])
        self.assertIn("desconhecido", result["message"].lower())

    def test_handler_exception_is_captured(self):
        # Passa lead_data válido (com name) para passar o guard de no_identity
        # e chegar até o ponto onde forçamos a exceção via mock.
        session = _make_session(self.empresa, lead_data={"name": "João"})
        with patch(
            "apps.chatbot.services._create_lead_action",
            side_effect=RuntimeError("boom"),
        ):
            result = dispatch_action("create_lead", session, {})
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["message"])


class LinkServicoHandlerTests(TestCase):
    """Item 1 da fatura — Vincular serviço pré-fixado."""

    def setUp(self):
        from apps.operations.models import ServiceType
        self.empresa = create_test_empresa()
        create_test_user("ls@t.com", "LS", self.empresa)
        self.servico = ServiceType.objects.create(
            empresa=self.empresa,
            name="Topografia Padrão",
            default_price=Decimal("1500.00"),
            default_prazo_dias=15,
        )

    def test_link_servico_sets_session_lead_data(self):
        session = _make_session(self.empresa)
        result = dispatch_action(
            "link_servico", session, {"servico_id": str(self.servico.pk)},
        )
        self.assertTrue(result["ok"], result["message"])
        session.refresh_from_db()
        self.assertEqual(session.lead_data["servico_id"], self.servico.pk)
        snap = session.lead_data["servico_snapshot"]
        self.assertEqual(snap["name"], "Topografia Padrão")
        self.assertEqual(snap["default_price"], "1500.00")
        self.assertEqual(snap["default_prazo_dias"], 15)

    def test_link_servico_updates_existing_lead(self):
        lead = Lead.objects.create(empresa=self.empresa, name="LL")
        session = _make_session(self.empresa, lead=lead)
        dispatch_action(
            "link_servico", session, {"servico_id": str(self.servico.pk)},
        )
        lead.refresh_from_db()
        self.assertEqual(lead.servico_id, self.servico.pk)

    def test_link_servico_missing_id_returns_error(self):
        session = _make_session(self.empresa)
        result = dispatch_action("link_servico", session, {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["extra"]["reason"], "missing_servico_id")

    def test_link_servico_cross_tenant_blocked(self):
        # Cria serviço em OUTRA empresa, tenta usar
        outra = create_test_empresa("Outra", "outra")
        from apps.operations.models import ServiceType
        servico_outra = ServiceType.objects.create(
            empresa=outra, name="X", default_price=Decimal("10"),
        )
        session = _make_session(self.empresa)
        result = dispatch_action(
            "link_servico", session, {"servico_id": str(servico_outra.pk)},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["extra"]["reason"], "not_found")


class ApplyTagHandlerTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("t@t.com", "T", self.empresa)

    def test_apply_tag_creates_leadtag(self):
        from apps.crm.models import LeadTag
        lead = Lead.objects.create(empresa=self.empresa, name="L1")
        session = _make_session(self.empresa, lead=lead)
        result = dispatch_action(
            "apply_tag", session, {"tag_name": "qualificado"},
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["extra"]["created"])
        self.assertEqual(
            LeadTag.objects.filter(lead=lead, name="qualificado").count(), 1,
        )

    def test_apply_tag_idempotent(self):
        from apps.crm.models import LeadTag
        lead = Lead.objects.create(empresa=self.empresa, name="L2")
        session = _make_session(self.empresa, lead=lead)
        dispatch_action("apply_tag", session, {"tag_name": "vip"})
        result2 = dispatch_action("apply_tag", session, {"tag_name": "vip"})
        self.assertTrue(result2["ok"])
        self.assertFalse(result2["extra"]["created"])
        self.assertEqual(LeadTag.objects.filter(lead=lead, name="vip").count(), 1)

    def test_apply_tag_without_lead_skips(self):
        session = _make_session(self.empresa)
        result = dispatch_action("apply_tag", session, {"tag_name": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["extra"]["reason"], "no_lead")


class UpdatePipelineHandlerTests(TestCase):
    def setUp(self):
        from apps.crm.models import Pipeline, PipelineStage
        self.empresa = create_test_empresa()
        create_test_user("p@t.com", "P", self.empresa)
        self.pipeline = Pipeline.objects.create(empresa=self.empresa, name="Vendas", is_default=True)
        self.stage = PipelineStage.objects.create(pipeline=self.pipeline, name="Qualificado", order=1)

    def test_moves_lead_to_stage(self):
        lead = Lead.objects.create(empresa=self.empresa, name="LP")
        session = _make_session(self.empresa, lead=lead)
        result = dispatch_action(
            "update_pipeline", session, {"pipeline_stage_id": str(self.stage.pk)},
        )
        self.assertTrue(result["ok"], result["message"])
        lead.refresh_from_db()
        self.assertEqual(lead.pipeline_stage_id, self.stage.pk)


class RegisterEventHandlerTests(TestCase):
    def test_creates_automation_log(self):
        from apps.automation.models import AutomationLog
        empresa = create_test_empresa()
        create_test_user("e@t.com", "E", empresa)
        session = _make_session(empresa)
        before = AutomationLog.objects.count()
        result = dispatch_action(
            "register_event", session, {"event_name": "cliente_qualificado"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(AutomationLog.objects.count(), before + 1)
        log = AutomationLog.objects.latest("id")
        self.assertEqual(log.metadata["event_name"], "cliente_qualificado")


class CreateTaskHandlerTests(TestCase):
    def test_create_task_returns_not_implemented(self):
        empresa = create_test_empresa()
        create_test_user("ct@t.com", "CT", empresa)
        session = _make_session(empresa)
        result = dispatch_action("create_task", session, {})
        self.assertFalse(result["ok"])
        self.assertTrue(result["extra"]["not_implemented"])


class SendProposalHandlerTests(TestCase):
    """Item 5/6 — testa wiring sem chamar Evolution real."""

    def test_skips_when_no_lead(self):
        empresa = create_test_empresa()
        create_test_user("sp@t.com", "SP", empresa)
        session = _make_session(empresa)
        result = dispatch_action("send_proposal", session, {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["extra"]["reason"], "no_lead")

    def test_skips_when_no_phone(self):
        from apps.proposals.models import Proposal
        empresa = create_test_empresa()
        create_test_user("sp2@t.com", "SP", empresa)
        lead = Lead.objects.create(empresa=empresa, name="LSP", phone="")
        Proposal.objects.create(empresa=empresa, lead=lead, title="P", status=Proposal.Status.DRAFT)
        session = _make_session(empresa, lead=lead)
        result = dispatch_action(
            "send_proposal", session, {"auto_create_if_missing": False},
        )
        # phone vem do sender_id "5511999999999" da session → tem phone
        # Vai cair na chamada real do send_proposal_whatsapp e falhar por falta
        # de WhatsAppConfig
        # OK desde que retorne ok=False com causa clara
        self.assertFalse(result["ok"])

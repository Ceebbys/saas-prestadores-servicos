"""RV08 (5.2) — "Consultas ao Sistema": ação query_status responde ao cliente."""
from __future__ import annotations

from django.test import TestCase

from apps.chatbot.action_handlers import dispatch_action
from apps.chatbot.builder.schemas import load_node_catalog
from apps.chatbot.builder.services.flow_executor import _emit_action_reply
from apps.chatbot.models import ChatbotFlow, ChatbotMessage, ChatbotSession
from apps.contracts.models import Contract
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead
from apps.operations.models import WorkOrder
from apps.proposals.models import Proposal


def _make_session(empresa, lead=None):
    flow = ChatbotFlow.objects.create(
        empresa=empresa, name="T", is_active=True, channel="whatsapp",
    )
    return ChatbotSession.objects.create(
        flow=flow, sender_id="5511999999999", channel="whatsapp",
        status=ChatbotSession.Status.ACTIVE, lead=lead,
    )


class QueryStatusRV08Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-q")
        create_test_user("q@t.com", "Q", self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="Cliente Q")

    def test_registered_in_catalog(self):
        catalog = load_node_catalog()
        action_node = next(n for n in catalog["nodes"] if n["type"] == "action")
        action_type_field = next(
            f for f in action_node["data_fields"] if f["name"] == "action_type"
        )
        self.assertIn("query_status", action_type_field["options"])
        self.assertIn("query_status", action_node["data_fields_per_action_type"])

    def test_service_progress(self):
        WorkOrder.objects.create(
            empresa=self.empresa, lead=self.lead, title="OS Q",
            status=WorkOrder.Status.IN_PROGRESS,
        )
        session = _make_session(self.empresa, self.lead)
        result = dispatch_action(
            "query_status", session, {"query_type": "service_progress"},
        )
        self.assertTrue(result["ok"])
        self.assertIn("Em Andamento", result["extra"]["reply_text"])

    def test_proposal_status(self):
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="P Q",
            status=Proposal.Status.SENT,
        )
        session = _make_session(self.empresa, self.lead)
        result = dispatch_action(
            "query_status", session, {"query_type": "proposal_status"},
        )
        self.assertTrue(result["ok"])
        self.assertIn("Enviada", result["extra"]["reply_text"])

    def test_contract_status(self):
        Contract.objects.create(
            empresa=self.empresa, lead=self.lead, title="C Q",
            status=Contract.Status.SIGNED,
        )
        session = _make_session(self.empresa, self.lead)
        result = dispatch_action(
            "query_status", session, {"query_type": "contract_status"},
        )
        self.assertTrue(result["ok"])
        self.assertIn("Assinado", result["extra"]["reply_text"])

    def test_no_lead_asks_to_identify(self):
        session = _make_session(self.empresa, lead=None)
        result = dispatch_action(
            "query_status", session, {"query_type": "service_progress"},
        )
        self.assertFalse(result["ok"])
        self.assertIn("identificar", result["extra"]["reply_text"].lower())

    def test_engine_emits_reply_as_bot_message(self):
        session = _make_session(self.empresa, self.lead)
        _emit_action_reply(
            {"id": "n1"}, session,
            {"ok": True, "extra": {"reply_text": "Seu serviço está em andamento."}},
        )
        msg = ChatbotMessage.objects.filter(
            session=session, direction=ChatbotMessage.Direction.OUTBOUND,
        ).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.content, "Seu serviço está em andamento.")

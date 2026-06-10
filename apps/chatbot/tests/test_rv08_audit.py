"""RV08 — Regressões do pente fino (chatbot).

- C1: a resposta da ação query_status REALMENTE chega ao cliente (vai no
  `message` retornado pelo motor, não só no banco).
- Simulador trata nó `action` (antes dava unknown_node_type:action).
- send_proposal não reutiliza proposta aceita/rejeitada.
"""
from django.test import TestCase
from django.utils import timezone

from apps.chatbot.action_handlers import dispatch_action
from apps.chatbot.builder.services.flow_executor import (
    process_response_v2,
    start_session_v2,
)
from apps.chatbot.builder.services.simulator import start_simulation
from apps.chatbot.models import ChatbotFlow, ChatbotFlowVersion, ChatbotSession
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead
from apps.operations.models import WorkOrder
from apps.proposals.models import Proposal


def _node(nid, ntype, **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": data}


def _edge(eid, source, target, sourceHandle="next"):
    return {"id": eid, "source": source, "target": target,
            "sourceHandle": sourceHandle, "targetHandle": "in"}


def _publish(flow, graph):
    version = ChatbotFlowVersion.objects.create(
        flow=flow, graph_json=graph,
        status=ChatbotFlowVersion.Status.PUBLISHED, published_at=timezone.now(),
    )
    flow.use_visual_builder = True
    flow.current_published_version = version
    flow.save(update_fields=["use_visual_builder", "current_published_version"])
    return version


def _graph_with_query():
    return {
        "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
        "nodes": [
            _node("n_start", "start"),
            _node("n_q", "question", prompt="Pode confirmar?"),
            _node("n_act", "action", action_type="query_status",
                  query_type="service_progress"),
            _node("n_end", "end", completion_message="Mais alguma coisa?"),
        ],
        "edges": [
            _edge("e1", "n_start", "n_q"),
            _edge("e2", "n_q", "n_act"),
            _edge("e3", "n_act", "n_end"),
        ],
    }


class QueryReplyDeliveryTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-aud-cb")
        create_test_user("a@t.com", "A", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Q", channel="webchat", is_active=True,
        )

    def test_query_reply_reaches_returned_message(self):
        """C1 — sem o acumulador, a resposta ficava só no banco."""
        lead = Lead.objects.create(empresa=self.empresa, name="Cliente")
        WorkOrder.objects.create(
            empresa=self.empresa, lead=lead, title="OS",
            status=WorkOrder.Status.IN_PROGRESS,
        )
        _publish(self.flow, _graph_with_query())
        start = start_session_v2(self.flow)
        sk = start["session_key"]
        session = ChatbotSession.objects.get(session_key=sk)
        session.lead = lead
        session.save(update_fields=["lead"])

        result = process_response_v2(sk, "sim")
        # A resposta da consulta DEVE estar no message entregue ao canal.
        self.assertIn("Em Andamento", result["message"])

    def test_simulator_handles_action_node(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("n_start", "start"),
                _node("n_act", "action", action_type="query_status",
                      query_type="proposal_status"),
                _node("n_end", "end", completion_message="Fim"),
            ],
            "edges": [_edge("e1", "n_start", "n_act"), _edge("e2", "n_act", "n_end")],
        }
        result = start_simulation(self.flow, graph)
        # Não pode terminar com unknown_node_type:action
        self.assertNotIn("unknown_node_type", str(result.get("completion_reason", "")))
        contents = " ".join(m.get("content", "") for m in result.get("messages", []))
        self.assertIn("seria executada", contents)


class SendProposalReuseTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-aud-sp")
        create_test_user("b@t.com", "B", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="whatsapp", is_active=True,
        )
        self.lead = Lead.objects.create(empresa=self.empresa, name="Lead SP")
        self.session = ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511999999999", channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE, lead=self.lead,
        )

    def test_rejected_proposal_is_not_recycled(self):
        Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="Antiga",
            status=Proposal.Status.REJECTED,
        )
        # Sem WhatsApp configurado o envio falha, mas uma NOVA proposta DRAFT
        # deve ser criada (a rejeitada não pode ser reaproveitada).
        dispatch_action("send_proposal", self.session, {"auto_create_if_missing": True})
        self.assertEqual(Proposal.objects.filter(lead=self.lead).count(), 2)
        self.assertTrue(
            Proposal.objects.filter(
                lead=self.lead, status=Proposal.Status.DRAFT,
            ).exists()
        )

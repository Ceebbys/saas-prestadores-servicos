"""Testes do bloco `action` no construtor visual.

Cobre:
- Validator: action_type é required (enum) — bloco sem action_type falha
- Validator: action_type fora da lista falha
- Executor: action node tipo create_lead chama _create_lead_action e vincula
  session.lead
- Executor: action inativa (is_active=False) é pulada
- Executor: action_type placeholder (send_email, etc.) loga warning mas
  continua o fluxo (não derruba)
- Executor: erro na execução é capturado, fluxo continua
- Catálogo: action está no node_catalog com status=active
"""
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.chatbot.builder.schemas import get_node_type
from apps.chatbot.builder.services.flow_executor import start_session_v2
from apps.chatbot.builder.services.flow_validator import validate_graph
from apps.chatbot.models import (
    ChatbotExecutionLog,
    ChatbotFlow,
    ChatbotFlowVersion,
    ChatbotSession,
)
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _node(nid, ntype, **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": data}


def _edge(eid, src, tgt, sh="next"):
    return {"id": eid, "source": src, "target": tgt, "sourceHandle": sh, "targetHandle": "in"}


def _graph(nodes, edges):
    return {
        "schema_version": 1,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "metadata": {},
        "nodes": nodes,
        "edges": edges,
    }


def _publish(flow, graph):
    v = ChatbotFlowVersion.objects.create(
        flow=flow, graph_json=graph,
        status=ChatbotFlowVersion.Status.PUBLISHED,
        published_at=timezone.now(),
    )
    flow.use_visual_builder = True
    flow.current_published_version = v
    flow.save()
    return v


class ActionNodeCatalogTests(TestCase):
    def test_action_is_in_catalog(self):
        entry = get_node_type("action")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["status"], "active")

    def test_action_has_required_fields(self):
        entry = get_node_type("action")
        names = [f["name"] for f in entry["data_fields"]]
        self.assertIn("action_type", names)
        self.assertIn("order", names)
        self.assertIn("is_active", names)

    def test_action_type_enum_includes_all_types(self):
        """RV06 — 10 tipos: 8 originais + send_proposal + send_contract."""
        entry = get_node_type("action")
        action_type_field = next(f for f in entry["data_fields"] if f["name"] == "action_type")
        # Os 8 originais
        for t in ("create_lead", "update_pipeline", "apply_tag", "link_servico",
                  "register_event", "send_email", "send_whatsapp", "create_task"):
            self.assertIn(t, action_type_field["options"])
        # RV06: 2 novos
        self.assertIn("send_proposal", action_type_field["options"])
        self.assertIn("send_contract", action_type_field["options"])
        self.assertEqual(len(action_type_field["options"]), 10)

    def test_data_fields_per_action_type_exists(self):
        """RV06 — catálogo declara campos extras condicionais por action_type."""
        entry = get_node_type("action")
        per_type = entry.get("data_fields_per_action_type")
        self.assertIsNotNone(per_type, "data_fields_per_action_type deve existir no catálogo")
        # link_servico precisa de servico_id (item 1 da fatura)
        link_fields = per_type.get("link_servico", [])
        names = [f["name"] for f in link_fields]
        self.assertIn("servico_id", names)
        # send_proposal precisa de proposal_template_id
        self.assertIn("proposal_template_id", [f["name"] for f in per_type.get("send_proposal", [])])
        # send_contract precisa de contract_template_id
        self.assertIn("contract_template_id", [f["name"] for f in per_type.get("send_contract", [])])


class ActionNodeValidatorTests(TestCase):
    def test_action_without_action_type_fails(self):
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "action"),  # sem action_type
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "a1"),
            _edge("e2", "a1", "e1"),
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("REQUIRED_FIELD_EMPTY", codes)

    def test_action_with_valid_action_type_passes(self):
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "action", action_type="create_lead"),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "a1"),
            _edge("e2", "a1", "e1"),
        ])
        result = validate_graph(graph)
        self.assertTrue(result["valid"], result["errors"])

    def test_action_with_invalid_action_type_fails(self):
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "action", action_type="alien_action"),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "a1"),
            _edge("e2", "a1", "e1"),
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("INVALID_ENUM_VALUE", codes)


class ActionNodeExecutorTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("a@t.com", "A", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="A", channel="webchat", is_active=True,
        )

    def test_create_lead_action_creates_lead(self):
        from apps.crm.models import Lead, Pipeline, PipelineStage
        # Pipeline default necessário para create_lead_from_chatbot
        Pipeline.objects.create(empresa=self.empresa, name="P", is_default=True)
        pipeline = Pipeline.objects.first()
        PipelineStage.objects.create(pipeline=pipeline, name="Novo", order=0)

        graph = _graph([
            _node("s1", "start"),
            _node("q1", "question", prompt="Nome?", lead_field="name"),
            _node("a1", "action", action_type="create_lead"),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "q1"),
            _edge("e2", "q1", "a1"),
            _edge("e3", "a1", "e1"),
        ])
        _publish(self.flow, graph)

        from apps.chatbot.builder.services.flow_executor import process_response_v2
        before = Lead.objects.count()
        result = start_session_v2(self.flow)
        sk = result["session_key"]
        result2 = process_response_v2(sk, "João")
        self.assertTrue(result2["is_complete"])
        # Lead criado pelo action node
        self.assertEqual(Lead.objects.count(), before + 1)

        # Session.lead vinculado
        session = ChatbotSession.objects.get(session_key=sk)
        self.assertIsNotNone(session.lead_id)

        # Log de action_executed
        logs = ChatbotExecutionLog.objects.filter(
            session=session, event="action_executed",
        )
        self.assertGreater(logs.count(), 0)

    def test_inactive_action_is_skipped(self):
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "action", action_type="create_lead", is_active=False),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "a1"),
            _edge("e2", "a1", "e1"),
        ])
        _publish(self.flow, graph)
        result = start_session_v2(self.flow)
        self.assertTrue(result["is_complete"])
        # Log do skip
        session = ChatbotSession.objects.filter(flow=self.flow).first()
        logs = ChatbotExecutionLog.objects.filter(
            session=session, event="action_executed",
        )
        # Tem ao menos 1 log com skipped_inactive=True
        skipped = [l for l in logs if l.payload.get("skipped_inactive")]
        self.assertGreater(len(skipped), 0)

    def test_placeholder_action_logs_warning_and_continues(self):
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "action", action_type="send_email"),
            _node("e1", "end", completion_message="Pronto"),
        ], [
            _edge("e1", "s1", "a1"),
            _edge("e2", "a1", "e1"),
        ])
        _publish(self.flow, graph)
        result = start_session_v2(self.flow)
        self.assertTrue(result["is_complete"])
        self.assertIn("Pronto", result.get("message", ""))
        # Log warning de not_implemented
        session = ChatbotSession.objects.filter(flow=self.flow).first()
        warning_logs = ChatbotExecutionLog.objects.filter(
            session=session, level="warning",
        )
        self.assertGreater(warning_logs.count(), 0)

    def test_action_error_does_not_break_flow(self):
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "action", action_type="create_lead"),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "a1"),
            _edge("e2", "a1", "e1"),
        ])
        _publish(self.flow, graph)
        # Mock para forçar exceção dentro do action handler
        with patch(
            "apps.chatbot.services._create_lead_action",
            side_effect=RuntimeError("boom"),
        ):
            result = start_session_v2(self.flow)
        # Fluxo continua até o end mesmo com action falhando
        self.assertTrue(result["is_complete"])

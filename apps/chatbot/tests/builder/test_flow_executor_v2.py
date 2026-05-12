"""RV06 — Testes do flow_executor v2 (interpretador graph_json).

Cobre:
- start_session_v2 cria sessão e envia welcome
- message node avança e envia texto
- question node aguarda input, valida, grava em lead_data
- menu node resolve handle por número/label
- condition node avalia operadores
- collect_data valida email/phone/cpf
- handoff e end encerram sessão
- ChatbotMessage e ChatbotExecutionLog são populados
- Despachador chama v2 quando flow.use_visual_builder + published version
"""
from django.test import TestCase
from django.utils import timezone

from apps.chatbot.builder.services.flow_executor import (
    process_response_v2,
    start_session_v2,
)
from apps.chatbot.models import (
    ChatbotExecutionLog,
    ChatbotFlow,
    ChatbotFlowVersion,
    ChatbotMessage,
    ChatbotSession,
)
from apps.chatbot.services import process_response, start_session
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _node(nid, ntype, **data):
    return {
        "id": nid,
        "type": ntype,
        "position": {"x": 0, "y": 0},
        "data": data,
    }


def _edge(eid, source, target, sourceHandle="next"):
    return {
        "id": eid,
        "source": source,
        "target": target,
        "sourceHandle": sourceHandle,
        "targetHandle": "in",
    }


def _publish(flow: ChatbotFlow, graph: dict) -> ChatbotFlowVersion:
    """Helper: cria FlowVersion published + marca use_visual_builder."""
    version = ChatbotFlowVersion.objects.create(
        flow=flow,
        graph_json=graph,
        status=ChatbotFlowVersion.Status.PUBLISHED,
        published_at=timezone.now(),
    )
    flow.use_visual_builder = True
    flow.current_published_version = version
    flow.save(update_fields=["use_visual_builder", "current_published_version"])
    return version


class StartSessionV2Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("e@t.com", "E", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="V2", channel="webchat",
            welcome_message="Olá!",
            is_active=True,
        )

    def test_start_session_with_no_published_version_fails(self):
        with self.assertRaises(ValueError):
            start_session_v2(self.flow)

    def test_start_session_advances_past_start_to_first_question(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("q1", "question", prompt="Qual seu nome?", lead_field="name"),
                _node("e1", "end"),
            ],
            "edges": [
                _edge("e_s", "s1", "q1"),
                _edge("e_e", "q1", "e1"),
            ],
        }
        _publish(self.flow, graph)
        result = start_session_v2(self.flow)
        self.assertFalse(result.get("is_complete"))
        self.assertEqual(result["step"]["id"], "q1")
        self.assertEqual(result["step"]["type"], "question")

    def test_start_session_creates_session_started_log(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("q1", "question", prompt="?"),
                _node("e1", "end"),
            ],
            "edges": [
                _edge("a", "s1", "q1"),
                _edge("b", "q1", "e1"),
            ],
        }
        _publish(self.flow, graph)
        start_session_v2(self.flow)
        log = ChatbotExecutionLog.objects.filter(event="session_started").first()
        self.assertIsNotNone(log)


class ProcessResponseV2Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("e@t.com", "E", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="V2 Run", channel="webchat",
            send_completion_message=True,
            completion_message="Tchau!",
            is_active=True,
        )

    def test_question_then_end_full_flow(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("q1", "question", prompt="Nome?", lead_field="name"),
                _node("e1", "end"),
            ],
            "edges": [
                _edge("a", "s1", "q1"),
                _edge("b", "q1", "e1"),
            ],
        }
        _publish(self.flow, graph)
        result = start_session_v2(self.flow)
        sk = result["session_key"]
        result2 = process_response_v2(sk, "João")
        self.assertTrue(result2["is_complete"])
        session = ChatbotSession.objects.get(session_key=sk)
        self.assertEqual(session.status, ChatbotSession.Status.COMPLETED)
        self.assertEqual(session.lead_data["name"], "João")

    def test_menu_resolves_by_number(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("m1", "menu", prompt="Escolha:", options=[
                    {"label": "Sim", "handle_id": "y"},
                    {"label": "Não", "handle_id": "n"},
                ]),
                _node("e_y", "end", completion_message="Sim recebido"),
                _node("e_n", "end", completion_message="Não recebido"),
            ],
            "edges": [
                _edge("a", "s1", "m1"),
                _edge("b", "m1", "e_y", sourceHandle="y"),
                _edge("c", "m1", "e_n", sourceHandle="n"),
            ],
        }
        _publish(self.flow, graph)
        sk = start_session_v2(self.flow)["session_key"]
        # Resposta "1" → handle 'y' → e_y
        result = process_response_v2(sk, "1")
        self.assertTrue(result["is_complete"])
        self.assertIn("Sim recebido", result["message"])

    def test_menu_resolves_by_label(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("m1", "menu", prompt="?", options=[
                    {"label": "Suporte", "handle_id": "sup"},
                    {"label": "Comercial", "handle_id": "com"},
                ]),
                _node("e1", "end"),
                _node("e2", "end"),
            ],
            "edges": [
                _edge("a", "s1", "m1"),
                _edge("b", "m1", "e1", sourceHandle="sup"),
                _edge("c", "m1", "e2", sourceHandle="com"),
            ],
        }
        _publish(self.flow, graph)
        sk = start_session_v2(self.flow)["session_key"]
        result = process_response_v2(sk, "suporte")
        self.assertTrue(result["is_complete"])

    def test_menu_invalid_response_repeats_prompt(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("m1", "menu", prompt="Escolha:", options=[
                    {"label": "A", "handle_id": "a"},
                    {"label": "B", "handle_id": "b"},
                ]),
                _node("e1", "end"),
            ],
            "edges": [
                _edge("a", "s1", "m1"),
                _edge("b", "m1", "e1", sourceHandle="a"),
                _edge("c", "m1", "e1", sourceHandle="b"),
            ],
        }
        _publish(self.flow, graph)
        sk = start_session_v2(self.flow)["session_key"]
        result = process_response_v2(sk, "xyz desconhecido")
        self.assertFalse(result["is_complete"])
        self.assertIn("Não entendi", result["message"])

    def test_condition_branches_correctly(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("q1", "question", prompt="Nome?", lead_field="name"),
                _node("c1", "condition", field="name", operator="eq", value="admin"),
                _node("e_t", "end", completion_message="Admin"),
                _node("e_f", "end", completion_message="User"),
            ],
            "edges": [
                _edge("a", "s1", "q1"),
                _edge("b", "q1", "c1"),
                _edge("c", "c1", "e_t", sourceHandle="true"),
                _edge("d", "c1", "e_f", sourceHandle="false"),
            ],
        }
        _publish(self.flow, graph)
        sk = start_session_v2(self.flow)["session_key"]
        result = process_response_v2(sk, "admin")
        self.assertTrue(result["is_complete"])
        self.assertIn("Admin", result["message"])

    def test_collect_data_email_validates(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("c1", "collect_data", prompt="Email?", lead_field="email"),
                _node("e1", "end"),
            ],
            "edges": [
                _edge("a", "s1", "c1"),
                _edge("b", "c1", "e1"),
            ],
        }
        _publish(self.flow, graph)
        sk = start_session_v2(self.flow)["session_key"]
        # Email inválido
        result = process_response_v2(sk, "not-an-email")
        self.assertFalse(result["is_complete"])
        # Email válido
        result = process_response_v2(sk, "user@example.com")
        self.assertTrue(result["is_complete"])
        session = ChatbotSession.objects.get(session_key=sk)
        self.assertEqual(session.lead_data["email"], "user@example.com")

    def test_message_node_auto_advances(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("m1", "message", text="Aguarde…"),
                _node("q1", "question", prompt="Nome?"),
                _node("e1", "end"),
            ],
            "edges": [
                _edge("a", "s1", "m1"),
                _edge("b", "m1", "q1"),
                _edge("c", "q1", "e1"),
            ],
        }
        _publish(self.flow, graph)
        result = start_session_v2(self.flow)
        # Após start: passou por message (auto) e parou em q1
        self.assertEqual(result["step"]["id"], "q1")


class HandoffNodeTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("e@t.com", "E", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="HO", channel="webchat", is_active=True,
        )

    def test_handoff_completes_session(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("h1", "handoff", message_to_user="Transferindo para humano"),
                _node("e1", "end"),
            ],
            "edges": [
                _edge("a", "s1", "h1"),
                _edge("b", "h1", "e1"),
            ],
        }
        _publish(self.flow, graph)
        result = start_session_v2(self.flow)
        self.assertTrue(result["is_complete"])


class MessageAndLogPersistenceTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("e@t.com", "E", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="P", channel="webchat", is_active=True,
        )

    def test_messages_and_logs_persisted(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("m1", "message", text="Oi!"),
                _node("q1", "question", prompt="Nome?", lead_field="name"),
                _node("e1", "end"),
            ],
            "edges": [
                _edge("a", "s1", "m1"),
                _edge("b", "m1", "q1"),
                _edge("c", "q1", "e1"),
            ],
        }
        _publish(self.flow, graph)
        sk = start_session_v2(self.flow)["session_key"]
        process_response_v2(sk, "João")
        session = ChatbotSession.objects.get(session_key=sk)

        # Mensagens outbound (msg+q1) + inbound (João)
        outbound = ChatbotMessage.objects.filter(
            session=session, direction="outbound",
        ).count()
        inbound = ChatbotMessage.objects.filter(
            session=session, direction="inbound",
        ).count()
        self.assertGreaterEqual(outbound, 2)
        self.assertEqual(inbound, 1)

        # Logs de entrada de node
        entered_logs = ChatbotExecutionLog.objects.filter(
            session=session, event="node_entered",
        ).count()
        self.assertGreaterEqual(entered_logs, 2)


class DispatcherTests(TestCase):
    """Garante que start_session/process_response delegam ao motor correto."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("d@t.com", "D", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Dispatch", channel="webchat", is_active=True,
        )

    def test_dispatch_to_v2_when_visual_builder_flag(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("q1", "question", prompt="?", lead_field="name"),
                _node("e1", "end"),
            ],
            "edges": [
                _edge("a", "s1", "q1"),
                _edge("b", "q1", "e1"),
            ],
        }
        _publish(self.flow, graph)
        # API pública start_session
        result = start_session(self.flow)
        self.assertEqual(result["step"]["id"], "q1")
        # process_response também via dispatcher
        result2 = process_response(result["session_key"], "Maria")
        self.assertTrue(result2["is_complete"])

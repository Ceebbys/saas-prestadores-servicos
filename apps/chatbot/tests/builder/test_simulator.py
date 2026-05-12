"""V2B — Testes do simulador inline."""
import json

from django.test import TestCase
from django.urls import reverse

from apps.chatbot.builder.services.simulator import (
    process_simulation,
    start_simulation,
)
from apps.chatbot.models import ChatbotFlow, ChatbotFlowVersion, ChatbotSession
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _node(nid, ntype, **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": data}


def _edge(eid, src, tgt, sh="next"):
    return {"id": eid, "source": src, "target": tgt, "sourceHandle": sh, "targetHandle": "in"}


class SimulatorServiceTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("s@t.com", "S", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Sim", channel="webchat",
        )

    def test_start_advances_to_first_question(self):
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
        result = start_simulation(self.flow, graph)
        self.assertFalse(result["is_complete"])
        self.assertEqual(result["step"]["id"], "q1")
        # Mensagem outbound do prompt
        self.assertEqual(result["messages"][-1]["content"], "Nome?")

    def test_step_response_advances_and_stores_lead_data(self):
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
        state = start_simulation(self.flow, graph)
        result = process_simulation(graph, state, "Maria")
        self.assertTrue(result["is_complete"])
        self.assertEqual(result["lead_data"]["name"], "Maria")

    def test_simulation_does_not_persist_session(self):
        """Sandbox NÃO cria ChatbotSession."""
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [_node("s1", "start"), _node("e1", "end")],
            "edges": [_edge("a", "s1", "e1")],
        }
        before = ChatbotSession.objects.count()
        result = start_simulation(self.flow, graph)
        after = ChatbotSession.objects.count()
        self.assertEqual(before, after)  # zero sessões criadas
        self.assertTrue(result["is_complete"])

    def test_menu_simulation_by_label(self):
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("m1", "menu", prompt="?", options=[
                    {"label": "Sim", "handle_id": "y"},
                    {"label": "Não", "handle_id": "n"},
                ]),
                _node("e_y", "end", completion_message="Sim"),
                _node("e_n", "end", completion_message="Não"),
            ],
            "edges": [
                _edge("a", "s1", "m1"),
                _edge("b", "m1", "e_y", "y"),
                _edge("c", "m1", "e_n", "n"),
            ],
        }
        state = start_simulation(self.flow, graph)
        self.assertEqual(state["step"]["type"], "menu")
        result = process_simulation(graph, state, "Sim")
        self.assertTrue(result["is_complete"])

    def test_api_call_is_mocked(self):
        """No simulador, api_call NUNCA dispara request real — mock success."""
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                _node("s1", "start"),
                _node("a1", "api_call",
                      secret_ref="xx", method="POST",
                      path_template="https://api.fake/x",
                      response_var="result"),
                _node("e_ok", "end"),
                _node("e_err", "end"),
            ],
            "edges": [
                _edge("a", "s1", "a1"),
                _edge("b", "a1", "e_ok", "success"),
                _edge("c", "a1", "e_err", "error"),
            ],
        }
        result = start_simulation(self.flow, graph)
        self.assertTrue(result["is_complete"])
        # Sem fazer request real, segue 'success' branch
        self.assertEqual(result["lead_data"].get("result"), {"_simulated": True})


class SimulatorEndpointsTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.empresa = create_test_empresa()
        self.user = create_test_user("u@t.com", "U", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="EP", channel="webchat",
        )
        self.client.force_login(self.user)
        # Cria draft com graph simples
        ChatbotFlowVersion.objects.create(
            flow=self.flow,
            status=ChatbotFlowVersion.Status.DRAFT,
            graph_json={
                "schema_version": 1,
                "viewport": {"x": 0, "y": 0, "zoom": 1},
                "metadata": {},
                "nodes": [
                    _node("s1", "start"),
                    _node("q1", "question", prompt="Olá?", lead_field="name"),
                    _node("e1", "end"),
                ],
                "edges": [_edge("a", "s1", "q1"), _edge("b", "q1", "e1")],
            },
        )

    def test_start_endpoint_returns_step(self):
        url = reverse("chatbot:builder_simulator_start", args=[self.flow.pk])
        resp = self.client.post(url, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["is_complete"])
        self.assertEqual(data["step"]["id"], "q1")

    def test_step_endpoint_completes_flow(self):
        start_url = reverse("chatbot:builder_simulator_start", args=[self.flow.pk])
        step_url = reverse("chatbot:builder_simulator_step", args=[self.flow.pk])
        state = self.client.post(start_url, content_type="application/json").json()
        resp = self.client.post(
            step_url,
            data=json.dumps({"state": state, "response": "João"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_complete"])
        self.assertEqual(data["lead_data"]["name"], "João")

    def test_cross_tenant_simulator_returns_404(self):
        outra = create_test_empresa(name="X", slug="x-sim")
        create_test_user("x@t.com", "X", outra)
        flow_x = ChatbotFlow.objects.create(empresa=outra, name="FX", channel="webchat")
        url = reverse("chatbot:builder_simulator_start", args=[flow_x.pk])
        resp = self.client.post(url, content_type="application/json")
        self.assertEqual(resp.status_code, 404)

"""RV06 — Vincular serviço por opção de menu (feedback usuário).

Cliente pediu: 'se ligue colca a opção de vinvular a um serviço' no
menu de opções. Cada option pode ter `servico_id`. Quando o cliente
escolhe essa opção, lead.servico é setado + lead_data.servico_snapshot
gravado (igual ao bloco link_servico).
"""
from decimal import Decimal

from django.test import TestCase

from apps.chatbot.builder.services.simulator import (
    process_simulation, start_simulation,
)
from apps.chatbot.models import ChatbotFlow, ChatbotSession
from apps.core.tests.helpers import create_test_empresa
from apps.operations.models import ServiceType


def _graph_with_menu_option_servico(svc_a_id, svc_b_id):
    """Menu com 3 opções: A vinculada a serviço A, B vinculada a serviço B,
    C sem vínculo."""
    return {
        "schema_version": 1,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "metadata": {},
        "nodes": [
            {"id": "n_start", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "n_menu", "type": "menu", "position": {"x": 100, "y": 100}, "data": {
                "prompt": "Qual serviço?",
                "options": [
                    {"label": "A", "handle_id": "opt_a", "servico_id": svc_a_id},
                    {"label": "B", "handle_id": "opt_b", "servico_id": svc_b_id},
                    {"label": "C", "handle_id": "opt_c"},  # sem servico_id
                ],
            }},
            {"id": "n_end_a", "type": "end", "position": {"x": 200, "y": 0}, "data": {}},
            {"id": "n_end_b", "type": "end", "position": {"x": 200, "y": 50}, "data": {}},
            {"id": "n_end_c", "type": "end", "position": {"x": 200, "y": 100}, "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "n_start", "target": "n_menu", "sourceHandle": "next"},
            {"id": "e2", "source": "n_menu", "target": "n_end_a", "sourceHandle": "opt_a"},
            {"id": "e3", "source": "n_menu", "target": "n_end_b", "sourceHandle": "opt_b"},
            {"id": "e4", "source": "n_menu", "target": "n_end_c", "sourceHandle": "opt_c"},
        ],
    }


class SimulatorMenuOptionServicoTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-menuopt-svc")
        self.svc_a = ServiceType.objects.create(
            empresa=self.empresa, name="Topografia",
            default_price=Decimal("5500.00"), default_prazo_dias=14,
        )
        self.svc_b = ServiceType.objects.create(
            empresa=self.empresa, name="Levantamento",
            default_price=Decimal("1500.00"), default_prazo_dias=3,
        )

    def test_option_with_servico_id_writes_to_lead_data(self):
        graph = _graph_with_menu_option_servico(self.svc_a.pk, self.svc_b.pk)
        state = start_simulation(None, graph)
        result = process_simulation(graph, state, "A")
        self.assertFalse(result.get("error"))
        self.assertEqual(result["lead_data"].get("servico_id"), self.svc_a.pk)

    def test_different_option_different_servico(self):
        graph = _graph_with_menu_option_servico(self.svc_a.pk, self.svc_b.pk)
        state = start_simulation(None, graph)
        result = process_simulation(graph, state, "B")
        self.assertEqual(result["lead_data"].get("servico_id"), self.svc_b.pk)

    def test_option_without_servico_does_not_set(self):
        graph = _graph_with_menu_option_servico(self.svc_a.pk, self.svc_b.pk)
        state = start_simulation(None, graph)
        result = process_simulation(graph, state, "C")
        self.assertNotIn("servico_id", result["lead_data"])


class ExecutorMenuOptionServicoTests(TestCase):
    """E2E motor real: ChatbotSession recebe servico vinculado."""

    def setUp(self):
        from apps.chatbot.models import ChatbotFlowVersion
        self.empresa = create_test_empresa(slug="rv06-menuopt-exec")
        self.svc_a = ServiceType.objects.create(
            empresa=self.empresa, name="Topografia",
            default_price=Decimal("5500.00"), default_prazo_dias=14,
        )
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="whatsapp",
            is_active=True, use_visual_builder=True,
        )
        graph = _graph_with_menu_option_servico(self.svc_a.pk, 0)
        self.version = ChatbotFlowVersion.objects.create(
            flow=self.flow,
            status=ChatbotFlowVersion.Status.PUBLISHED,
            graph_json=graph,
        )
        self.flow.current_published_version = self.version
        self.flow.save(update_fields=["current_published_version"])

    def test_choosing_option_with_servico_writes_session_lead_data(self):
        from apps.chatbot.builder.services.flow_executor import (
            _validate_user_input, _store_lead_data,
        )
        session = ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511777771111",
            current_node_id="n_menu",
        )
        # Simula menu node
        menu_node = self.version.graph_json["nodes"][1]
        self.assertEqual(menu_node["type"], "menu")

        validation = _validate_user_input(menu_node, "A")
        self.assertEqual(validation.get("servico_id"), self.svc_a.pk)

        _store_lead_data(menu_node, "A", validation, session)
        session.refresh_from_db()
        self.assertEqual(session.lead_data.get("servico_id"), self.svc_a.pk)
        snap = session.lead_data.get("servico_snapshot") or {}
        self.assertEqual(snap.get("name"), "Topografia")
        self.assertEqual(snap.get("default_price"), "5500.00")

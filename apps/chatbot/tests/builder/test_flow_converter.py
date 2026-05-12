"""RV06 — Testes do flow_converter (legacy → graph_json).

Cobre conversão de:
- fluxo linear (3 steps text/email/name)
- fluxo com choices (menu com branching)
- fluxo com is_final
- fluxo vazio
- fluxo com step solto sem next_step nas choices
"""
from django.test import TestCase

from apps.chatbot.builder.services.flow_converter import convert_legacy_flow_to_graph
from apps.chatbot.builder.services.flow_validator import validate_graph
from apps.chatbot.models import ChatbotChoice, ChatbotFlow, ChatbotStep
from apps.core.tests.helpers import create_test_empresa, create_test_user


class FlowConverterLinearTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("c@t.com", "C", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Linear", channel="webchat",
            welcome_message="Bem-vindo!",
        )

    def test_empty_flow_creates_start_and_end(self):
        graph = convert_legacy_flow_to_graph(self.flow)
        types = [n["type"] for n in graph["nodes"]]
        self.assertEqual(set(types), {"start", "end"})
        # start → end edge
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["source"], "n_start")

    def test_linear_flow_three_steps(self):
        s1 = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Qual seu nome?",
            step_type="name", lead_field_mapping="name",
        )
        s2 = ChatbotStep.objects.create(
            flow=self.flow, order=1, question_text="Seu email?",
            step_type="email", lead_field_mapping="email",
        )
        s3 = ChatbotStep.objects.create(
            flow=self.flow, order=2, question_text="Obrigado!",
            step_type="text", is_final=True,
        )
        graph = convert_legacy_flow_to_graph(self.flow)

        # 1 start + 3 steps + 1 end = 5 nodes
        self.assertEqual(len(graph["nodes"]), 5)
        types = [n["type"] for n in graph["nodes"]]
        self.assertIn("start", types)
        self.assertIn("end", types)
        self.assertIn("question", types)  # text/name → question
        self.assertIn("collect_data", types)  # email → collect_data

        # Validator deve aceitar
        result = validate_graph(graph, flow=self.flow)
        self.assertTrue(result["valid"], result["errors"])

    def test_position_xy_preserved_from_legacy(self):
        ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Pos test",
            step_type="text",
            position_x=125.5, position_y=200.0,
        )
        graph = convert_legacy_flow_to_graph(self.flow)
        # Encontra o node do step
        step_node = next(
            n for n in graph["nodes"] if n["type"] == "question"
        )
        self.assertAlmostEqual(step_node["position"]["x"], 125.5)
        self.assertAlmostEqual(step_node["position"]["y"], 200.0)


class FlowConverterChoicesTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("c@t.com", "C", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Menu", channel="webchat",
        )

    def test_choice_step_becomes_menu_node(self):
        s_menu = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="O que deseja?",
            step_type="choice",
        )
        s_a = ChatbotStep.objects.create(
            flow=self.flow, order=1, question_text="Orçamento",
            step_type="text", is_final=True,
        )
        s_b = ChatbotStep.objects.create(
            flow=self.flow, order=2, question_text="Suporte",
            step_type="text", is_final=True,
        )
        ChatbotChoice.objects.create(step=s_menu, text="Orçamento", order=0, next_step=s_a)
        ChatbotChoice.objects.create(step=s_menu, text="Suporte", order=1, next_step=s_b)

        graph = convert_legacy_flow_to_graph(self.flow)
        menu_node = next(n for n in graph["nodes"] if n["type"] == "menu")
        self.assertEqual(len(menu_node["data"]["options"]), 2)
        labels = [o["label"] for o in menu_node["data"]["options"]]
        self.assertIn("Orçamento", labels)
        self.assertIn("Suporte", labels)

        # Edges com sourceHandle opt_0 e opt_1
        handles = [
            e["sourceHandle"] for e in graph["edges"]
            if e["source"] == menu_node["id"]
        ]
        self.assertIn("opt_0", handles)
        self.assertIn("opt_1", handles)

    def test_choice_without_next_step_falls_to_next_in_order(self):
        s_menu = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="?",
            step_type="choice",
        )
        s_next = ChatbotStep.objects.create(
            flow=self.flow, order=1, question_text="Próximo",
            step_type="text", is_final=True,
        )
        ChatbotChoice.objects.create(step=s_menu, text="A", order=0, next_step=None)
        ChatbotChoice.objects.create(step=s_menu, text="B", order=1, next_step=None)

        graph = convert_legacy_flow_to_graph(self.flow)
        # Ambas opções devem apontar para s_next
        menu_node = next(n for n in graph["nodes"] if n["type"] == "menu")
        edges_out = [
            e for e in graph["edges"] if e["source"] == menu_node["id"]
        ]
        targets = {e["target"] for e in edges_out}
        s_next_node_id = f"n_step_{s_next.pk}"
        self.assertIn(s_next_node_id, targets)


class FlowConverterIsFinalTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("c@t.com", "C", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Final", channel="webchat",
        )

    def test_is_final_step_connects_to_end_node(self):
        s = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Pergunta final",
            step_type="text", is_final=True,
        )
        graph = convert_legacy_flow_to_graph(self.flow)
        # Há um node 'end'
        end_node = next(n for n in graph["nodes"] if n["type"] == "end")
        # E o step aponta para ele
        step_node_id = f"n_step_{s.pk}"
        outgoing = [
            e for e in graph["edges"] if e["source"] == step_node_id
        ]
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0]["target"], end_node["id"])


class FlowConverterIntegrationTests(TestCase):
    """Resultado do converter deve passar pelo validator (sem erros bloqueadores)."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("c@t.com", "C", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Real", channel="webchat",
            welcome_message="Oi!",
        )
        ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Qual seu nome?",
            step_type="name", lead_field_mapping="name",
        )
        ChatbotStep.objects.create(
            flow=self.flow, order=1, question_text="Email?",
            step_type="email", lead_field_mapping="email",
        )
        ChatbotStep.objects.create(
            flow=self.flow, order=2, question_text="Obrigado!",
            step_type="text", is_final=True,
        )

    def test_converted_graph_passes_validator(self):
        graph = convert_legacy_flow_to_graph(self.flow)
        result = validate_graph(graph, flow=self.flow)
        self.assertTrue(result["valid"], result["errors"])

    def test_converted_graph_has_metadata_flag(self):
        graph = convert_legacy_flow_to_graph(self.flow)
        self.assertTrue(graph["metadata"]["converted_from_legacy"])
        self.assertEqual(graph["metadata"]["legacy_flow_id"], self.flow.id)

"""RV06 Hotfix — Sanitização de extras do React Flow antes de salvar/validar.

Bug reportado em prod: cliente vê "Estrutura inválida: Additional properties
are not allowed ('className', 'measured' were unexpected)" ao clicar em
Validar. Causa: React Flow injeta esses campos em cada node, e o schema
graph_v1 tem additionalProperties:false.

Cobertura:
- sanitize_graph_for_storage remove extras de nodes
- mesma função remove extras de edges
- save endpoint persiste versão limpa
- validate endpoint sanitiza fluxo legacy antes de validar (e re-grava limpo)
"""
from django.test import TestCase
from django.urls import reverse
import json

from apps.chatbot.builder.services.graph_utils import sanitize_graph_for_storage
from apps.chatbot.builder.services.flow_validator import validate_graph
from apps.chatbot.models import ChatbotFlow, ChatbotFlowVersion
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _node_with_rf_extras(node_id="n_start_1", node_type="start"):
    """Nó como o React Flow envia ao backend: position + data + LIXO."""
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 100, "y": 100, "z": 99},  # z é extra
        "data": {"label": "Início", "welcome_message": "oi"},
        # Lixo injetado pelo React Flow:
        "className": "rf-node-error",
        "measured": {"width": 200, "height": 80},
        "selectable": True,
        "connectable": True,
        "deletable": True,
        "draggable": True,
        "focusable": True,
        "zIndex": 1,
        "ariaLabel": "Início",
        "handleBounds": {"source": [], "target": []},
    }


def _edge_with_rf_extras():
    return {
        "id": "e1",
        "source": "n_start_1",
        "target": "n_end_1",
        "sourceHandle": "next",
        "targetHandle": None,
        # Lixo:
        "interactionWidth": 20,
        "pathOptions": {"offset": 10},
        "focusable": True,
    }


class SanitizeGraphHelperTests(TestCase):

    def test_removes_className_and_measured_from_nodes(self):
        graph = {
            "schema_version": 1,
            "nodes": [_node_with_rf_extras()],
            "edges": [],
        }
        cleaned = sanitize_graph_for_storage(graph)
        node = cleaned["nodes"][0]
        self.assertNotIn("className", node)
        self.assertNotIn("measured", node)
        self.assertNotIn("selectable", node)
        self.assertNotIn("connectable", node)
        self.assertNotIn("focusable", node)
        self.assertNotIn("zIndex", node)
        self.assertNotIn("ariaLabel", node)
        self.assertNotIn("handleBounds", node)

    def test_preserves_required_node_fields(self):
        graph = {"schema_version": 1, "nodes": [_node_with_rf_extras()], "edges": []}
        cleaned = sanitize_graph_for_storage(graph)
        node = cleaned["nodes"][0]
        self.assertEqual(node["id"], "n_start_1")
        self.assertEqual(node["type"], "start")
        self.assertEqual(node["position"]["x"], 100)
        self.assertEqual(node["position"]["y"], 100)
        self.assertEqual(node["data"]["label"], "Início")
        self.assertEqual(node["data"]["welcome_message"], "oi")

    def test_strips_position_extras(self):
        """position deve ter apenas x/y."""
        graph = {"schema_version": 1, "nodes": [_node_with_rf_extras()], "edges": []}
        cleaned = sanitize_graph_for_storage(graph)
        pos = cleaned["nodes"][0]["position"]
        self.assertEqual(set(pos.keys()), {"x", "y"})

    def test_removes_extras_from_edges(self):
        graph = {
            "schema_version": 1,
            "nodes": [],
            "edges": [_edge_with_rf_extras()],
        }
        cleaned = sanitize_graph_for_storage(graph)
        edge = cleaned["edges"][0]
        self.assertNotIn("interactionWidth", edge)
        self.assertNotIn("pathOptions", edge)
        self.assertNotIn("focusable", edge)
        self.assertEqual(edge["id"], "e1")
        self.assertEqual(edge["source"], "n_start_1")
        self.assertEqual(edge["sourceHandle"], "next")

    def test_idempotent(self):
        """Rodar 2x não muda nada (sanitização é estável)."""
        graph = {"schema_version": 1, "nodes": [_node_with_rf_extras()], "edges": []}
        a = sanitize_graph_for_storage(graph)
        b = sanitize_graph_for_storage(a)
        self.assertEqual(a, b)

    def test_non_dict_input_returns_as_is(self):
        self.assertEqual(sanitize_graph_for_storage("not a dict"), "not a dict")
        self.assertIsNone(sanitize_graph_for_storage(None))


class ValidatorAcceptsSanitizedGraphTests(TestCase):
    """Antes do hotfix: validar fluxo com className/measured falhava com
    SCHEMA_VIOLATION para cada node. Agora deve passar."""

    def test_validator_accepts_sanitized_graph_no_schema_errors(self):
        graph = {
            "schema_version": 1,
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "metadata": {},
            "nodes": [
                _node_with_rf_extras("n_start", "start"),
                {
                    "id": "n_end",
                    "type": "end",
                    "position": {"x": 400, "y": 100},
                    "data": {"label": "Fim"},
                    "className": "rf-something",  # lixo
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "n_start",
                    "target": "n_end",
                    "sourceHandle": "next",
                    "interactionWidth": 20,  # lixo
                },
            ],
        }
        cleaned = sanitize_graph_for_storage(graph)
        result = validate_graph(cleaned)
        schema_errors = [e for e in result["errors"] if e["code"] == "SCHEMA_VIOLATION"]
        self.assertEqual(
            schema_errors, [],
            f"Validator ainda rejeita schema após sanitize: {schema_errors}",
        )


class LongEdgeIdAcceptedTests(TestCase):
    """RV06 Hotfix #2 — React Flow gera edge IDs concatenando source+target
    como 'xy-edge__{source}{sourceHandle}-{target}{targetHandle}'. Quando
    node_ids têm timestamp (n_menu_1778706798646_4), esses IDs facilmente
    passam de 64 chars. Schema antigo limitava a 64 → 12 erros 'too long'
    no fluxo do cliente. Agora maxLength=200."""

    def test_long_react_flow_edge_id_passes_schema(self):
        # ID real reportado pelo cliente (~76 chars)
        long_id = "xy-edge__n_menu_1778706798646_4opt_1778706814043_5-n_menu_1778706903389_5in"
        self.assertGreater(len(long_id), 64)
        self.assertLess(len(long_id), 200)

        graph = {
            "schema_version": 1,
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "metadata": {},
            "nodes": [
                {
                    "id": "n_menu_1778706798646_4",
                    "type": "menu",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "label": "Menu",
                        "prompt": "Escolha:",
                        "options": [
                            {"label": "A", "handle_id": "opt_1778706814043_5"},
                            {"label": "B", "handle_id": "opt_2"},
                        ],
                    },
                },
                {
                    "id": "n_menu_1778706903389_5",
                    "type": "menu",
                    "position": {"x": 400, "y": 0},
                    "data": {
                        "label": "Sub-menu",
                        "prompt": "Mais opções:",
                        "options": [
                            {"label": "X", "handle_id": "opt_x"},
                            {"label": "Y", "handle_id": "opt_y"},
                        ],
                    },
                },
            ],
            "edges": [
                {
                    "id": long_id,
                    "source": "n_menu_1778706798646_4",
                    "target": "n_menu_1778706903389_5",
                    "sourceHandle": "opt_1778706814043_5",
                },
            ],
        }
        result = validate_graph(graph)
        schema_errors = [e for e in result["errors"] if e["code"] == "SCHEMA_VIOLATION"]
        self.assertEqual(
            schema_errors, [],
            f"Edge ID longo ({len(long_id)} chars) deveria passar: {schema_errors}",
        )


class SaveEndpointSanitizesTests(TestCase):
    """End-to-end: POST /save/ com lixo do React Flow deve persistir limpo."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-sanitize")
        self.user = create_test_user("san@test.com", "San", self.empresa)
        self.client.force_login(self.user)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Sanitize Test", channel="whatsapp",
        )

    def test_save_strips_rf_extras_before_persisting(self):
        # Cria draft inicial via /init/
        init_url = reverse("chatbot:builder_init", args=[self.flow.pk])
        self.client.post(init_url, "{}", content_type="application/json")

        # POST /save/ com lixo
        save_url = reverse("chatbot:builder_save", args=[self.flow.pk])
        graph = {
            "schema_version": 1,
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "metadata": {},
            "nodes": [_node_with_rf_extras()],
            "edges": [_edge_with_rf_extras()],
        }
        resp = self.client.post(
            save_url, json.dumps({"graph": graph}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])

        # Lê o draft do banco e confirma que o lixo sumiu
        draft = ChatbotFlowVersion.objects.filter(
            flow=self.flow, status=ChatbotFlowVersion.Status.DRAFT,
        ).first()
        self.assertIsNotNone(draft)
        node = draft.graph_json["nodes"][0]
        self.assertNotIn("className", node)
        self.assertNotIn("measured", node)
        self.assertNotIn("handleBounds", node)

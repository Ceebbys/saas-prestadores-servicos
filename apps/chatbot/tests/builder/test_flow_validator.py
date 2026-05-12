"""RV06 — Testes do flow_validator.

Cobre as 12 etapas da pipeline: schema, start único, terminal, alcance,
campos required, menu, condition, ciclos, nós soltos, sanitização, limites.
"""
from django.test import SimpleTestCase

from apps.chatbot.builder.services.flow_validator import validate_graph


def _node(nid: str, ntype: str, **data) -> dict:
    """Helper de criação de node."""
    return {
        "id": nid,
        "type": ntype,
        "position": {"x": 0, "y": 0},
        "data": data,
    }


def _edge(eid: str, source: str, target: str, sourceHandle: str = "next") -> dict:
    return {
        "id": eid,
        "source": source,
        "target": target,
        "sourceHandle": sourceHandle,
        "targetHandle": "in",
    }


def _graph(nodes: list, edges: list = None) -> dict:
    return {
        "schema_version": 1,
        "nodes": nodes,
        "edges": edges or [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Schema básico
# ---------------------------------------------------------------------------


class SchemaValidationTests(SimpleTestCase):
    def test_empty_graph_fails_schema(self):
        result = validate_graph({"schema_version": 1, "nodes": [], "edges": []})
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("SCHEMA_VIOLATION", codes)  # nodes minItems=1

    def test_missing_schema_version(self):
        result = validate_graph({"nodes": [], "edges": []})
        self.assertFalse(result["valid"])

    def test_unknown_node_type_rejected(self):
        graph = _graph([_node("n1", "alien")])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        # SCHEMA_VIOLATION pega via enum; já cobre o caso
        self.assertTrue(any(c in ("SCHEMA_VIOLATION", "UNKNOWN_NODE_TYPE") for c in codes))


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


class StartNodeTests(SimpleTestCase):
    def test_no_start_node_fails(self):
        graph = _graph([_node("m1", "message", text="Oi")])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("MISSING_START", codes)

    def test_duplicate_start_fails(self):
        graph = _graph([
            _node("s1", "start"),
            _node("s2", "start"),
            _node("e1", "end"),
        ], [_edge("e_s_e", "s1", "e1")])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("DUPLICATE_START", codes)

    def test_start_with_inbound_fails(self):
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "message", text="Oi"),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "m1"),
            _edge("e2", "m1", "s1"),
            _edge("e3", "m1", "e1"),
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("START_HAS_INBOUND", codes)

    def test_start_not_connected_fails(self):
        graph = _graph([_node("s1", "start"), _node("e1", "end")])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("START_NOT_CONNECTED", codes)


# ---------------------------------------------------------------------------
# Fluxo válido mínimo
# ---------------------------------------------------------------------------


class MinimalValidFlowTests(SimpleTestCase):
    def test_start_message_end_is_valid(self):
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "message", text="Bem-vindo"),
            _node("e1", "end"),
        ], [
            _edge("e_s_m", "s1", "m1"),
            _edge("e_m_e", "m1", "e1"),
        ])
        result = validate_graph(graph)
        self.assertTrue(result["valid"], result["errors"])


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


class RequiredFieldTests(SimpleTestCase):
    def test_message_without_text_fails(self):
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "message"),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "m1"),
            _edge("e2", "m1", "e1"),
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [(e["code"], e["node_id"]) for e in result["errors"]]
        self.assertIn(("REQUIRED_FIELD_EMPTY", "m1"), codes)

    def test_collect_data_without_lead_field_fails(self):
        graph = _graph([
            _node("s1", "start"),
            _node("c1", "collect_data", prompt="Seu email?"),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "c1"),
            _edge("e2", "c1", "e1"),
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("REQUIRED_FIELD_EMPTY", codes)


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------


class MenuValidationTests(SimpleTestCase):
    def _menu_graph(self, options):
        return _graph([
            _node("s1", "start"),
            _node("m1", "menu", prompt="Escolha:", options=options),
            _node("e1", "end"),
        ], [
            _edge("e_s_m", "s1", "m1"),
            *[_edge(f"e_m_e_{i}", "m1", "e1", sourceHandle=o.get("handle_id", f"opt{i}"))
              for i, o in enumerate(options) if isinstance(o, dict)],
        ])

    def test_menu_with_2_options_connected_is_valid(self):
        opts = [
            {"label": "Sim", "handle_id": "yes"},
            {"label": "Não", "handle_id": "no"},
        ]
        result = validate_graph(self._menu_graph(opts))
        self.assertTrue(result["valid"], result["errors"])

    def test_menu_with_1_option_fails(self):
        opts = [{"label": "Sim", "handle_id": "yes"}]
        result = validate_graph(self._menu_graph(opts))
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("ARRAY_TOO_SHORT", codes)

    def test_menu_duplicate_handle_fails(self):
        opts = [
            {"label": "Sim", "handle_id": "x"},
            {"label": "Não", "handle_id": "x"},
        ]
        result = validate_graph(self._menu_graph(opts))
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("MENU_DUPLICATE_HANDLE", codes)

    def test_menu_unconnected_option_fails(self):
        opts = [
            {"label": "A", "handle_id": "a"},
            {"label": "B", "handle_id": "b"},
        ]
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "menu", prompt="?", options=opts),
            _node("e1", "end"),
        ], [
            _edge("e_s_m", "s1", "m1"),
            _edge("e_a", "m1", "e1", sourceHandle="a"),
            # handle 'b' não conectado
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("MENU_OPTION_NOT_CONNECTED", codes)


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------


class ConditionValidationTests(SimpleTestCase):
    def test_condition_with_both_branches_is_valid(self):
        graph = _graph([
            _node("s1", "start"),
            _node("c1", "condition", field="email", operator="exists"),
            _node("e_true", "end"),
            _node("e_false", "end"),
        ], [
            _edge("e_s_c", "s1", "c1"),
            _edge("e_t", "c1", "e_true", sourceHandle="true"),
            _edge("e_f", "c1", "e_false", sourceHandle="false"),
        ])
        result = validate_graph(graph)
        self.assertTrue(result["valid"], result["errors"])

    def test_condition_missing_false_branch_fails(self):
        graph = _graph([
            _node("s1", "start"),
            _node("c1", "condition", field="email", operator="exists"),
            _node("e1", "end"),
        ], [
            _edge("e_s_c", "s1", "c1"),
            _edge("e_t", "c1", "e1", sourceHandle="true"),
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [(e["code"], e.get("field")) for e in result["errors"]]
        self.assertTrue(any(c[0] == "CONDITION_MISSING_BRANCH" for c in codes))


# ---------------------------------------------------------------------------
# api_call coming_soon
# ---------------------------------------------------------------------------


class APICallComingSoonTests(SimpleTestCase):
    def test_api_call_block_is_blocked(self):
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "api_call", secret_ref="crm", method="POST", path_template="/x"),
            _node("e_ok", "end"),
            _node("e_err", "end"),
        ], [
            _edge("e_s", "s1", "a1"),
            _edge("e_ok", "a1", "e_ok", sourceHandle="success"),
            _edge("e_err", "a1", "e_err", sourceHandle="error"),
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("NODE_TYPE_COMING_SOON", codes)


# ---------------------------------------------------------------------------
# Ciclos & nós soltos
# ---------------------------------------------------------------------------


class CycleAndOrphanTests(SimpleTestCase):
    def test_cycle_without_exit_fails(self):
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "message", text="A"),
            _node("m2", "message", text="B"),
        ], [
            _edge("e_s", "s1", "m1"),
            _edge("e_a", "m1", "m2"),
            _edge("e_b", "m2", "m1"),
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("CYCLE_WITHOUT_EXIT", codes)

    def test_orphan_node_generates_warning(self):
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "message", text="Oi"),
            _node("orphan", "message", text="Sozinho"),
            _node("e1", "end"),
        ], [
            _edge("e_s", "s1", "m1"),
            _edge("e_e", "m1", "e1"),
        ])
        result = validate_graph(graph)
        codes = [w["code"] for w in result["warnings"]]
        self.assertIn("ORPHAN_NODE", codes)
        self.assertIn("NODE_NOT_REACHABLE", codes)


# ---------------------------------------------------------------------------
# Sanitização
# ---------------------------------------------------------------------------


class TextSanityTests(SimpleTestCase):
    def test_script_tag_generates_warning(self):
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "message", text="<script>alert(1)</script>Olá"),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "m1"),
            _edge("e2", "m1", "e1"),
        ])
        result = validate_graph(graph)
        codes = [w["code"] for w in result["warnings"]]
        self.assertIn("POTENTIALLY_UNSAFE_TEXT", codes)


# ---------------------------------------------------------------------------
# Limites
# ---------------------------------------------------------------------------


class LimitTests(SimpleTestCase):
    def test_text_field_too_long(self):
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "message", text="x" * 5500),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "m1"),
            _edge("e2", "m1", "e1"),
        ])
        result = validate_graph(graph)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("FIELD_TOO_LONG", codes)

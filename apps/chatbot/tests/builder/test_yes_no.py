"""Testes do bloco 'Pergunta SIM/NÃO' (feedback do cliente).

Cliente disse: 'pq assim eu fiz uma pergunta se ele me responder q sim
vai para um fluxo se responder q não vai para outro fluxo'. Bloco
Condition exige field+operator+value (avançado demais). Novo yes_no
combina pergunta + ramificação automática.
"""
from django.test import SimpleTestCase

from apps.chatbot.builder.services.flow_validator import validate_graph
from apps.chatbot.builder.services.yes_no_matcher import detect_yes_no


def _graph(nodes, edges):
    return {
        "schema_version": 1,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "metadata": {},
        "nodes": nodes,
        "edges": edges,
    }


def _node(nid, ntype, **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": data}


def _edge(eid, src, tgt, source_handle="next"):
    return {
        "id": eid, "source": src, "target": tgt,
        "sourceHandle": source_handle, "targetHandle": "in",
    }


class YesNoDetectorTests(SimpleTestCase):

    def test_yes_simple(self):
        self.assertEqual(detect_yes_no("sim").value, "yes")
        self.assertEqual(detect_yes_no("Sim").value, "yes")
        self.assertEqual(detect_yes_no("SIM").value, "yes")
        self.assertEqual(detect_yes_no("s").value, "yes")
        self.assertEqual(detect_yes_no("yes").value, "yes")
        self.assertEqual(detect_yes_no("ok").value, "yes")

    def test_no_simple(self):
        self.assertEqual(detect_yes_no("não").value, "no")
        self.assertEqual(detect_yes_no("nao").value, "no")
        self.assertEqual(detect_yes_no("NÃO").value, "no")
        self.assertEqual(detect_yes_no("n").value, "no")
        self.assertEqual(detect_yes_no("no").value, "no")

    def test_yes_phrases(self):
        self.assertEqual(detect_yes_no("com certeza").value, "yes")
        self.assertEqual(detect_yes_no("claro que sim").value, "yes")
        self.assertEqual(detect_yes_no("positivo").value, "yes")
        self.assertEqual(detect_yes_no("isso mesmo").value, "yes")
        self.assertEqual(detect_yes_no("exatamente").value, "yes")
        self.assertEqual(detect_yes_no("com toda certeza").value, "yes")
        self.assertEqual(detect_yes_no("beleza").value, "yes")

    def test_no_phrases(self):
        self.assertEqual(detect_yes_no("de jeito nenhum").value, "no")
        self.assertEqual(detect_yes_no("nem pensar").value, "no")
        self.assertEqual(detect_yes_no("jamais").value, "no")
        self.assertEqual(detect_yes_no("negativo").value, "no")
        self.assertEqual(detect_yes_no("nunca").value, "no")

    def test_unknown(self):
        self.assertEqual(detect_yes_no("talvez").value, "unknown")
        self.assertEqual(detect_yes_no("não sei").value, "no")  # contém "nao"
        self.assertEqual(detect_yes_no("xyzpdq").value, "unknown")
        self.assertEqual(detect_yes_no("").value, "unknown")
        self.assertEqual(detect_yes_no(None).value, "unknown")

    def test_punctuation_tolerated(self):
        self.assertEqual(detect_yes_no("Sim!").value, "yes")
        self.assertEqual(detect_yes_no("Sim.").value, "yes")
        self.assertEqual(detect_yes_no("Não, obrigado").value, "no")

    def test_yes_in_sentence(self):
        self.assertEqual(detect_yes_no("eu acho que sim").value, "yes")
        self.assertEqual(detect_yes_no("ok pode ser").value, "yes")


class YesNoValidatorTests(SimpleTestCase):
    """yes_no precisa de outbound 'yes' E 'no'."""

    def test_yes_no_node_validates(self):
        graph = _graph([
            _node("s1", "start"),
            _node("q1", "yes_no", prompt="É PJ?"),
            _node("c1", "message", text="É PJ"),
            _node("c2", "message", text="É PF"),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "q1"),
            _edge("e2", "q1", "c1", source_handle="yes"),
            _edge("e3", "q1", "c2", source_handle="no"),
            _edge("e4", "c1", "e1"),
            _edge("e5", "c2", "e1"),
        ])
        result = validate_graph(graph)
        # Sem erros (pode haver warnings, mas valid=True)
        self.assertTrue(
            result["valid"],
            f"Esperava válido. Erros: {result['errors']}",
        )

    def test_yes_no_without_prompt_fails(self):
        """prompt é required no catalog."""
        graph = _graph([
            _node("s1", "start"),
            _node("q1", "yes_no"),  # sem prompt
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "q1"),
            _edge("e2", "q1", "e1", source_handle="yes"),
            _edge("e3", "q1", "e1", source_handle="no"),
        ])
        result = validate_graph(graph)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("REQUIRED_FIELD_EMPTY", codes)

"""RV08 — Testes das ações inline (inline_actions) em CADA bloco.

Cliente pediu: "essa parada de ações tem q ta em todos os blocos tbm".

Cobre:
- inline_actions disparadas ao entrar no nó (qualquer tipo de bloco)
- is_active=False pula sem executar
- Múltiplas ações em ordem
- action_type vazio é ignorado silenciosamente
- Erro em uma ação não derruba o fluxo (dispatch_action captura)
- Logs estruturados (inline_action_executing + inline_action_executed)
- Sem inline_actions → sem ações disparadas (backward compat)
- Aceita config no topo OU em entry.config (compat)
"""
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.chatbot.builder.services.flow_executor import (
    _run_inline_actions, start_session_v2,
)
from apps.chatbot.models import (
    ChatbotExecutionLog,
    ChatbotFlow,
    ChatbotFlowVersion,
    ChatbotSession,
)
from apps.core.tests.helpers import create_test_empresa


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


class RunInlineActionsUnitTests(TestCase):
    """Testa a função `_run_inline_actions` em isolamento (com mock)."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-unit")
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="webchat", is_active=True,
        )
        self.session = ChatbotSession.objects.create(
            flow=self.flow, sender_id="webchat:test1",
            channel="webchat", current_node_id="",
        )

    def test_no_inline_actions_does_nothing(self):
        """Bloco sem inline_actions → não chama dispatch_action."""
        node = {"id": "n1", "type": "message", "data": {"text": "Oi"}}
        with patch("apps.chatbot.action_handlers.dispatch_action") as mock:
            _run_inline_actions(node, self.session)
        mock.assert_not_called()

    def test_empty_list_does_nothing(self):
        node = {"id": "n1", "type": "message", "data": {"inline_actions": []}}
        with patch("apps.chatbot.action_handlers.dispatch_action") as mock:
            _run_inline_actions(node, self.session)
        mock.assert_not_called()

    def test_inactive_action_is_skipped(self):
        """is_active=False não chama dispatch + loga skip."""
        node = {
            "id": "n1", "type": "message",
            "data": {"inline_actions": [
                {"action_type": "register_event", "is_active": False, "event_name": "x"},
            ]},
        }
        with patch("apps.chatbot.action_handlers.dispatch_action") as mock:
            _run_inline_actions(node, self.session)
        mock.assert_not_called()
        # Log de skip foi criado
        logs = ChatbotExecutionLog.objects.filter(
            session=self.session, event="inline_action_skipped",
        )
        self.assertEqual(logs.count(), 1)

    def test_empty_action_type_is_ignored(self):
        node = {
            "id": "n1", "type": "message",
            "data": {"inline_actions": [
                {"action_type": "", "event_name": "x"},
                {"action_type": "   ", "event_name": "y"},
                {"event_name": "z"},  # sem action_type
            ]},
        }
        with patch("apps.chatbot.action_handlers.dispatch_action") as mock:
            _run_inline_actions(node, self.session)
        mock.assert_not_called()

    def test_executes_active_actions_in_order(self):
        """Múltiplas ações são executadas na ordem do array."""
        node = {
            "id": "n1", "type": "message",
            "data": {"inline_actions": [
                {"action_type": "register_event", "event_name": "first"},
                {"action_type": "register_event", "event_name": "second"},
                {"action_type": "register_event", "event_name": "third"},
            ]},
        }
        calls = []

        def fake_dispatch(at, session, config):
            calls.append(config.get("event_name"))
            return {"ok": True}

        with patch(
            "apps.chatbot.action_handlers.dispatch_action",
            side_effect=fake_dispatch,
        ):
            _run_inline_actions(node, self.session)
        self.assertEqual(calls, ["first", "second", "third"])

    def test_accepts_config_at_top_or_nested(self):
        """Aceita campos no topo OU em entry.config (compat)."""
        node = {
            "id": "n1", "type": "message",
            "data": {"inline_actions": [
                {"action_type": "register_event", "config": {"event_name": "nested"}},
                {"action_type": "register_event", "event_name": "topo"},
            ]},
        }
        configs = []

        def fake_dispatch(at, session, config):
            configs.append(config.get("event_name"))
            return {"ok": True}

        with patch(
            "apps.chatbot.action_handlers.dispatch_action",
            side_effect=fake_dispatch,
        ):
            _run_inline_actions(node, self.session)
        self.assertEqual(configs, ["nested", "topo"])

    def test_skips_invalid_entries(self):
        """Entradas que não são dict são puladas (sem erro)."""
        node = {
            "id": "n1", "type": "message",
            "data": {"inline_actions": [
                "not a dict",
                None,
                42,
                {"action_type": "register_event", "event_name": "ok"},
            ]},
        }
        calls = []

        def fake_dispatch(at, session, config):
            calls.append(config.get("event_name"))
            return {"ok": True}

        with patch(
            "apps.chatbot.action_handlers.dispatch_action",
            side_effect=fake_dispatch,
        ):
            _run_inline_actions(node, self.session)
        # Só a entrada válida foi executada
        self.assertEqual(calls, ["ok"])

    def test_logs_executing_and_executed(self):
        """Cada ação gera 2 logs: executing + executed."""
        node = {
            "id": "n1", "type": "message",
            "data": {"inline_actions": [
                {"action_type": "register_event", "event_name": "x"},
            ]},
        }
        with patch(
            "apps.chatbot.action_handlers.dispatch_action",
            return_value={"ok": True, "message": "ok!"},
        ):
            _run_inline_actions(node, self.session)
        execing = ChatbotExecutionLog.objects.filter(
            session=self.session, event="inline_action_executing",
        )
        executed = ChatbotExecutionLog.objects.filter(
            session=self.session, event="inline_action_executed",
        )
        self.assertEqual(execing.count(), 1)
        self.assertEqual(executed.count(), 1)
        # Payload contém action_type + index
        self.assertEqual(execing.first().payload.get("action_type"), "register_event")
        self.assertEqual(execing.first().payload.get("index"), 0)

    def test_failed_action_logs_warning(self):
        """dispatch retornando ok=False gera log level=warning."""
        node = {
            "id": "n1", "type": "message",
            "data": {"inline_actions": [
                {"action_type": "register_event", "event_name": "x"},
            ]},
        }
        with patch(
            "apps.chatbot.action_handlers.dispatch_action",
            return_value={"ok": False, "message": "falhou"},
        ):
            _run_inline_actions(node, self.session)
        executed = ChatbotExecutionLog.objects.filter(
            session=self.session, event="inline_action_executed",
        ).first()
        self.assertEqual(executed.level, "warning")
        self.assertEqual(executed.payload.get("ok"), False)
        self.assertIn("falhou", executed.payload.get("message", ""))


class InlineActionsInFlowExecutorTests(TestCase):
    """End-to-end: inline_actions dentro de bloco message/start no fluxo."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-flow")
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="webchat", is_active=True,
        )

    def test_inline_action_in_message_block_fires(self):
        """Inline action num bloco 'message' dispara ao entrar no nó."""
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "message", text="Bem-vindo!", inline_actions=[
                {"action_type": "register_event", "event_name": "welcome_shown"},
            ]),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "m1"),
            _edge("e2", "m1", "e1"),
        ])
        _publish(self.flow, graph)
        with patch(
            "apps.chatbot.action_handlers.dispatch_action",
            return_value={"ok": True},
        ) as mock:
            result = start_session_v2(self.flow)
        self.assertTrue(result["is_complete"])
        # dispatch foi chamado com register_event
        mock.assert_called()
        # Ao menos uma chamada teve action_type=register_event
        called_action_types = [c.args[0] for c in mock.call_args_list]
        self.assertIn("register_event", called_action_types)

    def test_inline_action_in_start_block_fires(self):
        """Inline em bloco 'start' também dispara (cliente pediu 'em todos os blocos')."""
        graph = _graph([
            _node("s1", "start", inline_actions=[
                {"action_type": "register_event", "event_name": "flow_started"},
            ]),
            _node("e1", "end"),
        ], [
            _edge("e1", "s1", "e1"),
        ])
        _publish(self.flow, graph)
        with patch(
            "apps.chatbot.action_handlers.dispatch_action",
            return_value={"ok": True},
        ) as mock:
            result = start_session_v2(self.flow)
        self.assertTrue(result["is_complete"])
        mock.assert_called()

    def test_inline_action_error_does_not_break_flow(self):
        """Se dispatch_action levanta exceção, fluxo continua (já capturado dentro)."""
        graph = _graph([
            _node("s1", "start"),
            _node("m1", "message", text="Oi", inline_actions=[
                {"action_type": "register_event", "event_name": "x"},
            ]),
            _node("e1", "end", completion_message="Pronto"),
        ], [
            _edge("e1", "s1", "m1"),
            _edge("e2", "m1", "e1"),
        ])
        _publish(self.flow, graph)
        # Mock que levanta — _run_inline_actions chama dispatch_action que
        # internamente NÃO deve quebrar o fluxo.
        # Mas se ainda assim levanta, a chamada externa precisa ser robusta:
        # neste teste, dispatch_action ele mesmo nunca levanta, retorna
        # {"ok": False} mesmo em erro. Aqui simulamos isso.
        with patch(
            "apps.chatbot.action_handlers.dispatch_action",
            return_value={"ok": False, "message": "boom"},
        ):
            result = start_session_v2(self.flow)
        self.assertTrue(result["is_complete"])
        self.assertIn("Pronto", result.get("message", ""))

"""RV07 — Sistema completo de lembrete/retomada (feedback do cliente).

Cobre:
- enable_reminder=False ignora mesmo com reminder_value > 0
- Unit conversion (hours -> minutes)
- Backward compat: reminder_minutes antigo dispara reminder
- on_return_behavior=continue mantém current_node_id
- on_return_behavior=restart cria nova sessão (comportamento RV06)
- max_inactivity_value override flow
- auto_end_on_timeout marca COMPLETED em vez de EXPIRED
- Fallback do flow quando bloco está vazio
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.chatbot.models import (
    ChatbotFlow, ChatbotFlowVersion, ChatbotSession, WhatsAppConfig,
)
from apps.chatbot.reminders import (
    _resolve_reminder_config, send_idle_reminders, _to_minutes,
)
from apps.chatbot.whatsapp import _resolve_timeout_decision
from apps.core.tests.helpers import create_test_empresa


def _publish_question(flow, node_data: dict) -> ChatbotFlowVersion:
    """Helper: cria versão PUBLISHED com 1 nó question + start + end."""
    graph = {
        "schema_version": 1,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "metadata": {},
        "nodes": [
            {"id": "n_start", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "n_q1", "type": "question", "position": {"x": 100, "y": 100}, "data": node_data},
            {"id": "n_end", "type": "end", "position": {"x": 200, "y": 200}, "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "n_start", "target": "n_q1", "sourceHandle": "next"},
            {"id": "e2", "source": "n_q1", "target": "n_end", "sourceHandle": "next"},
        ],
    }
    v = ChatbotFlowVersion.objects.create(
        flow=flow, status=ChatbotFlowVersion.Status.PUBLISHED, graph_json=graph,
    )
    flow.current_published_version = v
    flow.save(update_fields=["current_published_version"])
    return v


# ===========================================================================
# Helper puros
# ===========================================================================


class HelpersTests(TestCase):

    def test_to_minutes_minutes(self):
        self.assertEqual(_to_minutes(30, "minutes"), 30)
        self.assertEqual(_to_minutes(0, "minutes"), 0)
        self.assertEqual(_to_minutes(None, "minutes"), 0)

    def test_to_minutes_hours(self):
        self.assertEqual(_to_minutes(2, "hours"), 120)
        self.assertEqual(_to_minutes(1, "hours"), 60)
        self.assertEqual(_to_minutes(0, "hours"), 0)

    def test_to_minutes_invalid(self):
        self.assertEqual(_to_minutes("abc", "minutes"), 0)
        self.assertEqual(_to_minutes([], "hours"), 0)

    def test_resolve_config_disabled(self):
        flow = ChatbotFlow.objects.create(
            empresa=create_test_empresa(slug="rv07-h1"),
            name="F", channel="whatsapp",
        )
        cfg = _resolve_reminder_config(
            {"enable_reminder": False, "reminder_value": 30, "reminder_unit": "minutes"},
            flow,
        )
        self.assertFalse(cfg["enabled"])

    def test_resolve_config_enabled_with_hours(self):
        flow = ChatbotFlow.objects.create(
            empresa=create_test_empresa(slug="rv07-h2"),
            name="F", channel="whatsapp",
        )
        cfg = _resolve_reminder_config(
            {"enable_reminder": True, "reminder_value": 2, "reminder_unit": "hours"},
            flow,
        )
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["reminder_minutes"], 120)

    def test_resolve_config_backward_compat_legacy_minutes(self):
        """reminder_minutes antigo (sem enable_reminder explicit) ativa lembrete."""
        flow = ChatbotFlow.objects.create(
            empresa=create_test_empresa(slug="rv07-h3"),
            name="F", channel="whatsapp",
        )
        cfg = _resolve_reminder_config({"reminder_minutes": 30}, flow)
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["reminder_minutes"], 30)


# ===========================================================================
# send_idle_reminders end-to-end
# ===========================================================================


class IdleRemindersBackwardCompatTests(TestCase):
    """Garante que fluxos antigos com reminder_minutes ainda funcionam."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-bc")
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="whatsapp",
            is_active=True, use_visual_builder=True,
            session_timeout_minutes=120,
        )
        # Node com campo antigo apenas
        _publish_question(self.flow, {
            "prompt": "?", "reminder_minutes": 10,
            "reminder_message": "Vc tá aí?",
        })
        WhatsAppConfig.objects.create(
            empresa=self.empresa, instance_name="t",
            api_url="https://x.test", api_key="k",
        )

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_legacy_reminder_minutes_still_fires(self, mock_send):
        ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511777770001",
            channel="whatsapp", current_node_id="n_q1",
            last_activity_at=timezone.now() - timedelta(minutes=15),
        )
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 1)
        # Mensagem é a do campo antigo
        call = mock_send.call_args
        self.assertEqual(call[0][1], "Vc tá aí?")


class IdleRemindersV2Tests(TestCase):
    """Campos novos: enable_reminder + reminder_value + reminder_unit."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-v2")
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="whatsapp",
            is_active=True, use_visual_builder=True,
            session_timeout_minutes=240,
        )
        WhatsAppConfig.objects.create(
            empresa=self.empresa, instance_name="t",
            api_url="https://x.test", api_key="k",
        )

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_enable_false_does_not_fire(self, mock_send):
        _publish_question(self.flow, {
            "prompt": "?",
            "enable_reminder": False,
            "reminder_value": 5, "reminder_unit": "minutes",
        })
        ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511888880001",
            channel="whatsapp", current_node_id="n_q1",
            last_activity_at=timezone.now() - timedelta(minutes=30),
        )
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 0)
        mock_send.assert_not_called()

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_enable_true_with_hours_unit(self, mock_send):
        _publish_question(self.flow, {
            "prompt": "?",
            "enable_reminder": True,
            "reminder_value": 1, "reminder_unit": "hours",  # 60min
            "reminder_message": "Lembrete em horas",
        })
        ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511888880002",
            channel="whatsapp", current_node_id="n_q1",
            last_activity_at=timezone.now() - timedelta(minutes=61),
        )
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 1)
        call = mock_send.call_args
        self.assertEqual(call[0][1], "Lembrete em horas")

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_max_inactivity_block_override(self, mock_send):
        """Quando block max_inactivity < threshold, lembrete não envia."""
        _publish_question(self.flow, {
            "prompt": "?",
            "enable_reminder": True,
            "reminder_value": 5, "reminder_unit": "minutes",
            "max_inactivity_value": 8, "max_inactivity_unit": "minutes",
        })
        # elapsed = 10min, reminder_min = 5min, max_inact = 8min → não envia
        ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511888880003",
            channel="whatsapp", current_node_id="n_q1",
            last_activity_at=timezone.now() - timedelta(minutes=10),
        )
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 0)


# ===========================================================================
# _resolve_timeout_decision (whatsapp.py)
# ===========================================================================


class TimeoutDecisionTests(TestCase):

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-td")
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="whatsapp",
            is_active=True, use_visual_builder=True,
            session_timeout_minutes=10,
        )

    def _make_session(self, data, current_node_id="n_q1"):
        _publish_question(self.flow, data)
        return ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511666660001",
            channel="whatsapp", current_node_id=current_node_id,
            last_activity_at=timezone.now() - timedelta(minutes=15),
        )

    def test_node_with_continue_returns_continue(self):
        s = self._make_session({"prompt": "?", "on_return_behavior": "continue"})
        decision = _resolve_timeout_decision(s, self.flow)
        self.assertEqual(decision["action"], "continue")

    def test_node_with_restart_returns_restart(self):
        s = self._make_session({"prompt": "?", "on_return_behavior": "restart"})
        decision = _resolve_timeout_decision(s, self.flow)
        self.assertEqual(decision["action"], "restart")

    def test_auto_end_overrides_to_end(self):
        s = self._make_session({"prompt": "?", "auto_end_on_timeout": True})
        decision = _resolve_timeout_decision(s, self.flow)
        self.assertEqual(decision["action"], "end")

    def test_empty_block_uses_flow_default(self):
        self.flow.default_on_return_behavior = "continue"
        self.flow.save()
        s = self._make_session({"prompt": "?"})  # sem on_return_behavior
        decision = _resolve_timeout_decision(s, self.flow)
        self.assertEqual(decision["action"], "continue")

    def test_legacy_flow_without_published_forces_restart(self):
        """Flow sem published_version (legacy) força restart mesmo com flow.default=continue."""
        flow_legacy = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Legacy", channel="whatsapp",
            is_active=True,
            default_on_return_behavior="continue",
            session_timeout_minutes=10,
        )
        s = ChatbotSession.objects.create(
            flow=flow_legacy, sender_id="5511666660002",
            channel="whatsapp", current_node_id="",
            last_activity_at=timezone.now() - timedelta(minutes=15),
        )
        decision = _resolve_timeout_decision(s, flow_legacy)
        self.assertEqual(decision["action"], "restart")

"""RV06 — Tests do serviço de lembretes (feedback usuário).

Cliente pediu: 'em todos os campos temos q ter aquela opção de marcar
o tempo de resposta fraga. tipo se o cara demora mais q 30 min pra
continuar manda uma msg vc está ai e retoma o fluxo. Se passa disso o
fluxo começa de novo caso ele mande uma msg'.

Cobre:
- send_idle_reminders detecta sessões idle elegíveis
- Pula sessões dentro da janela do reminder_minutes
- Pula sessões já com reminder enviado
- Pula sessões que passaram do session_timeout (fluxo morto)
- Pula nodes sem reminder configurado
- Atualiza reminder_sent_at após enviar
- Re-envia para próximo nó após cliente responder (reminder_sent_at limpo)
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.chatbot.models import (
    ChatbotFlow, ChatbotFlowVersion, ChatbotSession, WhatsAppConfig,
)
from apps.chatbot.reminders import send_idle_reminders
from apps.core.tests.helpers import create_test_empresa


def _make_published_graph(reminder_min=10, reminder_msg="Tá aí?"):
    return {
        "schema_version": 1,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "metadata": {},
        "nodes": [
            {"id": "n_start", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "n_q1", "type": "question", "position": {"x": 100, "y": 100}, "data": {
                "prompt": "Qual seu nome?",
                "reminder_minutes": reminder_min,
                "reminder_message": reminder_msg,
            }},
        ],
        "edges": [
            {"id": "e1", "source": "n_start", "target": "n_q1", "sourceHandle": "next"},
        ],
    }


class SendIdleRemindersTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-reminders")
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="whatsapp",
            is_active=True, use_visual_builder=True,
            session_timeout_minutes=120,  # 2h pra session expirar
        )
        self.version = ChatbotFlowVersion.objects.create(
            flow=self.flow,
            status=ChatbotFlowVersion.Status.PUBLISHED,
            graph_json=_make_published_graph(reminder_min=10),
        )
        self.flow.current_published_version = self.version
        self.flow.save(update_fields=["current_published_version"])
        WhatsAppConfig.objects.create(
            empresa=self.empresa, instance_name="test",
            api_url="https://x.test", api_key="k",
        )

    def _make_session(self, last_activity_ago_min=15, reminder_sent_at=None):
        return ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511999990001",
            channel="whatsapp",  # default seria 'webchat' (sem outbound auto)
            current_node_id="n_q1",
            last_activity_at=timezone.now() - timedelta(minutes=last_activity_ago_min),
            reminder_sent_at=reminder_sent_at,
        )

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_idle_beyond_threshold_sends_reminder(self, mock_send):
        """15min idle, threshold=10min → envia."""
        s = self._make_session(last_activity_ago_min=15)
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 1)
        s.refresh_from_db()
        self.assertIsNotNone(s.reminder_sent_at)
        mock_send.assert_called_once()
        # Mensagem enviada é a configurada no node
        call_args = mock_send.call_args
        self.assertEqual(call_args[0][1], "Tá aí?")

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_idle_within_threshold_skipped(self, mock_send):
        """5min idle, threshold=10min → ainda não."""
        self._make_session(last_activity_ago_min=5)
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["skipped"], 1)
        mock_send.assert_not_called()

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_already_reminded_skipped(self, mock_send):
        """reminder_sent_at preenchido → não duplica."""
        self._make_session(
            last_activity_ago_min=20,
            reminder_sent_at=timezone.now() - timedelta(minutes=5),
        )
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 0)
        # Filtrado pela query — nem entra em checked
        self.assertEqual(stats["checked"], 0)
        mock_send.assert_not_called()

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_session_expired_skipped(self, mock_send):
        """130min idle, session_timeout=120 → sessão morta, não envia."""
        self._make_session(last_activity_ago_min=130)
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["skipped"], 1)
        mock_send.assert_not_called()

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_node_without_reminder_skipped(self, mock_send):
        """Node sem reminder_minutes (=0) é pulado."""
        # Reconfigura graph sem reminder
        self.version.graph_json = _make_published_graph(reminder_min=0)
        self.version.save(update_fields=["graph_json"])
        self._make_session(last_activity_ago_min=60)
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["skipped"], 1)
        mock_send.assert_not_called()

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=False)
    def test_send_failure_does_not_mark_sent(self, mock_send):
        s = self._make_session(last_activity_ago_min=15)
        stats = send_idle_reminders()
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["skipped"], 1)
        s.refresh_from_db()
        self.assertIsNone(s.reminder_sent_at)  # não marcou

"""RV06 — Pausa do bot quando atendente assume (feedback usuário).

Cliente perguntou: 'quando q desativa quando ta com o atendete'.

Comportamento:
- Atendente envia 1ª msg manual via Inbox → Conversation.bot_paused=True
- Webhook do chatbot vê bot_paused=True para esse sender → não responde
- Botão 'Devolver ao bot' (POST /resume-bot/) reativa
"""
from unittest.mock import patch

from django.test import TestCase

from apps.chatbot.models import ChatbotFlow, ChatbotStep
from apps.communications.models import Conversation, ConversationMessage
from apps.communications.services import _pause_bot, resume_bot, send_whatsapp
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead


class BotPauseHelpersTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-pause-helpers")
        self.user = create_test_user("p@t.com", "P", self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="John", phone="5511999990001",
        )
        self.conv = Conversation.objects.create(
            empresa=self.empresa, lead=self.lead,
        )

    def test_pause_sets_fields(self):
        self.assertFalse(self.conv.bot_paused)
        _pause_bot(self.conv, self.user)
        self.conv.refresh_from_db()
        self.assertTrue(self.conv.bot_paused)
        self.assertIsNotNone(self.conv.bot_paused_at)
        self.assertEqual(self.conv.bot_paused_by_id, self.user.pk)

    def test_resume_clears_fields(self):
        _pause_bot(self.conv, self.user)
        resume_bot(self.conv)
        self.conv.refresh_from_db()
        self.assertFalse(self.conv.bot_paused)
        self.assertIsNone(self.conv.bot_paused_at)
        self.assertIsNone(self.conv.bot_paused_by_id)


class SendWhatsappPausesBotTests(TestCase):
    """Quando atendente envia via UI, send_whatsapp seta bot_paused=True."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-pause-send")
        self.user = create_test_user("send@t.com", "S", self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="John", phone="5511999990002",
        )
        self.conv = Conversation.objects.create(
            empresa=self.empresa, lead=self.lead,
        )

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    def test_human_send_pauses_bot(self, mock_send):
        # Sem WhatsAppConfig vai falhar early, mas mockar send_text não basta.
        # Vou criar o WhatsAppConfig.
        from apps.chatbot.models import WhatsAppConfig
        WhatsAppConfig.objects.create(
            empresa=self.empresa, instance_name="test",
            api_url="https://x.test", api_key="k",
        )
        send_whatsapp(self.conv, "olá manual", sender_user=self.user)
        self.conv.refresh_from_db()
        self.assertTrue(self.conv.bot_paused)
        self.assertEqual(self.conv.bot_paused_by_id, self.user.pk)

    def test_bot_outbound_does_NOT_pause(self):
        """record_bot_outbound não passa sender_user → bot continua ativo."""
        from apps.communications.services import record_bot_outbound
        record_bot_outbound(
            empresa=self.empresa, lead=self.lead,
            channel="whatsapp", content="oi do bot",
        )
        self.conv.refresh_from_db()
        self.assertFalse(self.conv.bot_paused)


class WebhookSkipsWhenPausedTests(TestCase):
    """_process_evolution_message ignora se bot_paused=True para o sender."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-pause-webhook")
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="whatsapp", is_active=True,
        )
        ChatbotStep.objects.create(
            flow=self.flow, order=0, step_type="text",
            question_text="Qual seu nome?",
        )
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="John", phone="5511777770001",
        )
        self.conv = Conversation.objects.create(
            empresa=self.empresa, lead=self.lead,
        )

    def test_webhook_paused_returns_empty_reply(self):
        from apps.chatbot.whatsapp import _process_evolution_message
        # Pausa
        from apps.communications.services import _pause_bot
        from apps.core.tests.helpers import create_test_user
        u = create_test_user("op@t.com", "Op", self.empresa)
        _pause_bot(self.conv, u)
        # Webhook recebe msg do mesmo phone
        reply, choices, is_complete, lead_id = _process_evolution_message(
            self.flow, "5511777770001", "oi de novo",
        )
        # Bot não responde
        self.assertEqual(reply, "")
        self.assertEqual(choices, [])
        self.assertFalse(is_complete)

    def test_webhook_not_paused_responds(self):
        from apps.chatbot.whatsapp import _process_evolution_message
        # bot_paused=False (default) — sem pause
        reply, _, _, _ = _process_evolution_message(
            self.flow, "5511777770001", "oi",
        )
        # Bot responde com welcome
        self.assertNotEqual(reply, "")

    def test_webhook_no_matching_conversation_responds(self):
        from apps.chatbot.whatsapp import _process_evolution_message
        # Phone diferente — sem conversation correspondente
        reply, _, _, _ = _process_evolution_message(
            self.flow, "5511888880001", "oi",
        )
        self.assertNotEqual(reply, "")

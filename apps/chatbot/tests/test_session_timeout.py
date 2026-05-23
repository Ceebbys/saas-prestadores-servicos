"""RV06 — Timeout de sessão do chatbot (feedback do usuário).

Cliente perguntou 'quando q ele começa sozinho novamente'. Feature:
- ChatbotFlow.session_timeout_minutes (default 30; 0 = nunca expira)
- ChatbotSession.last_activity_at + property is_expired
- _process_evolution_message expira session vencida e recomeça fluxo
- Opcional: session_timeout_message como prefixo da nova conversa
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.chatbot.models import (
    ChatbotAction, ChatbotChoice, ChatbotFlow, ChatbotSession, ChatbotStep,
)
from apps.core.tests.helpers import create_test_empresa


def _flow_with_step(empresa, timeout=30, timeout_msg=""):
    flow = ChatbotFlow.objects.create(
        empresa=empresa, name="Test", channel="whatsapp",
        is_active=True,
        session_timeout_minutes=timeout,
        session_timeout_message=timeout_msg,
    )
    ChatbotStep.objects.create(
        flow=flow, order=0, step_type="text",
        question_text="Qual seu nome?",
    )
    return flow


class IsExpiredPropertyTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-timeout-prop")
        self.flow = _flow_with_step(self.empresa, timeout=30)

    def test_active_recent_not_expired(self):
        s = ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511999990001",
            last_activity_at=timezone.now() - timedelta(minutes=5),
        )
        self.assertFalse(s.is_expired)

    def test_active_old_is_expired(self):
        s = ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511999990002",
            last_activity_at=timezone.now() - timedelta(minutes=31),
        )
        self.assertTrue(s.is_expired)

    def test_already_completed_not_expired(self):
        s = ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511999990003",
            status=ChatbotSession.Status.COMPLETED,
            last_activity_at=timezone.now() - timedelta(hours=2),
        )
        self.assertFalse(s.is_expired)

    def test_zero_timeout_never_expires(self):
        flow_no_timeout = _flow_with_step(
            create_test_empresa(slug="rv06-no-timeout"), timeout=0,
        )
        s = ChatbotSession.objects.create(
            flow=flow_no_timeout, sender_id="5511999990004",
            last_activity_at=timezone.now() - timedelta(days=30),
        )
        self.assertFalse(s.is_expired)


class ProcessMessageRestartsAfterTimeoutTests(TestCase):
    """E2E: _process_evolution_message detecta sessão expirada e cria nova."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-timeout-e2e")
        self.flow = _flow_with_step(
            self.empresa, timeout=30, timeout_msg="Olá de novo! Vamos recomeçar.",
        )

    def test_old_session_expires_and_new_session_starts(self):
        from apps.chatbot.whatsapp import _process_evolution_message
        old = ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511777770001",
            last_activity_at=timezone.now() - timedelta(minutes=45),
        )
        reply, choices, is_complete, lead_id = _process_evolution_message(
            self.flow, "5511777770001", "oi",
        )
        # Sessão antiga marcada EXPIRED
        old.refresh_from_db()
        self.assertEqual(old.status, ChatbotSession.Status.EXPIRED)
        # Nova sessão ACTIVE criada
        new_sessions = ChatbotSession.objects.filter(
            flow=self.flow, sender_id="5511777770001",
            status=ChatbotSession.Status.ACTIVE,
        )
        self.assertEqual(new_sessions.count(), 1)
        # Reply tem o prefixo do timeout_message
        self.assertIn("Olá de novo", reply)

    def test_recent_session_continues_without_restart(self):
        from apps.chatbot.whatsapp import _process_evolution_message
        # Cria session com current_step para o legacy processar OK
        step = ChatbotStep.objects.filter(flow=self.flow).first()
        recent = ChatbotSession.objects.create(
            flow=self.flow, sender_id="5511777770002",
            last_activity_at=timezone.now() - timedelta(minutes=5),
            current_step=step,
        )
        with patch("apps.chatbot.whatsapp.process_response", return_value={
            "step": {"question": "Próxima pergunta?", "choices": []},
        }):
            _process_evolution_message(self.flow, "5511777770002", "oi")
        recent.refresh_from_db()
        # Continua ACTIVE; last_activity atualizado
        self.assertEqual(recent.status, ChatbotSession.Status.ACTIVE)
        self.assertGreater(
            recent.last_activity_at,
            timezone.now() - timedelta(minutes=1),
        )

    def test_no_previous_session_starts_normally(self):
        """Primeira mensagem do cliente — sem sessão prévia, cria normal."""
        from apps.chatbot.whatsapp import _process_evolution_message
        _process_evolution_message(self.flow, "5511777770003", "oi")
        sessions = ChatbotSession.objects.filter(
            flow=self.flow, sender_id="5511777770003",
        )
        self.assertEqual(sessions.count(), 1)
        self.assertEqual(sessions.first().status, ChatbotSession.Status.ACTIVE)

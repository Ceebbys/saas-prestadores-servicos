"""Testes do adaptador WhatsApp (Evolution API)."""

import json
import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.chatbot.models import (
    ChatbotAction,
    ChatbotChoice,
    ChatbotFlow,
    ChatbotSession,
    ChatbotStep,
)
from apps.chatbot.whatsapp import EvolutionAPIClient, parse_evolution_webhook

from .helpers import create_test_empresa


def _create_flow_with_steps(empresa):
    """Helper: cria fluxo WhatsApp ativo com 3 passos + ação create_lead."""
    flow = ChatbotFlow.objects.create(
        empresa=empresa,
        name="Fluxo WhatsApp Teste",
        is_active=True,
        channel="whatsapp",
        welcome_message="Bem-vindo ao teste!",
        fallback_message="Não entendi.",
    )
    ChatbotStep.objects.create(
        flow=flow, order=0,
        question_text="Qual seu nome?",
        step_type=ChatbotStep.StepType.NAME,
        lead_field_mapping="name",
    )
    ChatbotStep.objects.create(
        flow=flow, order=1,
        question_text="Qual seu e-mail?",
        step_type=ChatbotStep.StepType.EMAIL,
        lead_field_mapping="email",
    )
    ChatbotStep.objects.create(
        flow=flow, order=2,
        question_text="Qual seu telefone?",
        step_type=ChatbotStep.StepType.PHONE,
        lead_field_mapping="phone",
    )
    ChatbotAction.objects.create(
        flow=flow,
        trigger=ChatbotAction.Trigger.ON_COMPLETE,
        action_type=ChatbotAction.ActionType.CREATE_LEAD,
    )
    return flow


def _make_evolution_payload(phone="5511999990000", text="Olá", from_me=False, event="messages.upsert"):
    """Helper: cria payload da Evolution API v2."""
    return {
        "event": event,
        "instance": "test-instance",
        "data": {
            "key": {
                "remoteJid": f"{phone}@s.whatsapp.net",
                "fromMe": from_me,
                "id": "ABC123",
            },
            "message": {
                "conversation": text,
            },
            "messageType": "conversation",
        },
    }


# ===========================================================================
# Parser tests
# ===========================================================================


class EvolutionWebhookParsingTests(TestCase):

    def test_parse_valid_text_message(self):
        body = _make_evolution_payload(phone="5511987654321", text="Olá mundo")
        result = parse_evolution_webhook(body)
        self.assertIsNotNone(result)
        sender_id, message, instance = result
        self.assertEqual(sender_id, "5511987654321")
        self.assertEqual(message, "Olá mundo")
        self.assertEqual(instance, "test-instance")

    def test_parse_button_response(self):
        body = _make_evolution_payload()
        body["data"]["message"] = {
            "buttonsResponseMessage": {
                "selectedDisplayText": "Solicitar Orçamento",
            }
        }
        result = parse_evolution_webhook(body)
        self.assertIsNotNone(result)
        _, message, _ = result
        self.assertEqual(message, "Solicitar Orçamento")

    def test_parse_ignores_from_me(self):
        body = _make_evolution_payload(from_me=True)
        result = parse_evolution_webhook(body)
        self.assertIsNone(result)

    def test_parse_ignores_non_message_events(self):
        body = _make_evolution_payload(event="connection.update")
        result = parse_evolution_webhook(body)
        self.assertIsNone(result)

    def test_parse_strips_whatsapp_suffix(self):
        body = _make_evolution_payload(phone="5521988887777")
        result = parse_evolution_webhook(body)
        sender_id, _, _ = result
        self.assertEqual(sender_id, "5521988887777")
        self.assertNotIn("@", sender_id)

    def test_parse_no_text_returns_none(self):
        body = _make_evolution_payload()
        body["data"]["message"] = {"imageMessage": {"url": "https://example.com/img.jpg"}}
        result = parse_evolution_webhook(body)
        self.assertIsNone(result)


# ===========================================================================
# Evolution webhook view tests
# ===========================================================================


class EvolutionWebhookViewTests(TransactionTestCase):

    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow = _create_flow_with_steps(self.empresa)
        self.url = reverse("chatbot:evolution_webhook", kwargs={"token": self.flow.webhook_token})

    def test_evolution_webhook_starts_session(self):
        payload = _make_evolution_payload(phone="5511999990000", text="Oi")
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("reply", data)
        self.assertFalse(data["is_complete"])
        # Session should have been created
        self.assertEqual(
            ChatbotSession.objects.filter(flow=self.flow, sender_id="5511999990000").count(), 1,
        )

    def test_evolution_webhook_continues_session(self):
        phone = "5511888880000"
        # First message — starts session
        self.client.post(
            self.url,
            data=json.dumps(_make_evolution_payload(phone=phone, text="Oi")),
            content_type="application/json",
        )
        # Second message — responds with name
        resp = self.client.post(
            self.url,
            data=json.dumps(_make_evolution_payload(phone=phone, text="Maria")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Should have advanced to email step
        self.assertIn("e-mail", data["reply"].lower())

    def test_evolution_webhook_invalid_token_404(self):
        url = reverse("chatbot:evolution_webhook", kwargs={"token": uuid.uuid4()})
        payload = _make_evolution_payload()
        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_evolution_webhook_non_message_200(self):
        payload = _make_evolution_payload(event="connection.update")
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ignored")
        # No session should be created
        self.assertEqual(ChatbotSession.objects.count(), 0)

    def test_evolution_webhook_from_me_ignored(self):
        payload = _make_evolution_payload(from_me=True)
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ignored")


# ===========================================================================
# Evolution API Client tests (mocked)
# ===========================================================================


class EvolutionAPIClientTests(TestCase):

    @override_settings(
        EVOLUTION_API_URL="http://evo.test:8080",
        EVOLUTION_API_KEY="test-key",
        EVOLUTION_INSTANCE_NAME="test-instance",
    )
    @patch("httpx.post")
    def test_send_text_calls_correct_url(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)

        client = EvolutionAPIClient()
        result = client.send_text("5511999990000", "Hello!")

        self.assertTrue(result)
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("/message/sendText/test-instance", call_args[0][0])
        self.assertEqual(call_args[1]["json"]["number"], "5511999990000")
        self.assertEqual(call_args[1]["json"]["text"], "Hello!")

    @override_settings(
        EVOLUTION_API_URL="http://evo.test:8080",
        EVOLUTION_API_KEY="test-key",
        EVOLUTION_INSTANCE_NAME="test-instance",
    )
    @patch("httpx.post")
    def test_send_buttons_formats_correctly(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)

        client = EvolutionAPIClient()
        result = client.send_buttons("5511999990000", "Escolha:", ["A", "B", "C"])

        self.assertTrue(result)
        call_args = mock_post.call_args
        self.assertIn("/message/sendButtons/", call_args[0][0])
        payload = call_args[1]["json"]
        self.assertEqual(len(payload["buttons"]), 3)

    def test_format_choices_as_text_fallback(self):
        client = EvolutionAPIClient()
        result = client._format_choices_as_text("Qual serviço?", ["A", "B", "C", "D"])
        self.assertIn("Qual serviço?", result)
        self.assertIn("A", result)
        self.assertIn("D", result)


# ===========================================================================
# Auto-detect webhook tests
# ===========================================================================


class EvolutionWebhookAutoTests(TransactionTestCase):

    def setUp(self):
        self.empresa = create_test_empresa()
        self.url = reverse("chatbot:evolution_webhook_auto")

    def test_auto_finds_active_whatsapp_flow(self):
        flow = _create_flow_with_steps(self.empresa)
        payload = _make_evolution_payload(phone="5511777770000", text="Oi")
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_auto_returns_404_when_no_active_flow(self):
        payload = _make_evolution_payload()
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)


# ===========================================================================
# Management command tests
# ===========================================================================


class CreateWhatsAppFlowsCommandTests(TransactionTestCase):

    def setUp(self):
        self.empresa = create_test_empresa(slug="cmd-test")

    def test_command_creates_three_flows(self):
        from django.core.management import call_command
        call_command("create_whatsapp_flows", empresa="cmd-test")

        flows = ChatbotFlow.objects.filter(empresa=self.empresa)
        self.assertEqual(flows.count(), 3)

        # The "Atendimento Completo" should have 7 steps
        completo = flows.get(name="Atendimento Completo WhatsApp")
        self.assertEqual(completo.steps.count(), 7)
        self.assertTrue(completo.is_active)

        # Actions should exist
        self.assertTrue(completo.actions.filter(action_type="create_lead").exists())

    def test_command_force_recreates(self):
        from django.core.management import call_command

        call_command("create_whatsapp_flows", empresa="cmd-test")
        self.assertEqual(ChatbotFlow.objects.filter(empresa=self.empresa).count(), 3)

        call_command("create_whatsapp_flows", empresa="cmd-test", force=True)
        self.assertEqual(ChatbotFlow.objects.filter(empresa=self.empresa).count(), 3)

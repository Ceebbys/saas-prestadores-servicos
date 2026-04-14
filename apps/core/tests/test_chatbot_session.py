"""Testes do chatbot funcional — sessões, API e webhook."""

import json
import uuid

from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.chatbot.models import (
    ChatbotAction,
    ChatbotChoice,
    ChatbotFlow,
    ChatbotSession,
    ChatbotStep,
)
from apps.chatbot.services import process_response, start_session
from apps.crm.models import Lead

from .helpers import create_test_empresa, create_test_user


def _create_flow_with_steps(empresa):
    """Helper: cria fluxo ativo com 3 passos + ação create_lead."""
    flow = ChatbotFlow.objects.create(
        empresa=empresa,
        name="Fluxo Teste",
        is_active=True,
        channel="webchat",
        welcome_message="Bem-vindo ao teste!",
        fallback_message="Não entendi.",
    )
    step_name = ChatbotStep.objects.create(
        flow=flow, order=0,
        question_text="Qual seu nome?",
        step_type=ChatbotStep.StepType.NAME,
        lead_field_mapping="name",
    )
    step_email = ChatbotStep.objects.create(
        flow=flow, order=1,
        question_text="Qual seu e-mail?",
        step_type=ChatbotStep.StepType.EMAIL,
        lead_field_mapping="email",
    )
    step_phone = ChatbotStep.objects.create(
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
    return flow, step_name, step_email, step_phone


# ===========================================================================
# Service layer tests
# ===========================================================================


class StartSessionTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow, self.step_name, _, _ = _create_flow_with_steps(self.empresa)

    def test_start_session_creates_session(self):
        result = start_session(self.flow)
        self.assertIn("session_key", result)
        self.assertEqual(result["flow_name"], "Fluxo Teste")
        self.assertEqual(result["welcome_message"], "Bem-vindo ao teste!")
        self.assertEqual(result["step"]["type"], "name")
        self.assertEqual(ChatbotSession.objects.count(), 1)

    def test_start_session_inactive_flow_raises(self):
        self.flow.is_active = False
        self.flow.save(update_fields=["is_active"])
        with self.assertRaises(ValueError):
            start_session(self.flow)

    def test_start_session_no_steps_raises(self):
        self.flow.steps.all().delete()
        with self.assertRaises(ValueError):
            start_session(self.flow)

    def test_start_session_sets_channel(self):
        result = start_session(self.flow, channel="simulator")
        session = ChatbotSession.objects.get(session_key=result["session_key"])
        self.assertEqual(session.channel, "simulator")


class ProcessResponseTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow, self.step_name, self.step_email, self.step_phone = (
            _create_flow_with_steps(self.empresa)
        )
        result = start_session(self.flow)
        self.session_key = result["session_key"]

    def test_advances_step(self):
        result = process_response(self.session_key, "João Silva")
        self.assertFalse(result["error"])
        self.assertFalse(result["is_complete"])
        self.assertEqual(result["step"]["type"], "email")

    def test_stores_lead_data(self):
        process_response(self.session_key, "João Silva")
        session = ChatbotSession.objects.get(session_key=self.session_key)
        self.assertEqual(session.lead_data["name"], "João Silva")

    def test_validates_email(self):
        # Advance past name step first
        process_response(self.session_key, "João")
        result = process_response(self.session_key, "not-an-email")
        self.assertTrue(result["error"])
        self.assertIn("e-mail válido", result["message"])

    def test_validates_phone(self):
        process_response(self.session_key, "João")
        process_response(self.session_key, "joao@test.com")
        result = process_response(self.session_key, "abc")
        self.assertTrue(result["error"])
        self.assertIn("telefone válido", result["message"])

    def test_completes_flow(self):
        process_response(self.session_key, "João Silva")
        process_response(self.session_key, "joao@test.com")
        result = process_response(self.session_key, "(11) 99999-0000")
        self.assertTrue(result["is_complete"])
        session = ChatbotSession.objects.get(session_key=self.session_key)
        self.assertEqual(session.status, ChatbotSession.Status.COMPLETED)

    def test_expired_session_rejected(self):
        session = ChatbotSession.objects.get(session_key=self.session_key)
        session.status = ChatbotSession.Status.EXPIRED
        session.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            process_response(self.session_key, "teste")

    def test_nonexistent_session_rejected(self):
        fake_key = str(uuid.uuid4())
        with self.assertRaises(ValueError):
            process_response(fake_key, "teste")


class FlowCompletionLeadTests(TransactionTestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow, _, _, _ = _create_flow_with_steps(self.empresa)

    def test_flow_completion_creates_lead(self):
        result = start_session(self.flow)
        sk = result["session_key"]
        process_response(sk, "Maria Souza")
        process_response(sk, "maria@test.com")
        result = process_response(sk, "(21) 98888-0000")

        self.assertTrue(result["is_complete"])
        self.assertIsNotNone(result["lead_id"])

        lead = Lead.objects.get(pk=result["lead_id"])
        self.assertEqual(lead.name, "Maria Souza")
        self.assertEqual(lead.email, "maria@test.com")
        self.assertEqual(lead.empresa, self.empresa)


class ChoiceStepTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Choice Flow", is_active=True,
        )
        self.step_choice = ChatbotStep.objects.create(
            flow=self.flow, order=0,
            question_text="Qual serviço?",
            step_type=ChatbotStep.StepType.CHOICE,
            lead_field_mapping="notes",
        )
        self.step_end = ChatbotStep.objects.create(
            flow=self.flow, order=1,
            question_text="Qual seu nome?",
            step_type=ChatbotStep.StepType.NAME,
            lead_field_mapping="name",
        )
        # Create choices — one with next_step, one without
        ChatbotChoice.objects.create(
            step=self.step_choice, text="Topografia", order=0,
        )
        ChatbotChoice.objects.create(
            step=self.step_choice, text="Engenharia", order=1,
            next_step=self.step_end,
        )

    def test_choice_validation_rejects_invalid(self):
        result = start_session(self.flow)
        sk = result["session_key"]
        result = process_response(sk, "Opção Inexistente")
        self.assertTrue(result["error"])
        self.assertIn("opções", result["message"])

    def test_choice_advances_to_next_step(self):
        result = start_session(self.flow)
        sk = result["session_key"]
        result = process_response(sk, "Topografia")
        self.assertFalse(result["error"])
        self.assertEqual(result["step"]["type"], "name")

    def test_choice_with_next_step_routing(self):
        result = start_session(self.flow)
        sk = result["session_key"]
        result = process_response(sk, "Engenharia")
        self.assertFalse(result["error"])
        # Should route to step_end via next_step on the choice
        self.assertEqual(result["step"]["question"], "Qual seu nome?")


# ===========================================================================
# API endpoint tests
# ===========================================================================


class ApiStartTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow, _, _, _ = _create_flow_with_steps(self.empresa)
        self.url = reverse("chatbot:api_start", kwargs={"token": self.flow.webhook_token})

    def test_api_start_returns_first_step(self):
        resp = self.client.post(
            self.url, data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("session_key", data)
        self.assertIn("step", data)
        self.assertEqual(data["step"]["type"], "name")

    def test_api_start_invalid_token_404(self):
        url = reverse("chatbot:api_start", kwargs={"token": uuid.uuid4()})
        resp = self.client.post(url, content_type="application/json")
        self.assertEqual(resp.status_code, 404)

    def test_api_start_get_405(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)


class ApiRespondTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow, _, _, _ = _create_flow_with_steps(self.empresa)
        self.start_url = reverse("chatbot:api_start", kwargs={"token": self.flow.webhook_token})
        self.respond_url = reverse("chatbot:api_respond", kwargs={"token": self.flow.webhook_token})

        resp = self.client.post(
            self.start_url, data=json.dumps({}), content_type="application/json",
        )
        self.session_key = resp.json()["session_key"]

    def test_api_respond_advances(self):
        resp = self.client.post(
            self.respond_url,
            data=json.dumps({"session_key": self.session_key, "response": "João"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["error"])
        self.assertEqual(data["step"]["type"], "email")

    def test_api_respond_missing_fields_400(self):
        resp = self.client.post(
            self.respond_url,
            data=json.dumps({"session_key": self.session_key}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class ApiFullFlowTests(TransactionTestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow, _, _, _ = _create_flow_with_steps(self.empresa)
        self.start_url = reverse("chatbot:api_start", kwargs={"token": self.flow.webhook_token})
        self.respond_url = reverse("chatbot:api_respond", kwargs={"token": self.flow.webhook_token})

    def test_api_full_flow_creates_lead(self):
        resp = self.client.post(
            self.start_url, data=json.dumps({}), content_type="application/json",
        )
        sk = resp.json()["session_key"]

        for answer in ["Carlos Santos", "carlos@test.com", "(31) 97777-0000"]:
            resp = self.client.post(
                self.respond_url,
                data=json.dumps({"session_key": sk, "response": answer}),
                content_type="application/json",
            )

        data = resp.json()
        self.assertTrue(data["is_complete"])
        self.assertIsNotNone(data["lead_id"])

        lead = Lead.objects.get(pk=data["lead_id"])
        self.assertEqual(lead.name, "Carlos Santos")
        self.assertEqual(lead.empresa, self.empresa)


# ===========================================================================
# Public chat + webhook tests
# ===========================================================================


class PublicChatTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow, _, _, _ = _create_flow_with_steps(self.empresa)

    def test_public_chat_page_renders(self):
        url = reverse("chatbot:public_chat", kwargs={"token": self.flow.webhook_token})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.flow.name)

    def test_public_chat_inactive_404(self):
        self.flow.is_active = False
        self.flow.save(update_fields=["is_active"])
        url = reverse("chatbot:public_chat", kwargs={"token": self.flow.webhook_token})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)


class WebhookTests(TransactionTestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow, _, _, _ = _create_flow_with_steps(self.empresa)
        self.url = reverse("chatbot:webhook_receive", kwargs={"token": self.flow.webhook_token})

    def test_webhook_starts_new_session(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"sender_id": "+5511999990000", "message": "oi"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("reply", data)
        self.assertFalse(data["is_complete"])

    def test_webhook_continues_existing_session(self):
        # Start session
        self.client.post(
            self.url,
            data=json.dumps({"sender_id": "+5511999990000", "message": "oi"}),
            content_type="application/json",
        )
        # Continue with name
        resp = self.client.post(
            self.url,
            data=json.dumps({"sender_id": "+5511999990000", "message": "Ana Paula"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("reply", data)

    def test_webhook_missing_sender_id_400(self):
        resp = self.client.post(
            self.url,
            data=json.dumps({"message": "oi"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_webhook_get_405(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)

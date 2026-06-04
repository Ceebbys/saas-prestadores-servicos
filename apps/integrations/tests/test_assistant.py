"""RV07 (6.1) — Assistente IA (Claude) no WhatsApp. SDK Anthropic mockado."""
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead
from apps.integrations.assistant import (
    AssistantService,
    get_assistant_service,
)
from apps.integrations.llm import run_agentic_loop
from apps.integrations.models import AssistantConfig


class FakeBlock:
    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type = type
        self.text = text
        self.name = name
        self.input = input
        self.id = id


class FakeResp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


# ---------------------------------------------------------------------------
# Loop agêntico (llm.py)
# ---------------------------------------------------------------------------
class AgenticLoopTests(TestCase):
    def test_no_api_key_errors(self):
        res = run_agentic_loop(
            api_key="", model="m", system="s", tools=[],
            messages=[{"role": "user", "content": "oi"}],
            tool_executor=lambda n, a: {"ok": True},
        )
        self.assertEqual(res["error"], "no_api_key")

    @patch("anthropic.Anthropic")
    def test_simple_reply(self, MockAnthropic):
        MockAnthropic.return_value.messages.create.return_value = FakeResp(
            "end_turn", [FakeBlock("text", text="Olá!")],
        )
        res = run_agentic_loop(
            api_key="k", model="m", system="s", tools=[],
            messages=[{"role": "user", "content": "oi"}],
            tool_executor=lambda n, a: {"ok": True},
        )
        self.assertIsNone(res["error"])
        self.assertEqual(res["reply"], "Olá!")

    @patch("anthropic.Anthropic")
    def test_executes_tool_then_replies(self, MockAnthropic):
        tool_block = FakeBlock(
            "tool_use", name="save_lead_details", input={"name": "João"}, id="t1",
        )
        MockAnthropic.return_value.messages.create.side_effect = [
            FakeResp("tool_use", [tool_block]),
            FakeResp("end_turn", [FakeBlock("text", text="Anotado, João!")]),
        ]
        calls = []

        def executor(name, args):
            calls.append((name, args))
            return {"ok": True, "message": "salvo"}

        res = run_agentic_loop(
            api_key="k", model="m", system="s", tools=[],
            messages=[{"role": "user", "content": "sou o joão"}],
            tool_executor=executor,
        )
        self.assertEqual(res["reply"], "Anotado, João!")
        self.assertEqual(calls, [("save_lead_details", {"name": "João"})])
        self.assertEqual(res["actions"][0]["tool"], "save_lead_details")

    @patch("anthropic.Anthropic")
    def test_api_exception_is_caught(self, MockAnthropic):
        MockAnthropic.return_value.messages.create.side_effect = RuntimeError("boom")
        res = run_agentic_loop(
            api_key="k", model="m", system="s", tools=[],
            messages=[{"role": "user", "content": "oi"}],
            tool_executor=lambda n, a: {"ok": True},
        )
        self.assertEqual(res["error"], "unexpected")
        self.assertEqual(res["reply"], "")


# ---------------------------------------------------------------------------
# Ferramentas + serviço (assistant.py)
# ---------------------------------------------------------------------------
class AssistantToolsTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="ai-tools")
        self.config = AssistantConfig.objects.create(
            empresa=self.empresa, is_enabled=True,
        )
        self.config.set_api_key("sk-ant-test")
        self.config.save()
        self.svc = AssistantService(self.config)

    def test_save_lead_updates_fields(self):
        lead = Lead.objects.create(empresa=self.empresa, name="WhatsApp 11999")
        res = self.svc._tool_save_lead(
            self.empresa, lead,
            {"name": "Maria", "email": "m@t.com", "interest": "telhado"},
        )
        self.assertTrue(res["ok"])
        lead.refresh_from_db()
        self.assertEqual(lead.name, "Maria")
        self.assertEqual(lead.email, "m@t.com")
        self.assertIn("telhado", lead.notes)

    def test_save_lead_cross_tenant_blocked(self):
        other = create_test_empresa(slug="ai-other")
        lead = Lead.objects.create(empresa=other, name="X")
        res = self.svc._tool_save_lead(self.empresa, lead, {"name": "Y"})
        self.assertFalse(res["ok"])

    def test_create_proposal_draft(self):
        from apps.proposals.models import Proposal

        lead = Lead.objects.create(empresa=self.empresa, name="Cliente")
        res = self.svc._tool_create_proposal(
            self.empresa, lead, {"title": "Reforma", "value": 2500},
        )
        self.assertTrue(res["ok"])
        prop = Proposal.objects.filter(empresa=self.empresa, lead=lead).first()
        self.assertIsNotNone(prop)
        self.assertEqual(prop.status, Proposal.Status.DRAFT)
        self.assertEqual(prop.title, "Reforma")

    def test_handle_inbound_builds_request(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Cliente")
        with patch(
            "apps.integrations.assistant.run_agentic_loop",
            return_value={"reply": "Oi! Como posso ajudar?", "actions": [], "error": None},
        ) as mock_loop:
            res = self.svc.handle_inbound_message(
                sender="11999", text="oi", lead=lead, history=[],
            )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["reply"], "Oi! Como posso ajudar?")
        _, kwargs = mock_loop.call_args
        self.assertEqual(kwargs["messages"][-1], {"role": "user", "content": "oi"})
        names = {t["name"] for t in kwargs["tools"]}
        self.assertEqual(names, {"save_lead_details", "create_proposal"})
        self.assertIn(self.empresa.name, kwargs["system"])

    def test_handle_inbound_error_returns_empty_reply(self):
        lead = Lead.objects.create(empresa=self.empresa, name="C")
        with patch(
            "apps.integrations.assistant.run_agentic_loop",
            return_value={"reply": "", "actions": [], "error": "auth"},
        ):
            res = self.svc.handle_inbound_message(sender="1", text="oi", lead=lead, history=[])
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["reply"], "")


class GetAssistantServiceTests(TestCase):
    def test_none_when_disabled(self):
        empresa = create_test_empresa(slug="ai-dis")
        AssistantConfig.objects.create(empresa=empresa, is_enabled=False)
        self.assertIsNone(get_assistant_service(empresa))

    def test_none_when_no_config(self):
        empresa = create_test_empresa(slug="ai-no")
        self.assertIsNone(get_assistant_service(empresa))

    def test_service_when_enabled(self):
        empresa = create_test_empresa(slug="ai-en")
        AssistantConfig.objects.create(empresa=empresa, is_enabled=True)
        self.assertIsNotNone(get_assistant_service(empresa))


# ---------------------------------------------------------------------------
# Roteamento no webhook (whatsapp.py)
# ---------------------------------------------------------------------------
class WebhookRoutingTests(TestCase):
    def test_process_with_assistant_returns_reply_and_mirrors(self):
        from apps.chatbot import whatsapp

        fake = Mock()
        fake.handle_inbound_message.return_value = {
            "status": "ok", "reply": "Olá do bot!", "actions": [],
        }
        with patch.object(whatsapp, "_resolve_or_create_lead_lazy", return_value=None), \
                patch.object(whatsapp, "_mirror_to_inbox") as mock_mirror:
            reply, choices, complete, lead_id = whatsapp._process_with_assistant(
                fake, Mock(), "11999", "oi",
            )
        self.assertEqual(reply, "Olá do bot!")
        self.assertFalse(complete)
        mock_mirror.assert_called_once()

    def test_process_with_assistant_fallback_on_empty(self):
        from apps.chatbot import whatsapp

        fake = Mock()
        fake.handle_inbound_message.return_value = {"status": "error", "reply": ""}
        with patch.object(whatsapp, "_resolve_or_create_lead_lazy", return_value=None), \
                patch.object(whatsapp, "_mirror_to_inbox"):
            reply, *_ = whatsapp._process_with_assistant(fake, Mock(), "11999", "oi")
        self.assertIn("atendente", reply.lower())


class AssistantSettingsPageTests(TestCase):
    def test_settings_page_renders(self):
        empresa = create_test_empresa(slug="ai-page")
        user = create_test_user("p@t.com", "P", empresa)
        self.client.force_login(user)
        resp = self.client.get(reverse("settings_app:assistant_settings"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Assistente IA")
        self.assertContains(resp, "Chave de API")
        html = resp.content.decode()
        self.assertNotIn("{% comment", html)
        self.assertNotIn("endcomment", html)

    def test_enabling_without_key_is_blocked(self):
        empresa = create_test_empresa(slug="ai-nokey")
        user = create_test_user("nk@t.com", "NK", empresa)
        self.client.force_login(user)
        self.client.post(reverse("settings_app:assistant_settings"), {
            "is_enabled": "on", "model_name": "claude-haiku-4-5",
        })
        config = AssistantConfig.objects.get(empresa=empresa)
        self.assertFalse(config.is_enabled)  # sem chave → não ativa

    def test_post_saves_key_and_enables(self):
        empresa = create_test_empresa(slug="ai-ok")
        user = create_test_user("ok@t.com", "OK", empresa)
        self.client.force_login(user)
        self.client.post(reverse("settings_app:assistant_settings"), {
            "is_enabled": "on", "model_name": "claude-sonnet-4-6",
            "api_key": "sk-ant-secret", "system_prompt": "Seja simpático.",
        })
        config = AssistantConfig.objects.get(empresa=empresa)
        self.assertTrue(config.is_enabled)
        self.assertEqual(config.model_name, "claude-sonnet-4-6")
        self.assertEqual(config.get_api_key(), "sk-ant-secret")
        # a chave NÃO é exibida de volta no GET
        resp = self.client.get(reverse("settings_app:assistant_settings"))
        self.assertNotContains(resp, "sk-ant-secret")

"""Testes multi-tenant do WhatsApp (Evolution API + WhatsAppConfig)."""

import json
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.chatbot.models import (
    ChatbotAction,
    ChatbotFlow,
    ChatbotSession,
    ChatbotStep,
    WhatsAppConfig,
)

from .helpers import create_test_empresa


def _make_evo_payload(phone="5511999990000", text="Oi", instance="empresa-a-whatsapp"):
    return {
        "event": "messages.upsert",
        "instance": instance,
        "data": {
            "key": {
                "remoteJid": f"{phone}@s.whatsapp.net",
                "fromMe": False,
                "id": "MSG001",
            },
            "message": {"conversation": text},
            "messageType": "conversation",
        },
    }


def _create_active_whatsapp_flow(empresa):
    flow = ChatbotFlow.objects.create(
        empresa=empresa,
        name="Flow WA Teste",
        is_active=True,
        channel="whatsapp",
        welcome_message="Ola!",
        fallback_message="Nao entendi.",
    )
    ChatbotStep.objects.create(
        flow=flow, order=0,
        question_text="Qual seu nome?",
        step_type=ChatbotStep.StepType.NAME,
        lead_field_mapping="name",
    )
    ChatbotAction.objects.create(
        flow=flow,
        trigger=ChatbotAction.Trigger.ON_COMPLETE,
        action_type=ChatbotAction.ActionType.CREATE_LEAD,
    )
    return flow


# ===========================================================================
# Model tests
# ===========================================================================


class WhatsAppConfigModelTests(TestCase):

    def setUp(self):
        self.empresa = create_test_empresa()

    @override_settings(EVOLUTION_API_URL="http://global.evo:8080")
    def test_effective_api_url_uses_override(self):
        config = WhatsAppConfig(
            empresa=self.empresa,
            instance_name="test-instance",
            api_url="http://custom.evo:9090",
        )
        self.assertEqual(config.effective_api_url, "http://custom.evo:9090")

    @override_settings(EVOLUTION_API_URL="http://global.evo:8080")
    def test_effective_api_url_falls_back_to_settings(self):
        config = WhatsAppConfig(
            empresa=self.empresa,
            instance_name="test-instance",
            api_url="",
        )
        self.assertEqual(config.effective_api_url, "http://global.evo:8080")

    @override_settings(EVOLUTION_API_KEY="global-key")
    def test_effective_api_key_falls_back_to_settings(self):
        config = WhatsAppConfig(
            empresa=self.empresa,
            instance_name="test-instance",
            api_key="",
        )
        self.assertEqual(config.effective_api_key, "global-key")

    def test_unique_instance_name(self):
        empresa_b = create_test_empresa(name="Empresa B", slug="empresa-b")
        WhatsAppConfig.objects.create(
            empresa=self.empresa,
            instance_name="shared-instance",
        )
        with self.assertRaises(IntegrityError):
            WhatsAppConfig.objects.create(
                empresa=empresa_b,
                instance_name="shared-instance",
            )

    def test_str(self):
        config = WhatsAppConfig(empresa=self.empresa, instance_name="inst-a")
        self.assertIn(self.empresa.name, str(config))
        self.assertIn("inst-a", str(config))


# ===========================================================================
# Multi-tenant webhook routing tests
# ===========================================================================


class EvolutionWebhookAutoMultiTenantTests(TransactionTestCase):

    url = reverse("chatbot:evolution_webhook_auto")

    def setUp(self):
        self.empresa_a = create_test_empresa(name="Empresa A", slug="empresa-a-mt")
        self.empresa_b = create_test_empresa(name="Empresa B", slug="empresa-b-mt")
        self.flow_a = _create_active_whatsapp_flow(self.empresa_a)
        self.flow_b = _create_active_whatsapp_flow(self.empresa_b)
        self.config_a = WhatsAppConfig.objects.create(
            empresa=self.empresa_a,
            instance_name="inst-a",
        )
        self.config_b = WhatsAppConfig.objects.create(
            empresa=self.empresa_b,
            instance_name="inst-b",
        )

    def test_routes_to_correct_empresa_by_instance(self):
        """Payload com instance inst-b deve criar sessão no flow da empresa B."""
        payload = _make_evo_payload(phone="5511111110000", text="Oi", instance="inst-b")
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        # Sessão criada no flow da empresa B, não A
        self.assertTrue(
            ChatbotSession.objects.filter(flow=self.flow_b, sender_id="5511111110000").exists()
        )
        self.assertFalse(
            ChatbotSession.objects.filter(flow=self.flow_a, sender_id="5511111110000").exists()
        )

    def test_unknown_instance_returns_404(self):
        payload = _make_evo_payload(instance="nao-existe")
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(ChatbotSession.objects.count(), 0)

    @override_settings(
        EVOLUTION_API_URL="http://global.evo:8080",
        EVOLUTION_API_KEY="global-key",
    )
    @patch("httpx.post")
    def test_sends_reply_with_empresa_config(self, mock_post):
        """EvolutionAPIClient deve usar api_url/api_key da config da empresa."""
        # Config A com override próprio
        self.config_a.api_url = "http://custom-evo:9090"
        self.config_a.api_key = "custom-key"
        self.config_a.save()

        mock_post.return_value = MagicMock(status_code=200)

        payload = _make_evo_payload(phone="5511222220000", text="Oi", instance="inst-a")
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        # httpx.post chamado com URL/chave da config, não do settings global
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("custom-evo:9090", call_args[0][0])
        self.assertEqual(call_args[1]["headers"]["apikey"], "custom-key")

    def test_from_me_ignored_without_config_lookup(self):
        """fromMe=True deve retornar 200 'ignored' sem fazer lookup de WhatsAppConfig."""
        payload = _make_evo_payload(instance="inst-a")
        payload["data"]["key"]["fromMe"] = True

        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ignored")
        self.assertEqual(ChatbotSession.objects.count(), 0)

    def test_no_active_flow_returns_404(self):
        """Empresa tem config mas sem flow ativo → 404."""
        self.flow_b.is_active = False
        self.flow_b.save()

        payload = _make_evo_payload(instance="inst-b")
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

"""RV08 (5.1) — Formulário tradicional descontinuado: fluxo novo nasce no
construtor visual; fluxos legacy continuam funcionando."""
from django.test import TestCase
from django.urls import reverse

from apps.chatbot.models import ChatbotFlow
from apps.core.tests.helpers import create_test_empresa, create_test_user


class VisualOnlyRV08Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-visual")
        self.user = create_test_user("v@t.com", "V", self.empresa)
        self.client.force_login(self.user)

    def test_create_flow_goes_to_visual_builder(self):
        resp = self.client.post(
            reverse("chatbot:flow_create"),
            data={
                "name": "Fluxo Novo",
                "channel": "whatsapp",
                "description": "",
                "welcome_message": "Olá!",
                "fallback_message": "Não entendi.",
                "completion_message": "Obrigado!",
                "trigger_type": "first_message",
                "trigger_keywords": "",
                "priority": "0",
                "cooldown_minutes": "0",
                "inactivity_minutes": "180",
            },
        )
        flow = ChatbotFlow.objects.get(empresa=self.empresa, name="Fluxo Novo")
        self.assertTrue(flow.use_visual_builder)
        self.assertRedirects(
            resp, reverse("chatbot:flow_builder", args=[flow.pk]),
            fetch_redirect_response=False,
        )

    def test_flow_list_has_no_legacy_form_editor_link(self):
        ChatbotFlow.objects.create(empresa=self.empresa, name="Legacy", channel="whatsapp")
        resp = self.client.get(reverse("chatbot:flow_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Editar (formulário)")
        self.assertContains(resp, "Abrir construtor visual")

    def test_legacy_flow_still_opens_in_builder(self):
        legacy = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Legacy", channel="whatsapp",
            use_visual_builder=False,
        )
        resp = self.client.get(reverse("chatbot:flow_builder", args=[legacy.pk]))
        self.assertEqual(resp.status_code, 200)

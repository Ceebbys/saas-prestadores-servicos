"""V2C — Testes dos templates pré-prontos de fluxo."""
import json

from django.test import TestCase
from django.urls import reverse

from apps.chatbot.builder.schemas import get_flow_template, load_flow_templates
from apps.chatbot.builder.services.flow_validator import validate_graph
from apps.chatbot.models import ChatbotFlow, ChatbotFlowVersion
from apps.core.tests.helpers import create_test_empresa, create_test_user


class FlowTemplatesLoaderTests(TestCase):
    def test_load_flow_templates_returns_4_templates(self):
        data = load_flow_templates()
        self.assertEqual(data["schema_version"], 1)
        ids = [t["id"] for t in data["templates"]]
        self.assertIn("captacao_basica", ids)
        self.assertIn("triagem_atendimento", ids)
        self.assertIn("qualificacao_lead", ids)
        self.assertIn("pesquisa_satisfacao", ids)

    def test_get_flow_template_lookup(self):
        t = get_flow_template("captacao_basica")
        self.assertIsNotNone(t)
        self.assertEqual(t["name"], "Captação básica de leads")

    def test_get_unknown_template_returns_none(self):
        self.assertIsNone(get_flow_template("nope"))

    def test_all_templates_pass_validator(self):
        """Garante que os graphs dos templates são todos válidos."""
        from apps.chatbot.builder.services.flow_validator import validate_graph

        for tpl in load_flow_templates()["templates"]:
            result = validate_graph(tpl["graph"], flow=None)
            self.assertTrue(
                result["valid"],
                msg=f"Template '{tpl['id']}' não passa no validator: {result['errors']}",
            )


class FlowTemplatesEndpointsTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # zera contadores de rate limit entre testes
        self.empresa = create_test_empresa()
        self.user = create_test_user("t@t.com", "T", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="T", channel="webchat",
        )
        self.client.force_login(self.user)

    def test_flow_templates_endpoint(self):
        url = reverse("chatbot:flow_templates")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreater(len(data["templates"]), 0)

    def test_apply_template_creates_draft_with_template_graph(self):
        url = reverse("chatbot:builder_apply_template", args=[self.flow.pk])
        resp = self.client.post(
            url,
            data=json.dumps({"template_id": "captacao_basica"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        # Draft existe com nodes do template
        draft = ChatbotFlowVersion.objects.filter(
            flow=self.flow, status="draft",
        ).first()
        self.assertIsNotNone(draft)
        node_ids = [n["id"] for n in draft.graph_json["nodes"]]
        self.assertIn("n_start", node_ids)
        self.assertIn("n_name", node_ids)

    def test_apply_template_unknown_returns_404(self):
        url = reverse("chatbot:builder_apply_template", args=[self.flow.pk])
        resp = self.client.post(
            url,
            data=json.dumps({"template_id": "alien_template"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_apply_template_missing_id_returns_400(self):
        url = reverse("chatbot:builder_apply_template", args=[self.flow.pk])
        resp = self.client.post(url, data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_apply_template_cross_tenant_404(self):
        outra = create_test_empresa(name="O", slug="o-tpl")
        create_test_user("o@t.com", "O", outra)
        flow_o = ChatbotFlow.objects.create(empresa=outra, name="O", channel="webchat")
        url = reverse("chatbot:builder_apply_template", args=[flow_o.pk])
        resp = self.client.post(
            url,
            data=json.dumps({"template_id": "captacao_basica"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

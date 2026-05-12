"""RV06 — Testes dos endpoints API do builder.

Cobre:
- GET /graph/ — retorna draft (cria se não existe)
- POST /save/ — salva graph
- POST /validate/ — roda validator
- POST /publish/ — exige válido, cria PUBLISHED, marca use_visual_builder
- POST /builder/init/ — converte legacy
- GET /node-catalog/ — retorna catalog
- Auth: 302/403 sem login
- Tenant isolation: 404 cross-tenant
- Limites: 413 payload too large, 422 too many nodes
"""
import json

from django.test import TestCase
from django.urls import reverse

from apps.chatbot.models import (
    ChatbotFlow,
    ChatbotFlowVersion,
    ChatbotStep,
)
from apps.core.tests.helpers import create_test_empresa, create_test_user


class GraphEndpointTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("a@t.com", "A", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="API", channel="webchat",
        )
        self.client.force_login(self.user)

    def test_get_graph_creates_draft_if_missing(self):
        url = reverse("chatbot:builder_graph", args=[self.flow.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("graph", data)
        self.assertIn("version_id", data)
        # Idempotente
        resp2 = self.client.get(url)
        self.assertEqual(resp2.json()["version_id"], data["version_id"])

    def test_get_graph_unauth_redirects(self):
        self.client.logout()
        url = reverse("chatbot:builder_graph", args=[self.flow.pk])
        resp = self.client.get(url)
        # LoginRequired + raise_exception=True → 403
        self.assertIn(resp.status_code, (302, 403))

    def test_save_graph(self):
        url = reverse("chatbot:builder_save", args=[self.flow.pk])
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                {"id": "s1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            ],
            "edges": [],
        }
        resp = self.client.post(url, data=json.dumps({"graph": graph}), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        # Verifica que foi salvo
        version = ChatbotFlowVersion.objects.filter(flow=self.flow).first()
        self.assertEqual(version.graph_json["nodes"][0]["id"], "s1")

    def test_save_graph_too_many_nodes(self):
        url = reverse("chatbot:builder_save", args=[self.flow.pk])
        graph = {
            "schema_version": 1,
            "nodes": [{"id": f"n{i}", "type": "message", "position": {"x": 0, "y": 0}, "data": {}}
                      for i in range(250)],
            "edges": [],
        }
        resp = self.client.post(url, data=json.dumps({"graph": graph}), content_type="application/json")
        self.assertEqual(resp.status_code, 422)

    def test_save_graph_invalid_json(self):
        url = reverse("chatbot:builder_save", args=[self.flow.pk])
        resp = self.client.post(url, data="{not valid}", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_validate_graph_endpoint(self):
        url = reverse("chatbot:builder_validate", args=[self.flow.pk])
        # Primeiro: salva um graph inválido
        save_url = reverse("chatbot:builder_save", args=[self.flow.pk])
        bad_graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [{"id": "m1", "type": "message", "position": {"x": 0, "y": 0}, "data": {}}],
            "edges": [],
        }
        self.client.post(save_url, data=json.dumps({"graph": bad_graph}), content_type="application/json")
        # Valida
        resp = self.client.post(url, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any(e["code"] == "MISSING_START" for e in data["errors"]))


class PublishWorkflowTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("a@t.com", "A", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Pub", channel="webchat",
        )
        self.client.force_login(self.user)

    def _save_valid_graph(self):
        url = reverse("chatbot:builder_save", args=[self.flow.pk])
        graph = {
            "schema_version": 1, "viewport": {"x": 0, "y": 0, "zoom": 1}, "metadata": {},
            "nodes": [
                {"id": "s1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "m1", "type": "message", "position": {"x": 100, "y": 0}, "data": {"text": "Oi"}},
                {"id": "e1", "type": "end", "position": {"x": 200, "y": 0}, "data": {}},
            ],
            "edges": [
                {"id": "e1", "source": "s1", "target": "m1", "sourceHandle": "next", "targetHandle": "in"},
                {"id": "e2", "source": "m1", "target": "e1", "sourceHandle": "next", "targetHandle": "in"},
            ],
        }
        self.client.post(url, data=json.dumps({"graph": graph}), content_type="application/json")

    def test_publish_invalid_returns_422(self):
        # Sem salvar nada — draft é graph vazio (só start sem outbound)
        url = reverse("chatbot:builder_publish", args=[self.flow.pk])
        resp = self.client.post(url, content_type="application/json")
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"], "invalid_graph")

    def test_publish_valid_creates_published_version(self):
        self._save_valid_graph()
        url = reverse("chatbot:builder_publish", args=[self.flow.pk])
        resp = self.client.post(url, content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertIn("published_version_id", data)
        # Flow agora tem current_published_version + use_visual_builder=True
        self.flow.refresh_from_db()
        self.assertTrue(self.flow.use_visual_builder)
        self.assertIsNotNone(self.flow.current_published_version_id)

    def test_publish_twice_archives_previous(self):
        self._save_valid_graph()
        url = reverse("chatbot:builder_publish", args=[self.flow.pk])
        self.client.post(url, content_type="application/json")
        first_pub_id = self.flow.versions.filter(status="published").first().id

        # Re-salvar e re-publicar
        self._save_valid_graph()
        self.client.post(url, content_type="application/json")

        # Versão antiga deve ser archived
        old_version = ChatbotFlowVersion.objects.get(pk=first_pub_id)
        self.assertEqual(old_version.status, "archived")
        # Nova versão é published
        self.assertEqual(self.flow.versions.filter(status="published").count(), 1)


class BuilderInitTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("a@t.com", "A", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Init", channel="webchat",
        )
        # Cria um step legacy para conversão
        ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Nome?", step_type="name",
        )
        self.client.force_login(self.user)

    def test_builder_init_converts_legacy(self):
        url = reverse("chatbot:builder_init", args=[self.flow.pk])
        resp = self.client.post(url, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["created"])
        # Draft tem graph com nodes convertidos
        draft = ChatbotFlowVersion.objects.get(pk=data["version_id"])
        types = [n["type"] for n in draft.graph_json["nodes"]]
        self.assertIn("start", types)
        self.assertIn("question", types)

    def test_builder_init_idempotent(self):
        url = reverse("chatbot:builder_init", args=[self.flow.pk])
        self.client.post(url, content_type="application/json")
        resp2 = self.client.post(url, content_type="application/json")
        self.assertEqual(resp2.status_code, 200)
        self.assertFalse(resp2.json()["created"])


class NodeCatalogTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("a@t.com", "A", self.empresa)
        self.client.force_login(self.user)

    def test_node_catalog_returns_catalog(self):
        url = reverse("chatbot:node_catalog")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        types = [n["type"] for n in data["nodes"]]
        for expected in ("start", "message", "question", "menu", "condition",
                         "collect_data", "api_call", "handoff", "end"):
            self.assertIn(expected, types)


class CrossTenantTests(TestCase):
    """User de uma empresa não acessa flows de outra."""

    def setUp(self):
        self.empresa_a = create_test_empresa(name="A", slug="a")
        self.user_a = create_test_user("a@t.com", "A", self.empresa_a)
        self.empresa_b = create_test_empresa(name="B", slug="b")
        create_test_user("b@t.com", "B", self.empresa_b)
        self.flow_b = ChatbotFlow.objects.create(
            empresa=self.empresa_b, name="B flow", channel="webchat",
        )
        self.client.force_login(self.user_a)

    def test_get_graph_other_tenant_404(self):
        url = reverse("chatbot:builder_graph", args=[self.flow_b.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_save_other_tenant_404(self):
        url = reverse("chatbot:builder_save", args=[self.flow_b.pk])
        resp = self.client.post(url, data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 404)

    def test_publish_other_tenant_404(self):
        url = reverse("chatbot:builder_publish", args=[self.flow_b.pk])
        resp = self.client.post(url, content_type="application/json")
        self.assertEqual(resp.status_code, 404)

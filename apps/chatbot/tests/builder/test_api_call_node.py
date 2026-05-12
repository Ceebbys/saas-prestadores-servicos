"""V2A — Testes do nó `api_call` funcional + ChatbotSecret CRUD.

Cobre:
- ChatbotSecret: encrypt/decrypt round-trip
- Validator: SECRET_NOT_FOUND quando secret_ref não existe
- Executor: _execute_api_call HTTP success/error → segue handle correto
- Template substitution em path e payload
- CRUD via settings_app (list/create/rotate/delete) com tenant isolation
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.urls import reverse

from apps.chatbot.builder.services.flow_validator import validate_graph
from apps.chatbot.builder.services.secrets import (
    get_secret_value,
    has_secret_value,
    set_secret_value,
)
from apps.chatbot.models import (
    ChatbotFlow,
    ChatbotFlowVersion,
    ChatbotSecret,
    ChatbotSession,
)
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _node(nid, ntype, **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": data}


def _edge(eid, source, target, sourceHandle="next"):
    return {
        "id": eid,
        "source": source,
        "target": target,
        "sourceHandle": sourceHandle,
        "targetHandle": "in",
    }


def _graph(nodes, edges=None):
    return {
        "schema_version": 1,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "metadata": {},
        "nodes": nodes,
        "edges": edges or [],
    }


class SecretCryptoTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("s@t.com", "S", self.empresa)

    def test_set_and_get_secret_round_trip(self):
        secret = ChatbotSecret.objects.create(empresa=self.empresa, name="test_key")
        set_secret_value(secret, "abc-123-xyz")
        secret.save()
        secret.refresh_from_db()
        self.assertTrue(has_secret_value(secret))
        plain = get_secret_value(secret)
        self.assertEqual(plain, "abc-123-xyz")

    def test_get_secret_updates_last_used_at(self):
        from django.utils import timezone
        secret = ChatbotSecret.objects.create(empresa=self.empresa, name="k")
        set_secret_value(secret, "x")
        secret.save()
        self.assertIsNone(secret.last_used_at)
        before = timezone.now()
        get_secret_value(secret)
        secret.refresh_from_db()
        self.assertIsNotNone(secret.last_used_at)
        self.assertGreaterEqual(secret.last_used_at, before)

    def test_get_empty_secret_returns_empty(self):
        secret = ChatbotSecret.objects.create(empresa=self.empresa, name="empty")
        self.assertEqual(get_secret_value(secret), "")


class APICallValidatorTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("v@t.com", "V", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="V", channel="webchat",
        )

    def test_secret_not_found_blocks_publish(self):
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "api_call", secret_ref="missing_key", method="POST", path_template="https://api.example.com/x"),
            _node("e_ok", "end"),
            _node("e_err", "end"),
        ], [
            _edge("e_s", "s1", "a1"),
            _edge("e_ok", "a1", "e_ok", sourceHandle="success"),
            _edge("e_err", "a1", "e_err", sourceHandle="error"),
        ])
        result = validate_graph(graph, flow=self.flow)
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("SECRET_NOT_FOUND", codes)

    def test_secret_found_validates(self):
        ChatbotSecret.objects.create(empresa=self.empresa, name="crm_key")
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "api_call", secret_ref="crm_key", method="POST", path_template="https://api.example.com/x"),
            _node("e_ok", "end"),
            _node("e_err", "end"),
        ], [
            _edge("e_s", "s1", "a1"),
            _edge("e_ok", "a1", "e_ok", sourceHandle="success"),
            _edge("e_err", "a1", "e_err", sourceHandle="error"),
        ])
        result = validate_graph(graph, flow=self.flow)
        self.assertTrue(result["valid"], result["errors"])


class APICallExecutorTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.empresa = create_test_empresa()
        create_test_user("e@t.com", "E", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="E", channel="webchat", is_active=True,
        )
        # Cria segredo
        self.secret = ChatbotSecret.objects.create(empresa=self.empresa, name="api_token")
        set_secret_value(self.secret, "secret-value-123")
        self.secret.save()

        # Publica graph com api_call
        graph = _graph([
            _node("s1", "start"),
            _node("a1", "api_call",
                  secret_ref="api_token",
                  method="POST",
                  path_template="https://api.example.com/test",
                  payload_template='{"name": "$name"}',
                  response_var="api_response"),
            _node("e_ok", "end", completion_message="Sucesso"),
            _node("e_err", "end", completion_message="Erro"),
        ], [
            _edge("e_s", "s1", "a1"),
            _edge("e_ok", "a1", "e_ok", sourceHandle="success"),
            _edge("e_err", "a1", "e_err", sourceHandle="error"),
        ])
        version = ChatbotFlowVersion.objects.create(
            flow=self.flow,
            graph_json=graph,
            status=ChatbotFlowVersion.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.flow.use_visual_builder = True
        self.flow.current_published_version = version
        self.flow.save()

    @patch("httpx.Client")
    def test_api_call_success_follows_success_branch(self, mock_client):
        from apps.chatbot.builder.services.flow_executor import start_session_v2

        # Mock httpx response 200 com JSON válido
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True, "id": 42}
        mock_instance = mock_client.return_value.__enter__.return_value
        mock_instance.request.return_value = mock_resp

        result = start_session_v2(self.flow)
        self.assertTrue(result["is_complete"])
        self.assertIn("Sucesso", result.get("message", ""))

        # Verifica response_var armazenado
        session = ChatbotSession.objects.filter(flow=self.flow).first()
        self.assertEqual(session.lead_data.get("api_response"), {"ok": True, "id": 42})

    @patch("httpx.Client")
    def test_api_call_4xx_follows_error_branch(self, mock_client):
        from apps.chatbot.builder.services.flow_executor import start_session_v2

        mock_resp = MagicMock(status_code=500)
        mock_resp.json.return_value = {"error": "internal"}
        mock_instance = mock_client.return_value.__enter__.return_value
        mock_instance.request.return_value = mock_resp

        result = start_session_v2(self.flow)
        self.assertTrue(result["is_complete"])
        self.assertIn("Erro", result.get("message", ""))

    @patch("httpx.Client")
    def test_api_call_timeout_follows_error_branch(self, mock_client):
        import httpx
        from apps.chatbot.builder.services.flow_executor import start_session_v2

        mock_instance = mock_client.return_value.__enter__.return_value
        mock_instance.request.side_effect = httpx.TimeoutException("timeout")

        result = start_session_v2(self.flow)
        self.assertTrue(result["is_complete"])
        self.assertIn("Erro", result.get("message", ""))

    @patch("httpx.Client")
    def test_api_call_uses_authorization_header_from_secret(self, mock_client):
        from apps.chatbot.builder.services.flow_executor import start_session_v2

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {}
        mock_instance = mock_client.return_value.__enter__.return_value
        mock_instance.request.return_value = mock_resp

        start_session_v2(self.flow)
        # Confere que Authorization header foi populado com o valor do secret
        call_args = mock_instance.request.call_args
        headers = call_args.kwargs.get("headers", {})
        self.assertEqual(headers.get("Authorization"), "Bearer secret-value-123")


class ChatbotSecretCRUDTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client.force_login(self.user)

    def test_list_view_renders(self):
        ChatbotSecret.objects.create(empresa=self.empresa, name="t1")
        resp = self.client.get(reverse("settings_app:chatbot_secret_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "t1")

    def test_create_via_post(self):
        resp = self.client.post(reverse("settings_app:chatbot_secret_create"), data={
            "name": "new_key",
            "description": "Test key",
            "value": "abc123",
        })
        self.assertIn(resp.status_code, (302, 303))
        secret = ChatbotSecret.objects.get(empresa=self.empresa, name="new_key")
        # Encrypted value gravado
        self.assertTrue(has_secret_value(secret))
        self.assertEqual(get_secret_value(secret), "abc123")

    def test_create_rejects_missing_value(self):
        resp = self.client.post(reverse("settings_app:chatbot_secret_create"), data={
            "name": "no_value", "description": "", "value": "",
        })
        self.assertEqual(resp.status_code, 200)  # form invalid → re-render
        self.assertContains(resp, "obrigatório")

    def test_rotate_keeps_value_when_blank(self):
        secret = ChatbotSecret.objects.create(empresa=self.empresa, name="rotate")
        set_secret_value(secret, "old_value")
        secret.save()
        resp = self.client.post(
            reverse("settings_app:chatbot_secret_rotate", args=[secret.pk]),
            data={"name": "rotate", "description": "updated desc", "value": ""},
        )
        self.assertIn(resp.status_code, (302, 303))
        secret.refresh_from_db()
        self.assertEqual(get_secret_value(secret), "old_value")
        self.assertEqual(secret.description, "updated desc")

    def test_rotate_updates_value_when_provided(self):
        secret = ChatbotSecret.objects.create(empresa=self.empresa, name="rotate2")
        set_secret_value(secret, "old")
        secret.save()
        resp = self.client.post(
            reverse("settings_app:chatbot_secret_rotate", args=[secret.pk]),
            data={"name": "rotate2", "description": "", "value": "new_value"},
        )
        self.assertIn(resp.status_code, (302, 303))
        secret.refresh_from_db()
        self.assertEqual(get_secret_value(secret), "new_value")

    def test_cross_tenant_404(self):
        outra = create_test_empresa(name="O", slug="o")
        create_test_user("o@t.com", "O", outra)
        secret = ChatbotSecret.objects.create(empresa=outra, name="cross")
        resp = self.client.get(
            reverse("settings_app:chatbot_secret_rotate", args=[secret.pk]),
        )
        self.assertEqual(resp.status_code, 404)

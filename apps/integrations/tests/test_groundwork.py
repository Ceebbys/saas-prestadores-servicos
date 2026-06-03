"""RV07 — Groundwork de integrações: tudo aditivo, sem chamadas externas."""
from django.test import TestCase
from django.urls import reverse

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.integrations import services
from apps.integrations.assistant import get_assistant_service
from apps.integrations.models import IntegrationConnection
from apps.operations.models import WorkOrder


class IntegrationsGroundworkTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-integ")
        self.user = create_test_user("i@t.com", "I", self.empresa)

    def test_token_encryption_roundtrip(self):
        conn = IntegrationConnection.objects.create(empresa=self.empresa, provider="google")
        conn.set_access_token("secret-access")
        conn.set_refresh_token("secret-refresh")
        conn.save()
        conn.refresh_from_db()
        self.assertEqual(conn.get_access_token(), "secret-access")
        self.assertEqual(conn.get_refresh_token(), "secret-refresh")
        # cifrado não vaza o texto em claro
        self.assertNotIn("secret-access", conn.access_token_encrypted)

    def test_provider_none_when_not_connected(self):
        self.assertIsNone(services.get_calendar_provider(self.empresa))
        self.assertIsNone(services.get_storage_provider(self.empresa))

    def test_convenience_stub_returns_not_configured(self):
        wo = WorkOrder.objects.create(empresa=self.empresa, title="OS")
        result = services.create_workorder_folder(wo)
        self.assertFalse(result.get("integration_ready"))
        self.assertEqual(result.get("status"), "not_configured")

    def test_assistant_disabled_returns_none(self):
        self.assertIsNone(get_assistant_service(self.empresa))

    def test_settings_integrations_page_renders(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("settings_app:integrations"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Não conectado")

"""RV07 (Epic 7) — Integração Google real (OAuth + Calendar + Drive).

Tudo com httpx mockado — nenhum teste toca a rede. Cobre: OAuth (auth URL,
exchange, refresh, ensure_fresh), providers (Calendar/Drive + retry 401),
views (connect/callback/disconnect + state CSRF), o hook de follow-up e a tela.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead
from apps.integrations import oauth, services
from apps.integrations.models import IntegrationConnection
from apps.integrations.providers.base import ProviderResult
from apps.integrations.providers.google import (
    GoogleCalendarProvider,
    GoogleStorageProvider,
)

GOOGLE_SETTINGS = dict(
    GOOGLE_OAUTH_CLIENT_ID="test-client-id",
    GOOGLE_OAUTH_CLIENT_SECRET="test-secret",
    GOOGLE_OAUTH_REDIRECT_URI="https://app.test/integrations/google/callback/",
)


class FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def _connected_conn(empresa, *, expired=False):
    conn = IntegrationConnection.objects.create(
        empresa=empresa,
        provider=IntegrationConnection.Provider.GOOGLE,
        status=IntegrationConnection.Status.CONNECTED,
        scopes=["calendar", "drive"],
    )
    conn.set_access_token("access-tok")
    conn.set_refresh_token("refresh-tok")
    conn.expires_at = timezone.now() + (
        timedelta(hours=-1) if expired else timedelta(hours=1)
    )
    conn.save()
    return conn


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------
@override_settings(**GOOGLE_SETTINGS)
class OAuthHelperTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="g-oauth")

    def test_is_configured(self):
        self.assertTrue(oauth.is_configured())

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_CLIENT_SECRET="")
    def test_not_configured_when_missing(self):
        self.assertFalse(oauth.is_configured())

    def test_authorization_url_has_required_params(self):
        url = oauth.authorization_url(state="xyz", capabilities=["calendar", "drive"])
        self.assertIn("accounts.google.com", url)
        self.assertIn("client_id=test-client-id", url)
        self.assertIn("state=xyz", url)
        self.assertIn("access_type=offline", url)
        self.assertIn("calendar.events", url)
        self.assertIn("drive.file", url)

    @patch("httpx.post")
    def test_exchange_code(self, mock_post):
        mock_post.return_value = FakeResp(200, {"access_token": "at", "expires_in": 3600})
        token = oauth.exchange_code("the-code")
        self.assertEqual(token["access_token"], "at")
        # postou no endpoint de token com grant_type correto
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["grant_type"], "authorization_code")

    @patch("httpx.post")
    def test_exchange_code_error_raises(self, mock_post):
        mock_post.return_value = FakeResp(400, text="bad")
        with self.assertRaises(oauth.OAuthError):
            oauth.exchange_code("bad-code")

    @patch("httpx.post")
    def test_refresh_updates_and_saves(self, mock_post):
        conn = _connected_conn(self.empresa, expired=True)
        mock_post.return_value = FakeResp(200, {"access_token": "new-at", "expires_in": 3600})
        new_token = oauth.refresh_access_token(conn)
        self.assertEqual(new_token, "new-at")
        conn.refresh_from_db()
        self.assertEqual(conn.get_access_token(), "new-at")
        self.assertGreater(conn.expires_at, timezone.now())

    @patch("httpx.post")
    def test_ensure_fresh_skips_refresh_when_valid(self, mock_post):
        conn = _connected_conn(self.empresa)  # expira em 1h
        self.assertEqual(oauth.ensure_fresh(conn), "access-tok")
        mock_post.assert_not_called()

    @patch("httpx.post")
    def test_ensure_fresh_refreshes_when_expired(self, mock_post):
        conn = _connected_conn(self.empresa, expired=True)
        mock_post.return_value = FakeResp(200, {"access_token": "fresh", "expires_in": 3600})
        self.assertEqual(oauth.ensure_fresh(conn), "fresh")
        mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# Providers (Calendar / Drive)
# ---------------------------------------------------------------------------
@override_settings(**GOOGLE_SETTINGS)
class GoogleProviderTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="g-prov")
        self.conn = _connected_conn(self.empresa)

    @patch("httpx.request")
    def test_calendar_create_event_ok(self, mock_req):
        mock_req.return_value = FakeResp(200, {"id": "evt1", "htmlLink": "http://e"})
        provider = GoogleCalendarProvider(self.conn)
        res = provider.create_event(
            title="Reunião", start=timezone.now(), end=timezone.now(),
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["event_id"], "evt1")
        method, url = mock_req.call_args[0][:2]
        self.assertEqual(method, "POST")
        self.assertIn("calendars/primary/events", url)

    @patch("httpx.request")
    def test_calendar_create_event_http_error(self, mock_req):
        mock_req.return_value = FakeResp(500, text="boom")
        provider = GoogleCalendarProvider(self.conn)
        res = provider.create_event(title="x", start=timezone.now(), end=timezone.now())
        self.assertEqual(res["status"], "error")
        self.conn.refresh_from_db()
        self.assertIn("500", self.conn.last_error)

    @patch("httpx.post")
    @patch("httpx.request")
    def test_calendar_retries_once_on_401(self, mock_req, mock_post):
        # 1ª chamada 401 → refresh (httpx.post) → 2ª chamada 200
        mock_req.side_effect = [FakeResp(401, text="unauth"), FakeResp(200, {"id": "e2"})]
        mock_post.return_value = FakeResp(200, {"access_token": "new", "expires_in": 3600})
        provider = GoogleCalendarProvider(self.conn)
        res = provider.create_event(title="x", start=timezone.now(), end=timezone.now())
        self.assertEqual(res["status"], "ok")
        self.assertEqual(mock_req.call_count, 2)
        mock_post.assert_called_once()

    @patch("httpx.request")
    def test_drive_upload_file_ok(self, mock_req):
        mock_req.return_value = FakeResp(
            200, {"id": "f1", "name": "a.pdf", "webViewLink": "http://d"},
        )
        provider = GoogleStorageProvider(self.conn)
        res = provider.upload_file(
            folder_id="fold", filename="a.pdf", content=b"PDFDATA",
            mime="application/pdf",
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["file_id"], "f1")
        method, url = mock_req.call_args[0][:2]
        kwargs = mock_req.call_args[1]
        self.assertEqual(method, "POST")
        self.assertIn("upload/drive/v3/files", url)
        self.assertEqual(kwargs["params"]["uploadType"], "multipart")
        self.assertIn(b"PDFDATA", kwargs["content"])  # bytes embutidos no corpo

    @patch("httpx.request")
    def test_drive_create_folder_ok(self, mock_req):
        mock_req.return_value = FakeResp(200, {"id": "fold1", "name": "Projeto"})
        provider = GoogleStorageProvider(self.conn)
        res = provider.create_folder(name="Projeto")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["file_id"], "fold1")


# ---------------------------------------------------------------------------
# Views (connect / callback / disconnect)
# ---------------------------------------------------------------------------
@override_settings(**GOOGLE_SETTINGS)
class OAuthViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="g-views")
        self.user = create_test_user("v@t.com", "V", self.empresa)
        self.client.force_login(self.user)

    def test_connect_redirects_to_google(self):
        resp = self.client.get(reverse("integrations:google_connect"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("accounts.google.com", resp["Location"])
        self.assertIn("google_oauth", self.client.session)

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_CLIENT_SECRET="")
    def test_connect_blocked_when_not_configured(self):
        resp = self.client.get(reverse("integrations:google_connect"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("settings_app:integrations"))
        self.assertNotIn("google_oauth", self.client.session)

    def test_callback_success_creates_connection(self):
        session = self.client.session
        session["google_oauth"] = {
            "state": "st4te", "empresa_id": self.empresa.pk,
            "capabilities": ["calendar", "drive"],
        }
        session.save()
        with patch.object(
            oauth, "exchange_code",
            return_value={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
        ), patch.object(oauth, "fetch_userinfo", return_value={"email": "u@gmail.com"}):
            resp = self.client.get(
                reverse("integrations:google_callback"),
                {"state": "st4te", "code": "auth-code"},
            )
        self.assertEqual(resp.status_code, 302)
        conn = IntegrationConnection.objects.get(
            empresa=self.empresa, provider="google",
        )
        self.assertTrue(conn.is_connected)
        self.assertEqual(conn.account_email, "u@gmail.com")
        self.assertEqual(conn.get_access_token(), "at")
        self.assertEqual(conn.get_refresh_token(), "rt")
        self.assertEqual(set(conn.scopes), {"calendar", "drive"})
        # state consumido
        self.assertNotIn("google_oauth", self.client.session)

    def test_callback_state_mismatch_rejected(self):
        session = self.client.session
        session["google_oauth"] = {
            "state": "real", "empresa_id": self.empresa.pk, "capabilities": [],
        }
        session.save()
        resp = self.client.get(
            reverse("integrations:google_callback"),
            {"state": "forged", "code": "x"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            IntegrationConnection.objects.filter(
                empresa=self.empresa, status="connected",
            ).exists()
        )

    def test_disconnect_clears_tokens(self):
        conn = _connected_conn(self.empresa)
        with patch.object(oauth, "revoke") as mock_revoke:
            resp = self.client.post(
                reverse("integrations:disconnect", args=["google"]),
            )
        self.assertEqual(resp.status_code, 302)
        mock_revoke.assert_called_once()
        conn.refresh_from_db()
        self.assertFalse(conn.is_connected)
        self.assertEqual(conn.access_token_encrypted, "")
        self.assertEqual(conn.refresh_token_encrypted, "")
        self.assertEqual(conn.scopes, [])


# ---------------------------------------------------------------------------
# Hook de follow-up + tela de Configurações
# ---------------------------------------------------------------------------
class FollowupHookAndPageTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="g-hook")
        self.user = create_test_user("h@t.com", "H", self.empresa)

    def test_followup_hook_no_connection_is_noop(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Lead Sem Integ")
        res = services.create_calendar_event_for_followup(
            lead, when=timezone.now(), title="Follow-up",
        )
        self.assertFalse(res.get("integration_ready"))
        self.assertEqual(res.get("status"), "not_configured")

    def test_followup_hook_with_connection_calls_provider(self):
        _connected_conn(self.empresa)
        lead = Lead.objects.create(empresa=self.empresa, name="Lead Com Integ")
        with patch.object(
            GoogleCalendarProvider, "create_event",
            return_value=ProviderResult(status="ok", integration_ready=True),
        ) as mock_ce:
            res = services.create_calendar_event_for_followup(
                lead, when=timezone.now(), title="Follow-up",
            )
        mock_ce.assert_called_once()
        self.assertEqual(res["status"], "ok")
        # evento de 30 min (end > start)
        _, kwargs = mock_ce.call_args
        self.assertGreater(kwargs["end"], kwargs["start"])

    @override_settings(**GOOGLE_SETTINGS)
    def test_page_shows_connect_when_configured(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("settings_app:integrations"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Conectar")
        self.assertContains(resp, reverse("integrations:google_connect"))

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_CLIENT_SECRET="")
    def test_page_shows_configure_when_not_configured(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("settings_app:integrations"))
        self.assertContains(resp, "Configurar credenciais")

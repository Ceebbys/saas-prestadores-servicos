"""End-to-end tests for the password reset flow."""

import re

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.tests.helpers import create_test_empresa, create_test_user


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="ServiçoPro <no-reply@example.com>",
)
class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user(
            "reset@test.com", "Reset User", self.empresa, password="OldPass123!"
        )

    def test_login_page_shows_forgot_password_link(self):
        resp = self.client.get(reverse("accounts:login"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("accounts:password_reset"))

    def test_password_reset_form_renders(self):
        resp = self.client.get(reverse("accounts:password_reset"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Recuperar senha")

    def test_password_reset_sends_email_for_existing_user(self):
        resp = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "reset@test.com"},
        )
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("reset@test.com", message.to)
        self.assertIn("ServiçoPro", message.subject)
        # Plain-text body must contain the reset link
        self.assertIn("password-reset/confirm/", message.body)

    def test_password_reset_email_is_multipart_html(self):
        """Email should ship both plain text and HTML versions."""
        self.client.post(
            reverse("accounts:password_reset"),
            {"email": "reset@test.com"},
        )
        message = mail.outbox[0]
        # alternatives is a list of (content, mimetype) tuples
        self.assertTrue(message.alternatives, "missing HTML alternative")
        html_body, mimetype = message.alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("<!DOCTYPE html>", html_body)
        self.assertIn("Redefinir minha senha", html_body)
        self.assertIn("password-reset/confirm/", html_body)
        self.assertIn("ServiçoPro", html_body)

    def test_password_reset_does_not_leak_unknown_email(self):
        # Django still redirects to "done" even when the email is not found
        # (avoids account enumeration). No email should be sent.
        resp = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "notfound@nope.com"},
        )
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_full_reset_cycle(self):
        # Trigger reset
        self.client.post(
            reverse("accounts:password_reset"),
            {"email": "reset@test.com"},
        )
        message = mail.outbox[0]
        match = re.search(
            r"password-reset/confirm/(?P<uidb64>[^/]+)/(?P<token>[^/\s]+)/",
            message.body,
        )
        self.assertIsNotNone(match, "reset link missing in email body")
        confirm_url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": match.group("uidb64"), "token": match.group("token")},
        )

        # Following the email link redirects to a session-stored "set-password" URL
        resp = self.client.get(confirm_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Definir nova senha")

        # Submit the new password against the final URL chain
        new_password = "BrandNewPass456!"
        # The form is posted to the final URL in resp.redirect_chain[-1]
        final_url = resp.redirect_chain[-1][0]
        resp_post = self.client.post(
            final_url,
            {"new_password1": new_password, "new_password2": new_password},
        )
        self.assertRedirects(resp_post, reverse("accounts:password_reset_complete"))

        # Old password no longer works, new password does
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password("OldPass123!"))
        self.assertTrue(self.user.check_password(new_password))

    def test_invalid_token_shows_error_page(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        resp = self.client.get(
            reverse(
                "accounts:password_reset_confirm",
                kwargs={"uidb64": uid, "token": "definitely-not-a-token"},
            )
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Link inválido ou expirado")

    def test_reset_complete_page_renders(self):
        resp = self.client.get(reverse("accounts:password_reset_complete"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Senha redefinida com sucesso")

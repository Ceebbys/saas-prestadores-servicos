"""RV07 (6.2) — Preferências de notificação por usuário.

Cobre:
- modelo NotificationPreference.is_muted (normalização + SYSTEM sempre on)
- notify() respeita mute (não cria) e o canal web_push
- digest diário pula quem desligou o e-mail
- tela de Configurações → Notificações (GET render + POST salva opt-out)
"""
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse

from apps.communications.models import Notification, NotificationPreference
from apps.communications.notifications import notify
from apps.communications.tasks import send_daily_digest
from apps.core.tests.helpers import create_test_empresa, create_test_user


class NotificationPreferenceModelTests(TestCase):
    def test_is_muted_normalizes_enum_and_string(self):
        pref = NotificationPreference(muted_types=["proposal_sent"])
        # aceita tanto o membro do enum quanto a string crua
        self.assertTrue(pref.is_muted(Notification.Type.PROPOSAL_SENT))
        self.assertTrue(pref.is_muted("proposal_sent"))
        self.assertFalse(pref.is_muted(Notification.Type.LEAD_MOVED))
        self.assertFalse(pref.is_muted("lead_moved"))

    def test_system_type_never_muted(self):
        # mesmo listado em muted_types, SYSTEM nunca é silenciado.
        pref = NotificationPreference(muted_types=["system"])
        self.assertFalse(pref.is_muted(Notification.Type.SYSTEM))
        self.assertFalse(pref.is_muted("system"))

    def test_empty_preference_mutes_nothing(self):
        pref = NotificationPreference()
        self.assertFalse(pref.is_muted(Notification.Type.PROPOSAL_SENT))


class NotifyRespectsPreferencesTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="notify-pref")
        self.user = create_test_user("np@t.com", "NP", self.empresa)

    def test_muted_type_is_not_created(self):
        NotificationPreference.objects.create(
            user=self.user, muted_types=["proposal_sent"],
        )
        result = notify(
            self.user, type=Notification.Type.PROPOSAL_SENT,
            title="x", empresa=self.empresa,
        )
        self.assertIsNone(result)
        self.assertFalse(
            Notification.objects.filter(
                user=self.user, type=Notification.Type.PROPOSAL_SENT,
            ).exists()
        )

    def test_unmuted_type_is_created(self):
        NotificationPreference.objects.create(
            user=self.user, muted_types=["proposal_sent"],
        )
        result = notify(
            self.user, type=Notification.Type.LEAD_MOVED,
            title="x", empresa=self.empresa,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.type, Notification.Type.LEAD_MOVED)

    def test_no_preference_row_creates_everything(self):
        # usuário sem registro = tudo ligado (compat com comportamento antigo)
        result = notify(
            self.user, type=Notification.Type.PROPOSAL_SENT,
            title="x", empresa=self.empresa,
        )
        self.assertIsNotNone(result)

    def test_system_type_created_even_if_listed(self):
        NotificationPreference.objects.create(
            user=self.user, muted_types=["system"],
        )
        result = notify(
            self.user, type=Notification.Type.SYSTEM,
            title="x", empresa=self.empresa,
        )
        self.assertIsNotNone(result)

    @patch("apps.communications.notifications._send_web_push")
    def test_web_push_disabled_skips_push(self, mock_push):
        NotificationPreference.objects.create(user=self.user, web_push=False)
        notify(
            self.user, type=Notification.Type.LEAD_MOVED,
            title="x", empresa=self.empresa,
        )
        mock_push.assert_not_called()

    @patch("apps.communications.notifications._send_web_push")
    def test_web_push_enabled_calls_push(self, mock_push):
        # sem pref → default ligado
        notify(
            self.user, type=Notification.Type.LEAD_MOVED,
            title="x", empresa=self.empresa,
        )
        mock_push.assert_called_once()


class DailyDigestRespectsPreferenceTests(TestCase):
    def test_digest_skips_user_who_disabled_email(self):
        empresa = create_test_empresa(slug="digest")
        u_on = create_test_user("on@t.com", "On", empresa)
        u_off = create_test_user("off@t.com", "Off", empresa)
        NotificationPreference.objects.create(user=u_off, email_digest=False)

        # notificação não lida para ambos (tipo não silenciado)
        notify(u_on, type=Notification.Type.LEAD_MOVED, title="x", empresa=empresa)
        notify(u_off, type=Notification.Type.LEAD_MOVED, title="x", empresa=empresa)

        send_daily_digest()

        recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertIn("on@t.com", recipients)
        self.assertNotIn("off@t.com", recipients)


class NotificationSettingsViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="notif-settings")
        self.user = create_test_user("set@t.com", "Set", self.empresa)
        self.client = Client()
        self.client.force_login(self.user)
        self.url = reverse("settings_app:notification_settings")

    def test_get_renders_form(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Resumo diário por e-mail")
        self.assertContains(resp, "Proposta enviada")
        self.assertContains(resp, "Ver central de notificações")

    def test_post_saves_optout_and_channels(self):
        from apps.settings_app.forms import NotificationPreferenceForm

        # email ligado, web_push desligado (ausente), todos os eventos
        # marcados EXCETO proposal_sent (que deve virar muted).
        data = {"email_digest": "on"}
        for v in NotificationPreferenceForm.all_event_values():
            if v != "proposal_sent":
                data[f"evt_{v}"] = "on"

        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 302)

        pref = NotificationPreference.objects.get(user=self.user)
        self.assertTrue(pref.email_digest)
        self.assertFalse(pref.web_push)  # não enviado ⇒ desmarcado
        self.assertIn("proposal_sent", pref.muted_types)
        self.assertNotIn("lead_moved", pref.muted_types)
        # SYSTEM nunca entra na lista (não é campo do form)
        self.assertNotIn("system", pref.muted_types)

    def test_post_is_idempotent_get_or_create(self):
        # 1º POST cria, 2º atualiza a MESMA linha (OneToOne)
        self.client.post(self.url, {"email_digest": "on"})
        self.client.post(self.url, {})
        self.assertEqual(
            NotificationPreference.objects.filter(user=self.user).count(), 1,
        )
        pref = NotificationPreference.objects.get(user=self.user)
        self.assertFalse(pref.email_digest)  # 2º POST sem o campo ⇒ False

"""RV07 (pente fino) — A sininha/lista de notificações NÃO pode vazar
notificações de outro tenant para um usuário membro de 2+ empresas.
"""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Membership
from apps.communications.models import Notification
from apps.core.tests.helpers import create_test_empresa, create_test_user


class NotificationTenantScopeTests(TestCase):
    def setUp(self):
        self.empresa_a = create_test_empresa(slug="scope-a")
        self.empresa_b = create_test_empresa(name="Empresa B", slug="scope-b")
        # Usuário é membro de A (via helper) E de B.
        self.user = create_test_user("multi@t.com", "Multi", self.empresa_a)
        Membership.objects.create(
            user=self.user, empresa=self.empresa_b,
            role=Membership.Role.OWNER, is_active=True,
        )
        # Notificação pertencente à Empresa B (outro tenant).
        self.notif_b = Notification.objects.create(
            user=self.user, empresa=self.empresa_b,
            type=Notification.Type.LEAD_MOVED, title="SEGREDO B",
        )
        # Notificação da Empresa A (deve aparecer) + uma pessoal (empresa nula).
        self.notif_a = Notification.objects.create(
            user=self.user, empresa=self.empresa_a,
            type=Notification.Type.LEAD_MOVED, title="Visível A",
        )
        self.notif_sys = Notification.objects.create(
            user=self.user, empresa=None,
            type=Notification.Type.SYSTEM, title="Pessoal",
        )
        # Contexto ativo = Empresa A
        self.user.active_empresa = self.empresa_a
        self.user.save(update_fields=["active_empresa"])
        self.client.force_login(self.user)

    def test_dropdown_excludes_other_tenant(self):
        resp = self.client.get(reverse("communications:notification_dropdown"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "SEGREDO B")
        self.assertContains(resp, "Visível A")
        self.assertContains(resp, "Pessoal")

    def test_list_excludes_other_tenant(self):
        resp = self.client.get(reverse("communications:notification_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "SEGREDO B")
        self.assertContains(resp, "Visível A")

    def test_mark_all_read_does_not_touch_other_tenant(self):
        self.client.post(reverse("communications:notification_mark_all_read"))
        self.notif_b.refresh_from_db()
        self.notif_a.refresh_from_db()
        # B continua não-lida (não foi tocada); A foi marcada.
        self.assertIsNone(self.notif_b.read_at)
        self.assertIsNotNone(self.notif_a.read_at)

    def test_mark_read_other_tenant_404(self):
        resp = self.client.post(
            reverse("communications:notification_mark_read", args=[self.notif_b.pk])
        )
        self.assertEqual(resp.status_code, 404)
        self.notif_b.refresh_from_db()
        self.assertIsNone(self.notif_b.read_at)

    def test_badge_count_excludes_other_tenant(self):
        # context processor: badge conta só A (1) + pessoal (1) = 2, não B.
        resp = self.client.get(reverse("dashboard:index"))
        self.assertEqual(resp.context["notifications_unread_count"], 2)

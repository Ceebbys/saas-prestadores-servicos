"""Testes das views de notificação + Web Push subscribe + email digest."""
from __future__ import annotations

import json

from django.test import TestCase
from django.urls import reverse

from apps.communications.models import (
    Conversation,
    ConversationMessage,
    Notification,
    PushSubscription,
)
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead


class NotificationViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("u@t.com", "U", self.empresa)
        self.client.force_login(self.user)
        # Cria 3 notificações para o user
        for i in range(3):
            Notification.objects.create(
                user=self.user, empresa=self.empresa,
                type=Notification.Type.SYSTEM,
                title=f"Notif {i}", body=f"body {i}",
            )

    def test_list_view(self):
        resp = self.client.get(reverse("communications:notification_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Notif 0")
        self.assertContains(resp, "Notif 2")

    def test_dropdown_view_returns_partial(self):
        resp = self.client.get(reverse("communications:notification_dropdown"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Notif 0")
        self.assertNotContains(resp, "<html")  # é partial, não shell

    def test_mark_one_read(self):
        n = self.user.notifications.first()
        self.assertIsNone(n.read_at)
        resp = self.client.post(reverse(
            "communications:notification_mark_read", args=[n.pk],
        ))
        self.assertEqual(resp.status_code, 204)
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)

    def test_mark_one_read_cross_user_404(self):
        # Outra empresa + outro user
        other_e = create_test_empresa("B", "b")
        other_u = create_test_user("o@t.com", "O", other_e)
        n2 = Notification.objects.create(
            user=other_u, empresa=other_e,
            type=Notification.Type.SYSTEM, title="not mine",
        )
        resp = self.client.post(reverse(
            "communications:notification_mark_read", args=[n2.pk],
        ))
        self.assertEqual(resp.status_code, 404)

    def test_mark_all_read(self):
        self.assertEqual(
            Notification.objects.filter(user=self.user, read_at__isnull=True).count(),
            3,
        )
        resp = self.client.post(reverse(
            "communications:notification_mark_all_read",
        ))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data["updated"], 3)
        self.assertEqual(
            Notification.objects.filter(user=self.user, read_at__isnull=True).count(),
            0,
        )

    def test_unread_only_filter(self):
        # Marca uma como lida
        n = self.user.notifications.first()
        n.mark_read()
        resp = self.client.get(
            reverse("communications:notification_list") + "?unread_only=1",
        )
        # 2 não lidas devem aparecer; a lida não
        self.assertEqual(resp.context["notifications"].count(), 2)


class PushSubscriptionViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("p@t.com", "P", self.empresa)
        self.client.force_login(self.user)

    def test_vapid_public_key_disabled_by_default(self):
        from django.test import override_settings
        with override_settings(VAPID_PUBLIC_KEY=""):
            resp = self.client.get(reverse(
                "communications:vapid_public_key",
            ))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content), {"enabled": False})

    def test_vapid_public_key_enabled(self):
        from django.test import override_settings
        with override_settings(VAPID_PUBLIC_KEY="testpubkey"):
            resp = self.client.get(reverse(
                "communications:vapid_public_key",
            ))
        data = json.loads(resp.content)
        self.assertTrue(data["enabled"])
        self.assertEqual(data["publicKey"], "testpubkey")

    def test_push_subscribe_creates_row(self):
        body = json.dumps({
            "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
            "keys": {"p256dh": "k1", "auth": "a1"},
        })
        resp = self.client.post(
            reverse("communications:push_subscribe"),
            data=body, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)
        sub = PushSubscription.objects.first()
        self.assertEqual(sub.user, self.user)
        self.assertEqual(sub.p256dh, "k1")

    def test_push_subscribe_upsert(self):
        body = json.dumps({
            "endpoint": "https://fcm.googleapis.com/fcm/send/x",
            "keys": {"p256dh": "k1", "auth": "a1"},
        })
        self.client.post(
            reverse("communications:push_subscribe"),
            data=body, content_type="application/json",
        )
        # Mesmo endpoint, novas chaves
        body2 = json.dumps({
            "endpoint": "https://fcm.googleapis.com/fcm/send/x",
            "keys": {"p256dh": "k2", "auth": "a2"},
        })
        self.client.post(
            reverse("communications:push_subscribe"),
            data=body2, content_type="application/json",
        )
        # Sem duplicação
        self.assertEqual(PushSubscription.objects.count(), 1)
        sub = PushSubscription.objects.first()
        self.assertEqual(sub.p256dh, "k2")

    def test_push_subscribe_invalid_json(self):
        resp = self.client.post(
            reverse("communications:push_subscribe"),
            data="bogus", content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_push_subscribe_missing_fields(self):
        body = json.dumps({"endpoint": "x"})  # sem keys
        resp = self.client.post(
            reverse("communications:push_subscribe"),
            data=body, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_push_unsubscribe(self):
        sub = PushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/z",
            p256dh="k", auth="a",
        )
        body = json.dumps({"endpoint": sub.endpoint})
        resp = self.client.post(
            reverse("communications:push_unsubscribe"),
            data=body, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(PushSubscription.objects.filter(pk=sub.pk).exists())


class AutoNotifyTests(TestCase):
    def test_assignment_creates_notification_for_assignee(self):
        empresa = create_test_empresa()
        actor = create_test_user("actor@t.com", "Actor", empresa)
        target = create_test_user("target@t.com", "Target", empresa)
        self.client.force_login(actor)

        # Cria Lead + Conversation
        lead = Lead.objects.create(empresa=empresa, name="Cliente X")
        from apps.communications.models import get_or_create_conversation
        conv = get_or_create_conversation(empresa, lead)

        self.assertEqual(target.notifications.count(), 0)
        resp = self.client.post(
            reverse("communications:assign", args=[conv.pk]),
            data={"user_id": str(target.pk)},
        )
        # Retorna redirect; aceita 200 OK também depending on EmpresaMiddleware
        self.assertIn(resp.status_code, (200, 302))
        self.assertEqual(target.notifications.count(), 1)
        notif = target.notifications.first()
        self.assertEqual(notif.type, Notification.Type.CONVERSATION_ASSIGNED)
        self.assertIn("Cliente X", notif.title)

    def test_inbound_message_creates_notification_for_assigned(self):
        empresa = create_test_empresa()
        assignee = create_test_user("a@t.com", "A", empresa)
        lead = Lead.objects.create(empresa=empresa, name="Cliente Y")
        from apps.communications.models import get_or_create_conversation
        conv = get_or_create_conversation(empresa, lead)
        conv.assigned_to = assignee
        conv.save(update_fields=["assigned_to", "updated_at"])

        ConversationMessage.objects.create(
            conversation=conv,
            direction=ConversationMessage.Direction.INBOUND,
            channel=ConversationMessage.Channel.WHATSAPP,
            content="Preciso de ajuda urgente",
        )
        # Signal cria notificação para assignee
        self.assertEqual(assignee.notifications.count(), 1)
        notif = assignee.notifications.first()
        self.assertEqual(notif.type, Notification.Type.MESSAGE_INBOUND)
        self.assertIn("Cliente Y", notif.title)
        self.assertIn("ajuda urgente", notif.body)

    def test_outbound_message_does_not_notify(self):
        empresa = create_test_empresa()
        assignee = create_test_user("a@t.com", "A", empresa)
        lead = Lead.objects.create(empresa=empresa, name="Cliente Z")
        from apps.communications.models import get_or_create_conversation
        conv = get_or_create_conversation(empresa, lead)
        conv.assigned_to = assignee
        conv.save(update_fields=["assigned_to", "updated_at"])

        # Mensagem OUTBOUND não deve notificar (é o usuário enviando)
        ConversationMessage.objects.create(
            conversation=conv,
            direction=ConversationMessage.Direction.OUTBOUND,
            channel=ConversationMessage.Channel.WHATSAPP,
            content="Aqui está a resposta",
        )
        self.assertEqual(assignee.notifications.count(), 0)


class DailyDigestTests(TestCase):
    def test_digest_skips_users_without_unread(self):
        from apps.communications.tasks import send_daily_digest
        empresa = create_test_empresa()
        user = create_test_user("d@t.com", "D", empresa)
        # User tem só notificações já lidas
        from django.utils import timezone
        Notification.objects.create(
            user=user, empresa=empresa,
            type=Notification.Type.SYSTEM, title="Lida",
            read_at=timezone.now(),
        )
        summary = send_daily_digest()
        self.assertEqual(summary["emails"], 0)

    def test_digest_sends_to_users_with_unread(self):
        from django.core import mail

        from apps.communications.tasks import send_daily_digest
        empresa = create_test_empresa()
        user = create_test_user("digest@t.com", "Digest", empresa)
        Notification.objects.create(
            user=user, empresa=empresa,
            type=Notification.Type.MESSAGE_INBOUND,
            title="Cliente novo", body="Quer orçamento",
            url="/inbox/42/",
        )

        mail.outbox = []
        summary = send_daily_digest()
        self.assertEqual(summary["emails"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Cliente novo", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["digest@t.com"])

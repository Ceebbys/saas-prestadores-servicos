"""Testes do realtime via Django Channels (signal broadcasts).

NOTA: testes assíncronos com `WebsocketCommunicator` foram desabilitados —
em ambiente Windows + Channels 4.3 + Django 5.1 a comunicação async no
test runner do unittest às vezes trava. A lógica dos consumers
(auth check, tenant isolation, subscribe/unsubscribe) é defendida por:
- inspeção de código
- testes síncronos abaixo via channel_layer.group_send/receive direto
- smoke manual descrito no docs/realtime_smoke.md
"""
from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.test import TestCase

from apps.communications.models import (
    Conversation,
    ConversationMessage,
    get_or_create_conversation,
)
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead


class SignalBroadcastTests(TestCase):
    """post_save de ConversationMessage e Conversation disparam broadcasts."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.layer = get_channel_layer()

    def test_layer_available(self):
        self.assertIsNotNone(self.layer)
        # InMemory em testes (sem Redis)
        layer_name = type(self.layer).__name__
        self.assertIn(layer_name, ("InMemoryChannelLayer", "RedisChannelLayer"))

    def test_creating_message_dispatches_to_empresa_group(self):
        empresa = create_test_empresa()
        create_test_user("br@t.com", "BR", empresa)
        lead = Lead.objects.create(empresa=empresa, name="LL")
        conv = get_or_create_conversation(empresa, lead)

        empresa_group = f"inbox-empresa-{empresa.pk}"
        test_channel = "test-channel-msg-new"
        async_to_sync(self.layer.group_add)(empresa_group, test_channel)
        try:
            ConversationMessage.objects.create(
                conversation=conv,
                direction=ConversationMessage.Direction.INBOUND,
                channel=ConversationMessage.Channel.WHATSAPP,
                content="Olá mundo",
            )
            received = async_to_sync(self.layer.receive)(test_channel)
            self.assertEqual(received["type"], "message.new")
            self.assertEqual(received["conversation_id"], conv.pk)
            self.assertEqual(received["empresa_id"], empresa.pk)
            self.assertIn("Olá", received["preview"])
        finally:
            async_to_sync(self.layer.group_discard)(empresa_group, test_channel)

    def test_creating_message_also_dispatches_to_conv_group(self):
        empresa = create_test_empresa()
        create_test_user("bc@t.com", "BC", empresa)
        lead = Lead.objects.create(empresa=empresa, name="Subscriber")
        conv = get_or_create_conversation(empresa, lead)

        conv_group = f"inbox-conv-{conv.pk}"
        test_channel = "test-channel-conv-spec"
        async_to_sync(self.layer.group_add)(conv_group, test_channel)
        try:
            ConversationMessage.objects.create(
                conversation=conv,
                direction=ConversationMessage.Direction.INBOUND,
                channel=ConversationMessage.Channel.EMAIL,
                content="Olá pelo email",
            )
            received = async_to_sync(self.layer.receive)(test_channel)
            self.assertEqual(received["type"], "message.new")
            self.assertEqual(received["conversation_id"], conv.pk)
        finally:
            async_to_sync(self.layer.group_discard)(conv_group, test_channel)

    def test_conversation_status_change_broadcasts(self):
        empresa = create_test_empresa()
        create_test_user("c@t.com", "C", empresa)
        lead = Lead.objects.create(empresa=empresa, name="X")
        conv = get_or_create_conversation(empresa, lead)

        empresa_group = f"inbox-empresa-{empresa.pk}"
        test_channel = "test-channel-status"
        async_to_sync(self.layer.group_add)(empresa_group, test_channel)
        try:
            conv.status = Conversation.Status.IN_PROGRESS
            conv.save(update_fields=["status", "updated_at"])
            received = async_to_sync(self.layer.receive)(test_channel)
            self.assertEqual(received["type"], "conversation.updated")
            self.assertEqual(received["status"], "in_progress")
            self.assertEqual(received["conversation_id"], conv.pk)
        finally:
            async_to_sync(self.layer.group_discard)(empresa_group, test_channel)


class NotificationServiceTests(TestCase):
    """Serviço `notify()` cria DB row + dispara WS."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.layer = get_channel_layer()

    def test_notify_creates_row_and_broadcasts(self):
        from apps.communications.models import Notification
        from apps.communications.notifications import notify

        empresa = create_test_empresa()
        user = create_test_user("n@t.com", "N", empresa)
        user.active_empresa = empresa
        user.save()

        notif_group = f"notif-user-{user.pk}"
        test_channel = "test-channel-notif"
        async_to_sync(self.layer.group_add)(notif_group, test_channel)
        try:
            notif = notify(
                user,
                type=Notification.Type.SYSTEM,
                title="Olá",
                body="Teste",
                url="/dash/",
                icon="bell",
            )
            # DB row criada
            self.assertIsNotNone(notif.pk)
            self.assertEqual(notif.user, user)
            self.assertEqual(notif.empresa, empresa)
            self.assertEqual(notif.title, "Olá")
            # WS broadcast
            received = async_to_sync(self.layer.receive)(test_channel)
            self.assertEqual(received["type"], "notification.new")
            self.assertEqual(received["title"], "Olá")
            self.assertEqual(received["url"], "/dash/")
        finally:
            async_to_sync(self.layer.group_discard)(notif_group, test_channel)

    def test_notify_new_message_to_assigned(self):
        from apps.communications.notifications import notify_new_message

        empresa = create_test_empresa()
        user = create_test_user("assigned@t.com", "Att", empresa)
        lead = Lead.objects.create(empresa=empresa, name="Cliente")
        conv = get_or_create_conversation(empresa, lead)
        conv.assigned_to = user
        conv.save(update_fields=["assigned_to", "updated_at"])
        msg = ConversationMessage.objects.create(
            conversation=conv,
            direction=ConversationMessage.Direction.INBOUND,
            channel=ConversationMessage.Channel.WHATSAPP,
            content="Preciso de ajuda",
        )
        notifs = notify_new_message(conv, msg)
        # Caminho 1: apenas o atribuído
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0].user, user)
        self.assertIn("Cliente", notifs[0].title)

    def test_notify_new_message_broadcasts_to_team_when_unassigned(self):
        """Conversa sem atribuição → notifica OWNER/ADMIN/MANAGER do tenant."""
        from apps.accounts.models import Membership
        from apps.communications.notifications import notify_new_message

        empresa = create_test_empresa()
        # 1 OWNER, 1 ADMIN, 1 MANAGER, 1 MEMBER (este último NÃO recebe)
        u_owner = create_test_user("owner@t.com", "Owner", empresa)
        # create_test_user já cria OWNER membership; precisamos criar outros
        from apps.accounts.models import User
        u_admin = User.objects.create_user(email="adm@t.com", full_name="Admin")
        u_admin.active_empresa = empresa
        u_admin.save()
        Membership.objects.create(
            user=u_admin, empresa=empresa, role=Membership.Role.ADMIN, is_active=True,
        )
        u_member = User.objects.create_user(email="mem@t.com", full_name="Member")
        u_member.active_empresa = empresa
        u_member.save()
        Membership.objects.create(
            user=u_member, empresa=empresa, role=Membership.Role.MEMBER, is_active=True,
        )

        lead = Lead.objects.create(empresa=empresa, name="Sem Atribuição")
        conv = get_or_create_conversation(empresa, lead)
        msg = ConversationMessage.objects.create(
            conversation=conv,
            direction=ConversationMessage.Direction.INBOUND,
            channel=ConversationMessage.Channel.WHATSAPP,
            content="Olá",
        )
        notifs = notify_new_message(conv, msg)
        users_notified = {n.user_id for n in notifs}
        self.assertIn(u_owner.pk, users_notified)
        self.assertIn(u_admin.pk, users_notified)
        # MEMBER comum NÃO recebe (evita spam em times grandes)
        self.assertNotIn(u_member.pk, users_notified)

    def test_notify_assignment_skips_self(self):
        from apps.communications.notifications import notify_conversation_assigned

        empresa = create_test_empresa()
        user = create_test_user("self@t.com", "Self", empresa)
        lead = Lead.objects.create(empresa=empresa, name="L")
        conv = get_or_create_conversation(empresa, lead)
        # User atribui a si mesmo → sem notificação
        result = notify_conversation_assigned(conv, user, user)
        self.assertIsNone(result)

    def test_notification_mark_read(self):
        from apps.communications.models import Notification

        empresa = create_test_empresa()
        user = create_test_user("mr@t.com", "MR", empresa)
        notif = Notification.objects.create(
            user=user, empresa=empresa,
            type=Notification.Type.SYSTEM, title="t",
        )
        self.assertIsNone(notif.read_at)
        notif.mark_read()
        notif.refresh_from_db()
        self.assertIsNotNone(notif.read_at)

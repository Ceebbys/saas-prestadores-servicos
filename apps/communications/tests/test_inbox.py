"""Testes da inbox unificada de comunicações."""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.communications.models import (
    Conversation,
    ConversationMessage,
    get_or_create_conversation,
)
from apps.communications.services import (
    add_internal_note,
    record_bot_outbound,
    record_inbound,
    send_email,
    send_whatsapp,
)
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)
from apps.crm.models import Lead


class ConversationModelTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("c@t.com", "C", self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="João")

    def test_get_or_create_returns_same_conversation(self):
        c1 = get_or_create_conversation(self.empresa, self.lead)
        c2 = get_or_create_conversation(self.empresa, self.lead)
        self.assertEqual(c1.pk, c2.pk)

    def test_touch_inbound_increments_unread(self):
        conv = get_or_create_conversation(self.empresa, self.lead)
        self.assertEqual(conv.unread_count, 0)
        conv.touch(
            direction="inbound", channel="whatsapp", content="Olá!",
        )
        self.assertEqual(conv.unread_count, 1)
        self.assertEqual(conv.last_message_preview, "Olá!")

    def test_mark_read_zeros_unread(self):
        conv = get_or_create_conversation(self.empresa, self.lead)
        conv.touch(direction="inbound", channel="whatsapp", content="x")
        conv.mark_read()
        self.assertEqual(conv.unread_count, 0)


class SendServicesTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("s@t.com", "S", self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Maria", phone="11999999999",
            email="maria@test.com",
        )
        self.conv = get_or_create_conversation(self.empresa, self.lead)

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.configured", new_callable=lambda: property(lambda self: True))
    def test_send_whatsapp_success(self, _mock_conf, mock_send):
        msg = send_whatsapp(self.conv, "Olá, tudo bem?")
        self.assertEqual(msg.delivery_status, ConversationMessage.DeliveryStatus.SENT)
        mock_send.assert_called_once()
        # Conversation touch
        self.conv.refresh_from_db()
        self.assertIn("Olá", self.conv.last_message_preview)
        self.assertEqual(self.conv.last_message_direction, "outbound")

    def test_send_whatsapp_no_phone_fails_gracefully(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Sem fone")
        conv = get_or_create_conversation(self.empresa, lead)
        msg = send_whatsapp(conv, "Oi")
        self.assertEqual(msg.delivery_status, ConversationMessage.DeliveryStatus.FAILED)
        self.assertIn("telefone", msg.error_message.lower())

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.configured", new_callable=lambda: property(lambda self: False))
    def test_send_whatsapp_unconfigured_fails(self, _mock):
        msg = send_whatsapp(self.conv, "x")
        self.assertEqual(msg.delivery_status, ConversationMessage.DeliveryStatus.FAILED)
        self.assertIn("Evolution", msg.error_message)

    def test_add_internal_note(self):
        msg = add_internal_note(self.conv, "Cliente solicitou desconto.")
        self.assertEqual(msg.channel, ConversationMessage.Channel.INTERNAL_NOTE)
        self.assertEqual(msg.direction, ConversationMessage.Direction.SYSTEM)

    def test_record_inbound_creates_message(self):
        conv, msg = record_inbound(
            empresa=self.empresa, lead=self.lead,
            channel="whatsapp", content="Olá",
            sender_external_id="5511999999999",
        )
        self.assertEqual(msg.direction, ConversationMessage.Direction.INBOUND)
        self.assertEqual(conv.unread_count, 1)

    def test_record_inbound_reopens_closed_conversation(self):
        self.conv.status = Conversation.Status.CLOSED
        self.conv.save()
        record_inbound(
            empresa=self.empresa, lead=self.lead,
            channel="whatsapp", content="Voltei",
        )
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.status, Conversation.Status.OPEN)

    def test_record_bot_outbound_marks_bot_payload(self):
        msg = record_bot_outbound(
            empresa=self.empresa, lead=self.lead,
            channel="whatsapp", content="Olá! Sou o bot.",
        )
        self.assertEqual(msg.direction, ConversationMessage.Direction.OUTBOUND)
        self.assertTrue(msg.payload.get("sent_by_bot"))


class InboxViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("u@t.com", "U", self.empresa)
        self.client.force_login(self.user)
        self.lead = Lead.objects.create(empresa=self.empresa, name="Cliente A", phone="11888888888")
        self.conv = get_or_create_conversation(self.empresa, self.lead)
        # Adiciona algumas mensagens
        record_inbound(
            empresa=self.empresa, lead=self.lead,
            channel="whatsapp", content="Oi, quero orçamento",
        )

    def test_inbox_list_renders(self):
        resp = self.client.get(reverse("communications:inbox"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cliente A")
        self.assertContains(resp, "orçamento")

    def test_inbox_filter_status(self):
        # Cria conversa encerrada com nome único que não colide com palavras do template
        lead2 = Lead.objects.create(empresa=self.empresa, name="LeadXYZ123Closed")
        conv2 = get_or_create_conversation(self.empresa, lead2)
        conv2.status = Conversation.Status.CLOSED
        conv2.save()
        resp = self.client.get(reverse("communications:inbox") + "?status=open")
        self.assertContains(resp, "Cliente A")
        self.assertNotContains(resp, "LeadXYZ123Closed")

    def test_inbox_search(self):
        resp = self.client.get(reverse("communications:inbox") + "?q=Cliente")
        self.assertContains(resp, "Cliente A")

    def test_detail_view_marks_read(self):
        self.conv.refresh_from_db()
        self.assertGreater(self.conv.unread_count, 0)
        resp = self.client.get(reverse("communications:detail", args=[self.conv.pk]))
        self.assertEqual(resp.status_code, 200)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.unread_count, 0)

    def test_detail_view_cross_tenant_404(self):
        outra = create_test_empresa(name="X", slug="x-inbox")
        create_test_user("x@t.com", "X", outra)
        lead_x = Lead.objects.create(empresa=outra, name="Outro")
        conv_x = get_or_create_conversation(outra, lead_x)
        resp = self.client.get(reverse("communications:detail", args=[conv_x.pk]))
        self.assertEqual(resp.status_code, 404)


class SendEndpointTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("u@t.com", "U", self.empresa)
        self.client.force_login(self.user)
        self.lead = Lead.objects.create(empresa=self.empresa, name="L", phone="11888888888")
        self.conv = get_or_create_conversation(self.empresa, self.lead)

    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.send_text", return_value=True)
    @patch("apps.chatbot.whatsapp.EvolutionAPIClient.configured", new_callable=lambda: property(lambda self: True))
    def test_send_via_whatsapp(self, _conf, _send):
        url = reverse("communications:send", args=[self.conv.pk])
        resp = self.client.post(url, data={
            "channel": "whatsapp",
            "content": "Mensagem teste",
        })
        self.assertIn(resp.status_code, (200, 302))
        self.assertEqual(
            self.conv.messages.filter(direction="outbound").count(), 1,
        )

    def test_send_internal_note(self):
        url = reverse("communications:send", args=[self.conv.pk])
        resp = self.client.post(url, data={
            "channel": "internal_note",
            "content": "Nota privada",
        })
        self.assertIn(resp.status_code, (200, 302))
        note = self.conv.messages.filter(channel="internal_note").first()
        self.assertIsNotNone(note)
        self.assertEqual(note.content, "Nota privada")


class QuickActionTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("u@t.com", "U", self.empresa)
        self.client.force_login(self.user)
        create_pipeline_for_empresa(self.empresa)
        from apps.crm.models import Pipeline, PipelineStage
        self.pipeline = Pipeline.objects.filter(empresa=self.empresa).first()
        self.stage = self.pipeline.stages.order_by("order").first()
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="L", pipeline_stage=self.stage,
        )
        self.conv = get_or_create_conversation(self.empresa, self.lead)

    def test_move_pipeline(self):
        # Cria uma 2ª etapa
        from apps.crm.models import PipelineStage
        new_stage = PipelineStage.objects.create(
            pipeline=self.pipeline, name="Em qualificação", order=99,
        )
        resp = self.client.post(reverse("communications:quick_action", args=[self.conv.pk]), data={
            "action": "move_pipeline",
            "pipeline_stage_id": new_stage.pk,
        })
        self.assertIn(resp.status_code, (200, 302))
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.pipeline_stage_id, new_stage.pk)
        # Nota interna registrada
        note = self.conv.messages.filter(channel="internal_note").last()
        self.assertIn("Em qualificação", note.content)

    def test_create_opportunity(self):
        from apps.crm.models import Opportunity
        resp = self.client.post(reverse("communications:quick_action", args=[self.conv.pk]), data={
            "action": "create_opportunity",
            "title": "Orçamento casamento",
            "value": "5000",
        })
        self.assertIn(resp.status_code, (200, 302))
        opp = Opportunity.objects.filter(empresa=self.empresa, lead=self.lead).first()
        self.assertIsNotNone(opp)
        self.assertEqual(opp.title, "Orçamento casamento")

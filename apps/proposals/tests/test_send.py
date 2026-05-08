"""Testes de envio (e-mail, WhatsApp) e endpoint público.

Mocka `render_proposal_pdf` para isolar do WeasyPrint, que requer GTK
no Windows (limitação de ambiente dev — em produção Linux funciona normalmente).
"""
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.crm.models import Lead
from apps.proposals.models import Proposal
from apps.proposals.services.email import send_proposal_email
from apps.proposals.services.whatsapp import send_proposal_whatsapp
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)

# PDF fake — bytes mínimos para validar o anexo sem invocar WeasyPrint.
_FAKE_PDF = b"%PDF-1.4\n%fake_pdf_for_tests\n%%EOF"


def _proposal(empresa, **kwargs):
    create_pipeline_for_empresa(empresa)
    lead = Lead.objects.create(
        empresa=empresa, name="Cliente", email="cliente@example.com",
        phone="11987654321",
    )
    return Proposal.objects.create(
        empresa=empresa, lead=lead, title="Proposta",
        discount_percent=Decimal("0"),
        **kwargs,
    )


@patch(
    "apps.proposals.services.email.render_proposal_pdf",
    return_value=_FAKE_PDF,
)
class EmailServiceTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("e@t.com", "E", self.empresa)

    def test_email_sends_with_pdf_attachment(self, _mock_pdf):
        p = _proposal(self.empresa)
        ok, err = send_proposal_email(p, to_email="cliente@example.com")
        self.assertTrue(ok, msg=err)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn("cliente@example.com", msg.to)
        self.assertEqual(len(msg.attachments), 1)
        filename, content, mimetype = msg.attachments[0]
        self.assertTrue(filename.endswith(".pdf"))
        self.assertEqual(mimetype, "application/pdf")
        self.assertEqual(content, _FAKE_PDF)

    def test_email_transitions_status_to_sent(self, _mock_pdf):
        p = _proposal(self.empresa, status=Proposal.Status.DRAFT)
        send_proposal_email(p, to_email="cliente@example.com")
        p.refresh_from_db()
        self.assertEqual(p.status, "sent")
        self.assertIsNotNone(p.last_email_sent_at)

    def test_email_returns_error_on_missing_to(self, _mock_pdf):
        p = _proposal(self.empresa)
        ok, err = send_proposal_email(p, to_email="")
        self.assertFalse(ok)
        self.assertIn("e-mail", err.lower())


@patch(
    "apps.proposals.services.whatsapp.render_proposal_pdf",
    return_value=_FAKE_PDF,
)
class WhatsAppServiceTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("w@t.com", "W", self.empresa)
        # Configura WhatsApp da empresa
        from apps.chatbot.models import WhatsAppConfig
        WhatsAppConfig.objects.create(
            empresa=self.empresa,
            instance_name="test-instance",
            api_url="https://example.com",
            api_key="testkey",
            instance_token="testkey",
        )

    def test_attachment_path_marks_sent(self, _mock_pdf):
        p = _proposal(self.empresa, status=Proposal.Status.DRAFT)
        with patch(
            "apps.proposals.services.whatsapp.EvolutionAPIClient.send_media",
            return_value=(True, ""),
        ):
            ok, mode, msg = send_proposal_whatsapp(p, to_phone="11999999999")
        self.assertTrue(ok)
        self.assertEqual(mode, "attachment")
        p.refresh_from_db()
        self.assertEqual(p.status, "sent")
        self.assertIsNotNone(p.last_whatsapp_sent_at)

    def test_attachment_failure_falls_back_to_link(self, _mock_pdf):
        p = _proposal(self.empresa, status=Proposal.Status.DRAFT)
        with patch(
            "apps.proposals.services.whatsapp.EvolutionAPIClient.send_media",
            return_value=(False, "API down"),
        ), patch(
            "apps.proposals.services.whatsapp.EvolutionAPIClient.send_text",
            return_value=True,
        ):
            ok, mode, msg = send_proposal_whatsapp(p, to_phone="11999999999")
        self.assertTrue(ok)
        self.assertEqual(mode, "link")
        p.refresh_from_db()
        self.assertEqual(p.status, "sent")

    def test_both_failing_returns_failed(self, _mock_pdf):
        p = _proposal(self.empresa)
        with patch(
            "apps.proposals.services.whatsapp.EvolutionAPIClient.send_media",
            return_value=(False, "boom"),
        ), patch(
            "apps.proposals.services.whatsapp.EvolutionAPIClient.send_text",
            return_value=False,
        ):
            ok, mode, msg = send_proposal_whatsapp(p, to_phone="11999999999")
        self.assertFalse(ok)
        self.assertEqual(mode, "failed")
        self.assertIn("Copie", msg)


class PublicViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()

    def test_public_view_renders_for_valid_token(self):
        p = _proposal(self.empresa)
        url = reverse("proposal_public", args=[p.public_token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(p.number.encode(), resp.content)

    def test_public_view_404s_for_invalid_token(self):
        random_token = uuid.uuid4()
        url = reverse("proposal_public", args=[random_token])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_public_view_marks_viewed_first_time(self):
        p = _proposal(self.empresa, status=Proposal.Status.SENT)
        self.assertIsNone(p.viewed_at)
        url = reverse("proposal_public", args=[p.public_token])
        self.client.get(url)
        p.refresh_from_db()
        self.assertIsNotNone(p.viewed_at)
        self.assertEqual(p.status, "viewed")

    def test_public_view_does_not_double_mark(self):
        from django.utils import timezone

        p = _proposal(self.empresa)
        p.viewed_at = timezone.now()
        p.save()
        first_viewed = p.viewed_at
        url = reverse("proposal_public", args=[p.public_token])
        self.client.get(url)
        p.refresh_from_db()
        self.assertEqual(p.viewed_at, first_viewed)

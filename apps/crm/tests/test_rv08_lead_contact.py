"""RV08 (4.1) — Histórico de ligações/contatos do Lead voltou a gravar.

Bug: `LeadContactForm` exigia `contacted_at` (model sem `blank=True`), e o form
do template só enviava channel+note → validação falhava e nada era salvo.
"""
from django.test import TestCase
from django.urls import reverse

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead, LeadContact


class LeadContactRV08Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client.force_login(self.user)
        self.lead = Lead.objects.create(empresa=self.empresa, name="Lead X")

    def test_records_call_with_channel_and_note_only(self):
        """O caso que estava quebrado: enviar só channel + note."""
        resp = self.client.post(
            reverse("crm:lead_contact_create", args=[self.lead.pk]),
            data={"channel": "phone", "note": "Não atendeu, retornar amanhã"},
        )
        self.assertIn(resp.status_code, (302, 303))
        contacts = LeadContact.objects.filter(lead=self.lead)
        self.assertEqual(contacts.count(), 1)
        c = contacts.first()
        self.assertEqual(c.channel, "phone")
        self.assertEqual(c.note, "Não atendeu, retornar amanhã")
        self.assertIsNotNone(c.contacted_at)  # preenchido com "agora"
        self.assertEqual(c.user, self.user)
        self.assertEqual(c.empresa, self.empresa)

    def test_records_with_explicit_datetime(self):
        resp = self.client.post(
            reverse("crm:lead_contact_create", args=[self.lead.pk]),
            data={"channel": "whatsapp", "contacted_at": "2026-01-15T09:30"},
        )
        self.assertIn(resp.status_code, (302, 303))
        c = LeadContact.objects.get(lead=self.lead)
        self.assertEqual(c.channel, "whatsapp")
        self.assertEqual(c.contacted_at.year, 2026)
        self.assertEqual(c.contacted_at.month, 1)
        self.assertEqual(c.contacted_at.day, 15)

    def test_history_is_displayed_on_lead_detail(self):
        LeadContact.objects.create(
            empresa=self.empresa, lead=self.lead, channel="phone",
            note="Ligação de teste", user=self.user,
        )
        resp = self.client.get(reverse("crm:lead_detail", args=[self.lead.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ligação de teste")

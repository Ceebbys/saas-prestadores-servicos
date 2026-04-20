"""Tests for Lead/PipelineStage integration, LeadContact, and signals."""

from django.test import TestCase

from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)
from apps.crm.models import Lead, LeadContact, Opportunity, PipelineStage


class LeadPipelineIntegrationTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("t@t.com", "Tester", self.empresa)
        self.pipeline, self.s0, self.s1, self.s_won = create_pipeline_for_empresa(
            self.empresa
        )

    def test_lead_auto_assigns_first_stage_on_create(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Auto Stage")
        lead.refresh_from_db()
        self.assertEqual(lead.pipeline_stage_id, self.s0.id)

    def test_lead_auto_creates_opportunity_on_create(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Auto Opp")
        self.assertTrue(lead.opportunities.exists())
        opp = lead.opportunities.first()
        self.assertEqual(opp.current_stage_id, self.s0.id)

    def test_changing_lead_stage_syncs_opportunities(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Sync")
        lead.pipeline_stage = self.s1
        lead.save()
        opp = lead.opportunities.first()
        opp.refresh_from_db()
        self.assertEqual(opp.current_stage_id, self.s1.id)

    def test_changing_opportunity_stage_syncs_lead(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Reverse Sync")
        opp = lead.opportunities.first()
        opp.current_stage = self.s_won
        opp.save()
        lead.refresh_from_db()
        self.assertEqual(lead.pipeline_stage_id, self.s_won.id)

    def test_deleting_stage_reassigns_leads_to_previous(self):
        lead_a = Lead.objects.create(empresa=self.empresa, name="A")
        # Move lead to stage s1
        lead_a.pipeline_stage = self.s1
        lead_a.save()
        # Opportunities were auto-created and are PROTECTed; move them first
        # (mirrors real-world flow: user moves opps before deleting stage)
        lead_a.opportunities.update(current_stage=self.s0)

        self.s1.delete()
        lead_a.refresh_from_db()
        # Pre_delete signal moved leads to previous stage (s0)
        self.assertEqual(lead_a.pipeline_stage_id, self.s0.id)


class LeadContactModelTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="Contact Lead")

    def test_create_lead_contact(self):
        contact = LeadContact.objects.create(
            empresa=self.empresa,
            lead=self.lead,
            channel=LeadContact.Channel.PHONE,
            note="Ligação de follow-up",
        )
        self.assertEqual(contact.lead_id, self.lead.id)
        self.assertEqual(contact.channel, "phone")
        self.assertIn("Contact Lead", str(contact))

    def test_lead_contacts_reverse_relation(self):
        LeadContact.objects.create(
            empresa=self.empresa, lead=self.lead, channel="whatsapp"
        )
        LeadContact.objects.create(
            empresa=self.empresa, lead=self.lead, channel="email"
        )
        self.assertEqual(self.lead.contacts.count(), 2)


class LeadCpfCnpjValidationTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_pipeline_for_empresa(self.empresa)

    def test_cpf_cnpj_optional_empty_is_valid(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Empty Docs")
        lead.full_clean()  # should not raise

    def test_invalid_cpf_raises(self):
        from django.core.exceptions import ValidationError
        lead = Lead(empresa=self.empresa, name="Bad CPF", cpf="111.111.111-11")
        with self.assertRaises(ValidationError):
            lead.full_clean()

    def test_valid_cpf_passes(self):
        # A canonical valid CPF (test-safe)
        lead = Lead(empresa=self.empresa, name="OK CPF", cpf="529.982.247-25")
        lead.full_clean()

    def test_invalid_cnpj_raises(self):
        from django.core.exceptions import ValidationError
        lead = Lead(empresa=self.empresa, name="Bad CNPJ", cnpj="11.111.111/1111-11")
        with self.assertRaises(ValidationError):
            lead.full_clean()

    def test_valid_cnpj_passes(self):
        lead = Lead(empresa=self.empresa, name="OK CNPJ", cnpj="04.252.011/0001-10")
        lead.full_clean()

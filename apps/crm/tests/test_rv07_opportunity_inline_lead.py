"""RV07 — Item 5.1: criar Lead/contato direto pela Pipeline (Nova Oportunidade).

Antes a Nova Oportunidade só permitia escolher um lead existente num dropdown.
Agora replica a tela de Leads: lead existente OU novo lead (com contato novo
ou existente), sem duplicar a oportunidade criada pelo signal.
"""
from decimal import Decimal

from django.test import TestCase

from apps.core.tests.helpers import create_test_empresa
from apps.crm.forms import OpportunityForm
from apps.crm.models import Lead, Opportunity, Pipeline, PipelineStage


def _pipeline(empresa):
    p = Pipeline.objects.create(empresa=empresa, name="Vendas", is_default=True)
    s = PipelineStage.objects.create(pipeline=p, name="Novo", order=0)
    return p, s


class OpportunityInlineLeadTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-opp")
        self.pipeline, self.stage = _pipeline(self.empresa)

    def _base_data(self, **over):
        data = {
            "title": "Obra X",
            "pipeline": self.pipeline.pk,
            "current_stage": self.stage.pk,
            "value": "1500.00",
            "probability": "50",
            "priority": "medium",
        }
        data.update(over)
        return data

    def _save(self, form):
        # Na view, EmpresaMixin.form_valid seta instance.empresa antes do save.
        form.instance.empresa = self.empresa
        return form.save()

    def test_new_lead_with_new_contact_creates_one_lead_one_opportunity(self):
        data = self._base_data(
            lead_mode="new",
            contact_mode="new",
            new_contato_name="Maria Nova",
            new_contato_phone="11999998888",
        )
        form = OpportunityForm(data=data, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        opp = self._save(form)

        leads = Lead.objects.filter(empresa=self.empresa)
        self.assertEqual(leads.count(), 1)
        lead = leads.first()
        self.assertEqual(lead.name, "Obra X")
        self.assertIsNotNone(lead.contato)
        self.assertEqual(lead.contato.name, "Maria Nova")
        self.assertEqual(lead.estimated_value, Decimal("1500.00"))
        # Exatamente 1 oportunidade — o signal NÃO criou uma 2ª.
        self.assertEqual(Opportunity.objects.filter(lead=lead).count(), 1)
        self.assertEqual(opp.lead_id, lead.pk)

    def test_new_lead_new_contact_with_multiple_phones(self):
        # RV07 (4.2) — o "criar novo contato" inline da Nova Oportunidade
        # também aceita múltiplos telefones (mesmo editor do Novo Lead).
        import json
        tels = [
            {"tipo": "celular", "numero": "11911112222", "is_principal": True},
            {"tipo": "whatsapp", "numero": "11933334444", "is_principal": False},
        ]
        data = self._base_data(
            lead_mode="new",
            contact_mode="new",
            new_contato_name="Multi Fone",
            new_contato_telefones_json=json.dumps(tels),
        )
        form = OpportunityForm(data=data, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        opp = self._save(form)

        contato = opp.lead.contato
        self.assertIsNotNone(contato)
        self.assertEqual(contato.telefones.count(), 2)
        # principal = celular -> phone; o de tipo whatsapp -> whatsapp.
        self.assertEqual(contato.phone, "11911112222")
        self.assertEqual(contato.whatsapp, "11933334444")
        self.assertEqual(contato.telefones.filter(is_principal=True).count(), 1)

    def test_new_lead_with_existing_contact(self):
        from apps.contacts.models import Contato
        contato = Contato.objects.create(empresa=self.empresa, name="João Velho")
        data = self._base_data(
            lead_mode="new",
            contact_mode="search",
            contato=contato.pk,
        )
        form = OpportunityForm(data=data, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        opp = self._save(form)
        self.assertEqual(opp.lead.contato_id, contato.pk)
        self.assertEqual(Opportunity.objects.filter(lead=opp.lead).count(), 1)

    def test_existing_lead_mode_still_works(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="Lead Velho", pipeline_stage=self.stage,
        )
        # criar lead auto-criou 1 oportunidade
        self.assertEqual(Opportunity.objects.filter(lead=lead).count(), 1)
        data = self._base_data(lead_mode="existing", lead=lead.pk, value="0")
        form = OpportunityForm(data=data, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        opp = self._save(form)
        self.assertEqual(opp.lead_id, lead.pk)

    def test_new_lead_mode_requires_contact_name(self):
        data = self._base_data(lead_mode="new", contact_mode="new")  # sem nome
        form = OpportunityForm(data=data, empresa=self.empresa)
        self.assertFalse(form.is_valid())
        self.assertIn("new_contato_name", form.errors)

    def test_existing_mode_requires_lead(self):
        data = self._base_data(lead_mode="existing")  # sem lead
        form = OpportunityForm(data=data, empresa=self.empresa)
        self.assertFalse(form.is_valid())
        self.assertIn("lead", form.errors)

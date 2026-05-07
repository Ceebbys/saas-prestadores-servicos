"""Testes da integração Lead x Contato."""

from django.db.models import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from apps.contacts.models import Contato
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)
from apps.crm.models import Lead


class LeadContatoModelTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("u@t.com", "U", self.empresa)
        create_pipeline_for_empresa(self.empresa)

    def test_lead_with_contato_uses_contato_name(self):
        contato = Contato.objects.create(
            empresa=self.empresa, name="João Cliente",
            cpf_cnpj="529.982.247-25",
        )
        lead = Lead.objects.create(
            empresa=self.empresa, name="Levantamento Lote X",
            contato=contato,
        )
        self.assertEqual(lead.contact_name, "João Cliente")
        self.assertEqual(lead.contact_document, "529.982.247-25")
        self.assertIn("João Cliente", str(lead))

    def test_lead_without_contato_falls_back_to_legacy(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente sem contato",
            email="legacy@t.com", phone="11999",
        )
        self.assertEqual(lead.contact_name, "Cliente sem contato")
        self.assertEqual(lead.contact_email, "legacy@t.com")

    def test_one_contato_many_leads(self):
        contato = Contato.objects.create(
            empresa=self.empresa, name="Cliente Reutilizável",
            cpf_cnpj="529.982.247-25",
        )
        Lead.objects.create(
            empresa=self.empresa, name="Op 1", contato=contato,
        )
        Lead.objects.create(
            empresa=self.empresa, name="Op 2", contato=contato,
        )
        self.assertEqual(contato.leads.count(), 2)

    def test_delete_contato_with_leads_raises_protected(self):
        contato = Contato.objects.create(
            empresa=self.empresa, name="C",
        )
        Lead.objects.create(empresa=self.empresa, name="Op", contato=contato)
        with self.assertRaises(ProtectedError):
            contato.delete()


class LeadFormDualModeTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("u@t.com", "U", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.client = Client()
        self.client.force_login(self.user)

    def test_create_lead_with_existing_contato(self):
        contato = Contato.objects.create(
            empresa=self.empresa, name="Existente",
        )
        resp = self.client.post(reverse("crm:lead_create"), {
            "contact_mode": "search",
            "contato": contato.pk,
            "name": "Levantamento Topográfico",
            "source": "whatsapp",
        })
        # Deve redirecionar (sucesso) ou retornar 200 com partial; aceitar ambos
        # contanto que o lead seja criado.
        lead = Lead.objects.filter(name="Levantamento Topográfico").first()
        self.assertIsNotNone(lead)
        self.assertEqual(lead.contato_id, contato.pk)

    def test_create_lead_with_new_contato(self):
        resp = self.client.post(reverse("crm:lead_create"), {
            "contact_mode": "new",
            "new_contato_name": "Novo Cliente",
            "new_contato_document": "529.982.247-25",
            "new_contato_phone": "11999990000",
            "new_contato_email": "novo@t.com",
            "name": "Regularização",
            "source": "whatsapp",
        })
        lead = Lead.objects.filter(name="Regularização").first()
        self.assertIsNotNone(lead, f"Lead not created. Response status={resp.status_code}")
        self.assertIsNotNone(lead.contato)
        self.assertEqual(lead.contato.name, "Novo Cliente")
        self.assertEqual(lead.contato.cpf_cnpj_normalized, "52998224725")

    def test_create_lead_new_contato_blocks_duplicate_doc(self):
        Contato.objects.create(
            empresa=self.empresa, name="Já existe", cpf_cnpj="529.982.247-25",
        )
        resp = self.client.post(reverse("crm:lead_create"), {
            "contact_mode": "new",
            "new_contato_name": "Tentativa Dup",
            "new_contato_document": "529.982.247-25",
            "name": "Op",
            "source": "site",
        })
        # Não deve criar o lead
        self.assertFalse(Lead.objects.filter(name="Op").exists())

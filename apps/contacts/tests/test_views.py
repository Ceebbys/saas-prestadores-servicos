"""Testes das views de Contatos (list/detail/create/update/delete/autocomplete)."""

from django.test import Client, TestCase
from django.urls import reverse

from apps.contacts.models import Contato
from apps.core.tests.helpers import (
    create_test_empresa,
    create_test_user,
)


class ContactViewsTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client = Client()
        self.client.force_login(self.user)

    def test_list_renders(self):
        Contato.objects.create(
            empresa=self.empresa, name="João", cpf_cnpj="529.982.247-25",
        )
        resp = self.client.get(reverse("contacts:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "João")

    def test_list_search(self):
        Contato.objects.create(empresa=self.empresa, name="Maria")
        Contato.objects.create(empresa=self.empresa, name="João Silva")
        resp = self.client.get(reverse("contacts:list"), {"q": "joão"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "João Silva")
        self.assertNotContains(resp, "Maria")

    def test_create(self):
        resp = self.client.post(reverse("contacts:create"), {
            "name": "Novo Contato",
            "cpf_cnpj": "529.982.247-25",
            "phone": "11999990000",
            "email": "novo@t.com",
            "is_active": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Contato.objects.filter(empresa=self.empresa, name="Novo Contato").exists()
        )

    def test_create_rejects_duplicate_doc(self):
        Contato.objects.create(
            empresa=self.empresa, name="Existing", cpf_cnpj="529.982.247-25",
        )
        resp = self.client.post(reverse("contacts:create"), {
            "name": "Dup",
            "cpf_cnpj": "52998224725",
            "is_active": "on",
        })
        # Should NOT redirect — form has error
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Já existe um contato")

    def test_detail_shows_leads(self):
        from apps.crm.models import Lead, Pipeline, PipelineStage
        contato = Contato.objects.create(empresa=self.empresa, name="J")
        # Cria pipeline para signal não falhar
        p = Pipeline.objects.create(empresa=self.empresa, name="P", is_default=True)
        PipelineStage.objects.create(pipeline=p, name="S0", order=0)
        Lead.objects.create(empresa=self.empresa, name="Op", contato=contato)
        resp = self.client.get(reverse("contacts:detail", args=[contato.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Op")

    def test_autocomplete(self):
        Contato.objects.create(
            empresa=self.empresa, name="João Silva", cpf_cnpj="529.982.247-25",
        )
        Contato.objects.create(empresa=self.empresa, name="Maria")
        resp = self.client.get(reverse("contacts:autocomplete"), {"q": "joão"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "João Silva")
        self.assertNotContains(resp, "Maria")

    def test_delete_blocks_when_lead_attached(self):
        from apps.crm.models import Lead, Pipeline, PipelineStage
        contato = Contato.objects.create(empresa=self.empresa, name="J")
        p = Pipeline.objects.create(empresa=self.empresa, name="P", is_default=True)
        PipelineStage.objects.create(pipeline=p, name="S0", order=0)
        Lead.objects.create(empresa=self.empresa, name="Op", contato=contato)

        resp = self.client.post(
            reverse("contacts:delete", args=[contato.pk]), follow=False
        )
        # Should redirect back to detail, NOT delete
        self.assertTrue(Contato.objects.filter(pk=contato.pk).exists())

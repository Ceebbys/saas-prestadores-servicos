"""Testes dos services de Contato (busca, criação, vinculação)."""

from django.test import TestCase

from apps.contacts.models import Contato
from apps.contacts.services import (
    find_contato_by_document,
    get_or_create_contato_by_document,
    search_contatos,
)
from apps.core.tests.helpers import create_test_empresa


class ContactServicesTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa("Empresa A", "empresa-a")
        self.empresa_b = create_test_empresa("Empresa B", "empresa-b")

    def test_find_returns_none_when_empty(self):
        self.assertIsNone(find_contato_by_document(self.empresa, "529.982.247-25"))
        self.assertIsNone(find_contato_by_document(self.empresa, ""))

    def test_find_finds_with_or_without_mask(self):
        c = Contato.objects.create(
            empresa=self.empresa, name="João", cpf_cnpj="529.982.247-25",
        )
        self.assertEqual(find_contato_by_document(self.empresa, "529.982.247-25"), c)
        self.assertEqual(find_contato_by_document(self.empresa, "52998224725"), c)

    def test_find_isolated_per_empresa(self):
        Contato.objects.create(
            empresa=self.empresa, name="J", cpf_cnpj="529.982.247-25",
        )
        self.assertIsNone(find_contato_by_document(self.empresa_b, "52998224725"))

    def test_get_or_create_creates(self):
        c, created = get_or_create_contato_by_document(
            self.empresa, "529.982.247-25",
            defaults={"name": "João"},
        )
        self.assertTrue(created)
        self.assertEqual(c.name, "João")
        self.assertEqual(c.cpf_cnpj_normalized, "52998224725")

    def test_get_or_create_returns_existing(self):
        Contato.objects.create(
            empresa=self.empresa, name="Existing", cpf_cnpj="529.982.247-25",
        )
        c, created = get_or_create_contato_by_document(
            self.empresa, "52998224725",
            defaults={"name": "Should not be used"},
        )
        self.assertFalse(created)
        self.assertEqual(c.name, "Existing")

    def test_get_or_create_without_doc_requires_name(self):
        c, created = get_or_create_contato_by_document(
            self.empresa, "", defaults={"name": "Sem doc"},
        )
        self.assertTrue(created)
        self.assertEqual(c.cpf_cnpj_normalized, "")

    def test_search_by_name(self):
        Contato.objects.create(empresa=self.empresa, name="João Silva")
        Contato.objects.create(empresa=self.empresa, name="Maria")
        results = list(search_contatos(self.empresa, "joão"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "João Silva")

    def test_search_by_document_partial(self):
        Contato.objects.create(
            empresa=self.empresa, name="J", cpf_cnpj="529.982.247-25",
        )
        results = list(search_contatos(self.empresa, "5299"))
        self.assertEqual(len(results), 1)

    def test_search_isolated_per_empresa(self):
        Contato.objects.create(empresa=self.empresa, name="João")
        results = list(search_contatos(self.empresa_b, "joão"))
        self.assertEqual(results, [])

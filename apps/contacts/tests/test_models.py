"""Testes do modelo Contato e regras de unicidade."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.contacts.models import Contato
from apps.core.tests.helpers import create_test_empresa


class ContatoModelTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa("Empresa A", "empresa-a")
        self.empresa_b = create_test_empresa("Empresa B", "empresa-b")

    def test_normalize_document_on_save(self):
        c = Contato.objects.create(
            empresa=self.empresa, name="João", cpf_cnpj="529.982.247-25",
        )
        self.assertEqual(c.cpf_cnpj_normalized, "52998224725")

    def test_str_includes_document_when_present(self):
        c = Contato.objects.create(
            empresa=self.empresa, name="João", cpf_cnpj="529.982.247-25",
        )
        self.assertIn("João", str(c))
        self.assertIn("529.982.247-25", str(c))

    def test_str_no_document(self):
        c = Contato.objects.create(empresa=self.empresa, name="Maria")
        self.assertEqual(str(c), "Maria")

    def test_unique_doc_within_empresa(self):
        Contato.objects.create(
            empresa=self.empresa, name="João", cpf_cnpj="529.982.247-25",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Contato.objects.create(
                    empresa=self.empresa, name="João 2", cpf_cnpj="52998224725",
                )

    def test_same_doc_allowed_in_different_empresas(self):
        Contato.objects.create(
            empresa=self.empresa, name="João A", cpf_cnpj="529.982.247-25",
        )
        # Deve permitir
        c2 = Contato.objects.create(
            empresa=self.empresa_b, name="João B", cpf_cnpj="529.982.247-25",
        )
        self.assertIsNotNone(c2.pk)

    def test_invalid_cpf_raises_on_full_clean(self):
        c = Contato(empresa=self.empresa, name="X", cpf_cnpj="111.111.111-11")
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_invalid_cnpj_raises_on_full_clean(self):
        c = Contato(empresa=self.empresa, name="X", cpf_cnpj="11.111.111/1111-11")
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_pessoa_fisica_juridica_props(self):
        cpf = Contato.objects.create(
            empresa=self.empresa, name="J", cpf_cnpj="529.982.247-25",
        )
        cnpj = Contato.objects.create(
            empresa=self.empresa, name="ACME", cpf_cnpj="04.252.011/0001-10",
        )
        self.assertTrue(cpf.is_pessoa_fisica)
        self.assertFalse(cpf.is_pessoa_juridica)
        self.assertTrue(cnpj.is_pessoa_juridica)
        self.assertFalse(cnpj.is_pessoa_fisica)

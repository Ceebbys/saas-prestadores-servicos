"""Testes do RV05 FASE 5 — Contratos padronizados (rich + render)."""
import zipfile
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.contracts.models import Contract, ContractTemplate
from apps.contracts.services.render import (
    build_contract_context,
    render_contract_docx,
)
from apps.crm.models import Lead
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _setup(empresa):
    create_pipeline_for_empresa(empresa)
    lead = Lead.objects.create(empresa=empresa, name="Test Lead", email="x@y.com")
    contract = Contract.objects.create(
        empresa=empresa, lead=lead,
        title="Contrato de Teste",
        body="<p><strong>Cláusula 1:</strong> Teste</p>",
        terms="<p>Termos legais</p>",
        value=Decimal("5000"),
    )
    return contract, lead


class ContractRichFieldsTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client.force_login(self.user)

    def test_body_field_is_sanitized_on_save(self):
        c, _ = _setup(self.empresa)
        url = reverse("contracts:edit", args=[c.pk])
        resp = self.client.post(url, data={
            "title": c.title,
            "lead": str(c.lead.pk),
            "value": "5000",
            "body": '<p><strong>OK</strong></p><script>alert(1)</script>',
            "header_content": "", "introduction": "",
            "terms": "", "footer_content": "",
            "notes": "",
        })
        self.assertIn(resp.status_code, (302, 303))
        c.refresh_from_db()
        self.assertIn("<strong>", c.body)
        self.assertNotIn("script", c.body)

    def test_dual_read_legacy_content_when_body_empty(self):
        c, _ = _setup(self.empresa)
        c.body = ""
        c.content = "Texto legado"
        c.save()
        ctx = build_contract_context(c)
        self.assertEqual(ctx["body"], "Texto legado")

    def test_body_preferred_over_content(self):
        c, _ = _setup(self.empresa)
        c.body = "<p>Novo</p>"
        c.content = "Legado ignorado"
        c.save()
        ctx = build_contract_context(c)
        self.assertEqual(ctx["body"], "<p>Novo</p>")


class ContractDocxTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("d@t.com", "D", self.empresa)

    def test_docx_generation(self):
        c, _ = _setup(self.empresa)
        docx_bytes = render_contract_docx(c)
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"))
        z = zipfile.ZipFile(BytesIO(docx_bytes))
        self.assertIn("word/document.xml", z.namelist())
        doc_xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        self.assertIn("Contrato de Teste", doc_xml)


class ContractPreviewViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("p@t.com", "P", self.empresa)
        self.client.force_login(self.user)

    def test_preview_renders(self):
        c, _ = _setup(self.empresa)
        resp = self.client.get(reverse("contracts:preview", args=[c.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(c.number.encode(), resp.content)
        self.assertIn(b"Cl\xc3\xa1usula", resp.content)

    def test_docx_endpoint_returns_word_content_type(self):
        c, _ = _setup(self.empresa)
        resp = self.client.get(reverse("contracts:docx", args=[c.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("wordprocessingml", resp.headers.get("Content-Type", ""))

    def test_other_tenant_cannot_access(self):
        outra = create_test_empresa(name="X", slug="x")
        c, _ = _setup(outra)
        resp = self.client.get(reverse("contracts:preview", args=[c.pk]))
        self.assertEqual(resp.status_code, 404)


class ContractSoftDeleteTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("sd@t.com", "SD", self.empresa)

    def test_soft_delete_hides_from_default_manager(self):
        c, _ = _setup(self.empresa)
        c.delete()
        self.assertFalse(Contract.objects.filter(pk=c.pk).exists())
        self.assertTrue(Contract.all_objects.filter(pk=c.pk).exists())

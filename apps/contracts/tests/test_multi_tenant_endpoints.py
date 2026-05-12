"""RV05-G — Garante que PDF e DOCX endpoints também respeitam tenant isolation.

Auditoria descobriu que `test_other_tenant_cannot_access` cobre apenas preview.
Este arquivo cobre todos os 3 endpoints (preview, pdf, docx).
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.contracts.models import Contract
from apps.crm.models import Lead
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


class ContractEndpointsCrossTenantTests(TestCase):
    """Verifica que user de uma empresa não acessa contratos de outra empresa
    em todos os endpoints de visualização (preview, pdf, docx).
    """

    def setUp(self):
        # Tenant A — user fará as requests
        self.empresa_a = create_test_empresa(name="Empresa A", slug="emp-a")
        self.user_a = create_test_user("a@t.com", "A", self.empresa_a)
        # Tenant B — owner dos contratos que serão tentados
        self.empresa_b = create_test_empresa(name="Empresa B", slug="emp-b")
        create_test_user("b@t.com", "B", self.empresa_b)
        # Cria contract NO TENANT B
        create_pipeline_for_empresa(self.empresa_b)
        lead_b = Lead.objects.create(empresa=self.empresa_b, name="LB", email="lb@b.com")
        self.contract_b = Contract.objects.create(
            empresa=self.empresa_b, lead=lead_b,
            title="Confidencial B",
            body="<p>Conteúdo privado da empresa B</p>",
            value=Decimal("1000"),
        )
        # User A faz login (tenta acessar contrato B)
        self.client.force_login(self.user_a)

    def test_preview_returns_404_for_cross_tenant(self):
        url = reverse("contracts:preview", args=[self.contract_b.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_pdf_returns_404_for_cross_tenant(self):
        url = reverse("contracts:pdf", args=[self.contract_b.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_docx_returns_404_for_cross_tenant(self):
        url = reverse("contracts:docx", args=[self.contract_b.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_status_returns_404_for_cross_tenant(self):
        url = reverse("contracts:status", args=[self.contract_b.pk])
        resp = self.client.post(url, data={"status": "sent"})
        self.assertEqual(resp.status_code, 404)

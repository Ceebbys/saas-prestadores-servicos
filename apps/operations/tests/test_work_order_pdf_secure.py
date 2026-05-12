"""RV05-H — Verifica que WorkOrderPDFView usa render_html_to_pdf seguro.

Antes do RV05-H, a view chamava `weasyprint.HTML(string=...).write_pdf()`
direto, sem `url_fetcher`, deixando vetor SSRF residual. Agora deve usar
o helper do core que bloqueia file://, ftp:// e resolve /media/ via
default_storage.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.crm.models import Lead
from apps.operations.models import WorkOrder
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


class WorkOrderPDFSecureTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("wo@t.com", "WO", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.client.force_login(self.user)
        lead = Lead.objects.create(empresa=self.empresa, name="L", email="l@l.com")
        self.wo = WorkOrder.objects.create(
            empresa=self.empresa, lead=lead,
            title="OS Test", scheduled_date="2026-06-01",
        )

    def test_pdf_view_uses_core_render_html_to_pdf(self):
        """A view deve chamar `core.document_render.pdf.render_html_to_pdf`,
        que internamente aplica o url_fetcher seguro."""
        with patch("apps.core.document_render.pdf.render_html_to_pdf") as mock_render:
            mock_render.return_value = b"%PDF-1.7\nfake"
            url = reverse("operations:work_order_pdf", args=[self.wo.pk])
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            mock_render.assert_called_once()
            # Confere que base_url foi passado (necessário para url_fetcher)
            kwargs = mock_render.call_args.kwargs
            self.assertIn("base_url", kwargs)
            self.assertTrue(kwargs["base_url"].startswith("http"))

    def test_pdf_view_returns_pdf_content_type(self):
        with patch("apps.core.document_render.pdf.render_html_to_pdf") as mock_render:
            mock_render.return_value = b"%PDF-1.7\nfake"
            url = reverse("operations:work_order_pdf", args=[self.wo.pk])
            resp = self.client.get(url)
            self.assertEqual(resp["Content-Type"], "application/pdf")
            self.assertIn("OS-", resp["Content-Disposition"])

    def test_pdf_view_handles_valueerror_gracefully(self):
        """Imagem corrompida ou URL bloqueada → 4xx amigável, não 500."""
        with patch("apps.core.document_render.pdf.render_html_to_pdf") as mock_render:
            mock_render.side_effect = ValueError("Esquema bloqueado: file")
            url = reverse("operations:work_order_pdf", args=[self.wo.pk])
            resp = self.client.get(url, follow=False)
            # Redirect para detail (não 500)
            self.assertIn(resp.status_code, (302, 303))

    def test_pdf_view_handles_generic_exception_as_5xx_redirect(self):
        """Exception genérica não deve vazar stack trace; redireciona com mensagem."""
        with patch("apps.core.document_render.pdf.render_html_to_pdf") as mock_render:
            mock_render.side_effect = RuntimeError("Boom unexpected")
            url = reverse("operations:work_order_pdf", args=[self.wo.pk])
            resp = self.client.get(url, follow=False)
            self.assertIn(resp.status_code, (302, 303))

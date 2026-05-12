"""RV05-G — Render PDF/DOCX/Preview iterando múltiplas formas de pagamento.

Auditoria mostrou que `test_payment_methods_and_footer.py` cobre só o count
do M2M, mas não valida que o RENDER (preview HTML, PDF, DOCX) realmente
inclui o nome de cada forma. Este arquivo cobre essa lacuna.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.proposals.models import FormaPagamento, Proposal
from apps.proposals.services.render import (
    build_proposal_context,
    render_proposal_html,
    render_proposal_docx,
)
from apps.crm.models import Lead
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


class PaymentMethodsRenderTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("pmr@t.com", "PMR", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="L", email="l@l.com",
        )

    def _make_proposal(self, formas):
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="Multi-pay test", discount_percent=Decimal("0"),
        )
        for slug in formas:
            obj = FormaPagamento.objects.get(slug=slug)
            p.payment_methods.add(obj)
        return p

    def test_context_includes_all_payment_methods(self):
        p = self._make_proposal(["pix", "boleto", "cartao_credito"])
        ctx = build_proposal_context(p)
        names = [f.nome for f in ctx["payment_methods"]]
        self.assertIn("Pix", names)
        self.assertIn("Boleto", names)
        self.assertIn("Cartão de Crédito", names)

    def test_html_render_shows_all_payment_method_names(self):
        p = self._make_proposal(["pix", "boleto", "dinheiro"])
        html = render_proposal_html(p)
        self.assertIn("Pix", html)
        self.assertIn("Boleto", html)
        self.assertIn("Dinheiro", html)
        # Confere o separador "·" entre formas
        self.assertIn("·", html)

    def test_html_fallback_for_legacy_payment_method(self):
        """Sem payment_methods (M2M vazio), fallback para payment_method legado."""
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="Legacy", discount_percent=Decimal("0"),
            payment_method=Proposal.PaymentMethod.PIX,
        )
        html = render_proposal_html(p)
        # Pix vai aparecer renderizado pelo get_payment_method_display()
        self.assertIn("Pix", html)

    def test_html_no_payment_section_when_empty(self):
        """Sem M2M e sem legado, seção de pagamentos não fica visível."""
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="Empty", discount_percent=Decimal("0"),
        )
        html = render_proposal_html(p)
        # Não deve renderizar "Formas de pagamento aceitas" — só aparece se M2M tem itens
        self.assertNotIn("Formas de pagamento aceitas", html)

    def test_docx_render_includes_payment_methods(self):
        """DOCX gera com python-docx; verifica que bytes saem válidos
        e contém os nomes das formas no document.xml."""
        import zipfile, io as _io
        p = self._make_proposal(["pix", "boleto"])
        docx_bytes = render_proposal_docx(p)
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"))
        z = zipfile.ZipFile(_io.BytesIO(docx_bytes))
        doc_xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        self.assertIn("Pix", doc_xml)
        self.assertIn("Boleto", doc_xml)

    def test_backfill_migration_already_seeded_6_formas(self):
        """Migration 0009 deve ter seedado as 6 formas padrão."""
        slugs = set(FormaPagamento.objects.values_list("slug", flat=True))
        self.assertGreaterEqual(slugs, {
            "pix", "boleto", "cartao_credito",
            "cartao_debito", "dinheiro", "transferencia",
        })

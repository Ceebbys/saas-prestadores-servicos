"""Testes do RV05 FASE 4 — múltiplas formas de pagamento + rodapé."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.crm.models import Lead
from apps.proposals.models import FormaPagamento, Proposal
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


class FormaPagamentoSeedTests(TestCase):
    """Migration 0009 seedou as 6 formas padrão."""

    def test_six_default_forms_seeded(self):
        slugs = set(FormaPagamento.objects.values_list("slug", flat=True))
        expected = {
            "pix", "cartao_credito", "cartao_debito",
            "dinheiro", "transferencia", "boleto",
        }
        self.assertEqual(slugs, expected)

    def test_all_active(self):
        self.assertTrue(
            all(FormaPagamento.objects.values_list("is_active", flat=True))
        )

    def test_ordering(self):
        first = FormaPagamento.objects.order_by("ordem").first()
        self.assertEqual(first.slug, "pix")


class ProposalMultiPaymentMethodTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("pm@t.com", "PM", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="PM Lead")

    def test_proposal_can_have_multiple_payment_methods(self):
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="Multi",
            discount_percent=Decimal("0"),
        )
        pix = FormaPagamento.objects.get(slug="pix")
        boleto = FormaPagamento.objects.get(slug="boleto")
        p.payment_methods.add(pix, boleto)
        self.assertEqual(p.payment_methods.count(), 2)

    def test_legacy_payment_method_still_readable(self):
        """Backward compat: campo legado continua sendo lido se M2M vazio."""
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="Legacy",
            payment_method="pix",
            discount_percent=Decimal("0"),
        )
        self.assertEqual(p.payment_method, "pix")
        # Mas o display em template prefere M2M se existir
        pix = FormaPagamento.objects.get(slug="pix")
        p.payment_methods.add(pix)
        self.assertEqual(p.payment_methods.count(), 1)


class ProposalFooterTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("foot@t.com", "F", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="F Lead")
        self.client.force_login(self.user)

    def test_footer_content_is_sanitized(self):
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="Footer",
            discount_percent=Decimal("0"),
        )
        url = reverse("proposals:edit", args=[p.pk])
        resp = self.client.post(url, data={
            "title": p.title, "lead": str(self.lead.pk),
            "introduction": "", "body": "", "terms": "",
            "footer_content": '<p>Footer</p><script>alert(1)</script>',
            "discount_percent": "0",
        })
        self.assertIn(resp.status_code, (302, 303))
        p.refresh_from_db()
        # Sanitizer removeu o script
        self.assertNotIn("<script", p.footer_content)
        self.assertNotIn("alert", p.footer_content)
        self.assertIn("<p>Footer</p>", p.footer_content)

    def test_proposal_detail_shows_footer(self):
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="Footer detail",
            footer_content="<p>Visible footer</p>",
            discount_percent=Decimal("0"),
        )
        resp = self.client.get(reverse("proposals:detail", args=[p.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Rodap", resp.content)
        self.assertIn(b"Visible footer", resp.content)

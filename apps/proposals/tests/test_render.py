"""Testes de render: preview, PDF e DOCX."""
from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.proposals.models import Proposal, ProposalItem
from apps.proposals.services.render import (
    build_proposal_context,
    render_proposal_docx,
)
from apps.crm.models import Lead
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _setup_basic_proposal(empresa, with_items=True):
    create_pipeline_for_empresa(empresa)
    lead = Lead.objects.create(
        empresa=empresa, name="Cliente Teste", email="cliente@example.com",
    )
    proposal = Proposal.objects.create(
        empresa=empresa, lead=lead, title="Proposta de Teste",
        introduction="<p><strong>Bem-vindo</strong></p>",
        body="<p>Conteúdo principal</p>",
        terms="<p>Termos legais</p>",
        discount_percent=Decimal("0"),
    )
    if with_items:
        ProposalItem.objects.create(
            proposal=proposal, description="Serviço A",
            quantity=Decimal("2"), unit="un", unit_price=Decimal("100"),
            order=0,
        )
        proposal.recalculate_totals()
        proposal.refresh_from_db()
    return proposal


class RenderContextTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("r@t.com", "R", self.empresa)

    def test_context_has_all_keys(self):
        proposal = _setup_basic_proposal(self.empresa)
        ctx = build_proposal_context(proposal)
        self.assertEqual(ctx["proposal"], proposal)
        self.assertEqual(len(ctx["items"]), 1)
        self.assertEqual(ctx["lead"], proposal.lead)
        self.assertEqual(ctx["empresa"], self.empresa)
        self.assertIn("now", ctx)


class DOCXRenderTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("d@t.com", "D", self.empresa)

    def test_docx_returns_valid_zip(self):
        """DOCX é um zip — deve começar com PK\\x03\\x04 e ser maior que 1KB."""
        proposal = _setup_basic_proposal(self.empresa)
        docx_bytes = render_proposal_docx(proposal)
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"))
        self.assertGreater(len(docx_bytes), 1024)

    def test_docx_strips_html_tags(self):
        """Rich HTML não vaza para DOCX (limitação documentada)."""
        proposal = _setup_basic_proposal(self.empresa)
        proposal.introduction = "<p><strong>Negrito</strong> e <em>itálico</em></p>"
        proposal.save()
        docx_bytes = render_proposal_docx(proposal)
        # Em DOCX, "<strong>" não deve aparecer literalmente
        self.assertNotIn(b"<strong>", docx_bytes)
        self.assertNotIn(b"<em>", docx_bytes)


class PreviewViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("p@t.com", "P", self.empresa)
        self.client.force_login(self.user)

    def test_preview_renders(self):
        proposal = _setup_basic_proposal(self.empresa)
        url = reverse("proposals:preview", args=[proposal.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(proposal.number.encode(), resp.content)

    def test_other_tenant_cannot_access_preview(self):
        outra = create_test_empresa(name="Outra", slug="outra")
        proposal = _setup_basic_proposal(outra)
        url = reverse("proposals:preview", args=[proposal.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_docx_view_returns_word_content_type(self):
        proposal = _setup_basic_proposal(self.empresa)
        url = reverse("proposals:docx", args=[proposal.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            "wordprocessingml.document",
            resp.headers.get("Content-Type", ""),
        )
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))
        self.assertIn(proposal.number, resp.headers.get("Content-Disposition", ""))

"""RV05-H — Forma de pagamento desativada após vínculo continua aparecendo em todos os renders.

Antes do RV05-H, build_proposal_context e DOCX filtravam por `is_active=True`
mas o template HTML usava `.all()`. Resultado: forma desativada após uso
aparecia no PDF HTML mas SUMIA do DOCX/preview context.

Agora todos usam `.all()` (paridade total): se a proposta já vinculou a forma,
ela aparece em todos os canais. Para remover permanentemente, hard-delete
a FormaPagamento.
"""
from decimal import Decimal

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


class PaymentMethodsInactiveConsistencyTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("pmi@t.com", "PMI", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="L", email="l@l.com")
        self.proposal = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="P", discount_percent=Decimal("0"),
        )
        # Vincula 2 formas: pix (ficará ativa) e boleto (vai ser desativada)
        self.pix = FormaPagamento.objects.get(slug="pix")
        self.boleto = FormaPagamento.objects.get(slug="boleto")
        self.proposal.payment_methods.add(self.pix, self.boleto)

    def _deactivate(self, forma):
        forma.is_active = False
        forma.save()

    def test_context_shows_inactive_method_after_link(self):
        """Forma desativada depois do vínculo continua no contexto."""
        self._deactivate(self.boleto)
        ctx = build_proposal_context(self.proposal)
        slugs = [f.slug for f in ctx["payment_methods"]]
        self.assertIn("pix", slugs)
        self.assertIn("boleto", slugs)  # AINDA aparece — paridade

    def test_html_render_shows_inactive_method(self):
        self._deactivate(self.boleto)
        html = render_proposal_html(self.proposal)
        self.assertIn("Pix", html)
        self.assertIn("Boleto", html)

    def test_docx_render_shows_inactive_method(self):
        """Antes do RV05-H este teste falharia (DOCX filtrava is_active=True)."""
        import zipfile, io as _io
        self._deactivate(self.boleto)
        docx_bytes = render_proposal_docx(self.proposal)
        z = zipfile.ZipFile(_io.BytesIO(docx_bytes))
        doc_xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        self.assertIn("Pix", doc_xml)
        self.assertIn("Boleto", doc_xml)  # AINDA aparece

    def test_active_forms_in_form_queryset_still_filtered(self):
        """No FORM (criação/edição de proposta), apenas formas ATIVAS aparecem
        como opção — só não some das propostas que já a vincularam."""
        from apps.proposals.forms import ProposalForm
        self._deactivate(self.boleto)
        f = ProposalForm(empresa=self.empresa)
        qs_slugs = list(f.fields["payment_methods"].queryset.values_list("slug", flat=True))
        self.assertIn("pix", qs_slugs)
        self.assertNotIn("boleto", qs_slugs)  # sumiu do form (não é uma opção válida nova)

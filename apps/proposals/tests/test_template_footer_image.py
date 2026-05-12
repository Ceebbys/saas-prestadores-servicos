"""Testes do RV05-F — ProposalTemplate.footer_image (paridade com header)."""
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from apps.proposals.models import Proposal, ProposalTemplate
from apps.proposals.services.render import build_proposal_context
from apps.crm.models import Lead
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _png(size=(60, 40)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color=(200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


class ProposalTemplateFooterImageTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("pf@t.com", "PF", self.empresa)
        create_pipeline_for_empresa(self.empresa)

    def test_template_has_footer_image_field(self):
        """Campo existe no modelo."""
        self.assertTrue(hasattr(ProposalTemplate, "footer_image"))

    def test_template_stores_footer_image(self):
        t = ProposalTemplate.objects.create(empresa=self.empresa, name="T")
        t.footer_image.save("tpl_footer.png", SimpleUploadedFile(
            "tpl_footer.png", _png(), content_type="image/png",
        ))
        t.refresh_from_db()
        self.assertTrue(bool(t.footer_image))
        self.assertIn("proposals/footers/", t.footer_image.name)

    def test_cascata_template_footer_to_proposal(self):
        """Se proposta não tem footer_image, herda do template."""
        t = ProposalTemplate.objects.create(empresa=self.empresa, name="T2")
        t.footer_image.save("cascata.png", SimpleUploadedFile(
            "cascata.png", _png(), content_type="image/png",
        ))
        lead = Lead.objects.create(empresa=self.empresa, name="L", email="l@l.com")
        p = Proposal.objects.create(
            empresa=self.empresa, lead=lead, template=t,
            title="P1", discount_percent=Decimal("0"),
        )
        ctx = build_proposal_context(p)
        self.assertTrue(ctx["footer_image_url"])
        self.assertIn("cascata", ctx["footer_image_url"])

    def test_proposal_footer_image_overrides_template(self):
        """Footer da proposta tem prioridade sobre o do template."""
        t = ProposalTemplate.objects.create(empresa=self.empresa, name="T3")
        t.footer_image.save("template.png", SimpleUploadedFile(
            "template.png", _png(), content_type="image/png",
        ))
        lead = Lead.objects.create(empresa=self.empresa, name="L2", email="l2@l.com")
        p = Proposal.objects.create(
            empresa=self.empresa, lead=lead, template=t,
            title="P2", discount_percent=Decimal("0"),
        )
        p.footer_image.save("proposal.png", SimpleUploadedFile(
            "proposal.png", _png(), content_type="image/png",
        ))
        ctx = build_proposal_context(p)
        self.assertIn("proposal", ctx["footer_image_url"])
        self.assertNotIn("template", ctx["footer_image_url"])

    def test_form_includes_footer_image(self):
        """settings_app.ProposalTemplateForm aceita upload de footer."""
        from apps.settings_app.forms import ProposalTemplateForm

        f = ProposalTemplateForm(
            data={"name": "X", "is_default": False, "default_payment_method": ""},
            files={"footer_image": SimpleUploadedFile(
                "f.png", _png(), content_type="image/png",
            )},
        )
        self.assertTrue(f.is_valid(), msg=f.errors)
        t = f.save(commit=False)
        t.empresa = self.empresa
        t.save()
        self.assertTrue(bool(t.footer_image))

    def test_form_rejects_invalid_footer_extension(self):
        from apps.settings_app.forms import ProposalTemplateForm

        f = ProposalTemplateForm(
            data={"name": "X", "is_default": False, "default_payment_method": ""},
            files={"footer_image": SimpleUploadedFile(
                "bad.exe", b"MZbinary", content_type="application/octet-stream",
            )},
        )
        self.assertFalse(f.is_valid())
        self.assertIn("footer_image", f.errors)

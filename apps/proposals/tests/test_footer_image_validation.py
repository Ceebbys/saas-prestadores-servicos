"""RV05-G — Validação de footer_image em ProposalForm (auditoria gap).

Cobre upload de footer_image válida, extensão inválida e tamanho excedido.
"""
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from apps.proposals.forms import ProposalForm
from apps.crm.models import Lead
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _png(size=(60, 40)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color=(100, 200, 50)).save(buf, format="PNG")
    return buf.getvalue()


class ProposalFooterImageValidationTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("fv@t.com", "FV", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="L", email="l@l.com",
        )

    def _form_data(self):
        return {
            "title": "P", "lead": str(self.lead.pk), "value": "1000",
            "introduction": "", "body": "<p>x</p>", "terms": "",
            "header_content": "", "footer_content": "",
            "discount_percent": "0",
        }

    def test_valid_footer_image_accepted(self):
        form = ProposalForm(
            data=self._form_data(),
            files={"footer_image": SimpleUploadedFile(
                "ok.png", _png(), content_type="image/png",
            )},
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), msg=form.errors)

    def test_invalid_extension_rejected(self):
        form = ProposalForm(
            data=self._form_data(),
            files={"footer_image": SimpleUploadedFile(
                "evil.exe", b"MZbinary content",
                content_type="application/octet-stream",
            )},
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("footer_image", form.errors)

    def test_oversized_image_rejected(self):
        """Imagem > 2MB deve ser rejeitada."""
        from apps.core.document_render.image_validation import MAX_DOCUMENT_IMAGE_BYTES
        # Cria conteúdo claramente maior que o limite
        big = b"x" * (MAX_DOCUMENT_IMAGE_BYTES + 1000)
        form = ProposalForm(
            data=self._form_data(),
            files={"footer_image": SimpleUploadedFile(
                "big.png", big, content_type="image/png",
            )},
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("footer_image", form.errors)

    def test_no_footer_image_is_ok(self):
        """Form deve aceitar sem footer (campo opcional)."""
        form = ProposalForm(
            data=self._form_data(), empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), msg=form.errors)

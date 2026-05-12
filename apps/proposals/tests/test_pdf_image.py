"""Regression test: bug 500 ao inserir imagem no cabeçalho da proposta.

Causa raiz era `settings.STORAGES["default"]` ausente (Django 5+).
Esse teste garante que upload de header_image não dispara 500.
"""
import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.crm.models import Lead
from apps.proposals.models import Proposal
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _make_png_bytes(size=(100, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(80, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _make_webp_bytes(size=(100, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(80, 120, 200)).save(buf, format="WEBP")
    return buf.getvalue()


class HeaderImageUploadTests(TestCase):
    """Garante que upload no header_image salva sem 500."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("hi@t.com", "HI", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="HI Lead")
        self.client.force_login(self.user)

    def test_upload_png_to_existing_proposal(self):
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="Bug500 PNG", discount_percent=Decimal("0"),
        )
        image = SimpleUploadedFile(
            "logo.png", _make_png_bytes(), content_type="image/png",
        )
        url = reverse("proposals:edit", args=[p.pk])
        resp = self.client.post(url, data={
            "title": p.title,
            "lead": str(self.lead.pk),
            "introduction": "",
            "body": "",
            "terms": "",
            "discount_percent": "0",
            "header_image": image,
        })
        # Esperamos redirect (302) — NÃO 500
        self.assertIn(resp.status_code, (302, 303),
                      msg=f"Esperava redirect, recebeu {resp.status_code}: {resp.content[:200]!r}")
        p.refresh_from_db()
        self.assertTrue(p.header_image, "header_image deveria estar salvo")

    def test_upload_webp_aceito(self):
        """WEBP está na allowlist e deve passar pela validação."""
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="Bug500 WEBP", discount_percent=Decimal("0"),
        )
        image = SimpleUploadedFile(
            "logo.webp", _make_webp_bytes(), content_type="image/webp",
        )
        url = reverse("proposals:edit", args=[p.pk])
        resp = self.client.post(url, data={
            "title": p.title, "lead": str(self.lead.pk),
            "introduction": "", "body": "", "terms": "",
            "discount_percent": "0", "header_image": image,
        })
        self.assertIn(resp.status_code, (302, 303))

    def test_upload_invalid_extension_rejected_with_400_friendly(self):
        """Extensão fora da allowlist → form error, NÃO 500."""
        p = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="Bug500 Invalid", discount_percent=Decimal("0"),
        )
        evil = SimpleUploadedFile(
            "evil.exe", b"\x4D\x5A" + b"\x00" * 100,  # DOS header
            content_type="application/x-msdownload",
        )
        url = reverse("proposals:edit", args=[p.pk])
        resp = self.client.post(url, data={
            "title": p.title, "lead": str(self.lead.pk),
            "introduction": "", "body": "", "terms": "",
            "discount_percent": "0", "header_image": evil,
        })
        # O critério essencial: NÃO 500. Form invalid re-renderiza (200) ou
        # redireciona com mensagem (302). Qualquer um é aceitável.
        self.assertIn(
            resp.status_code, (200, 302),
            msg=f"Esperava 200/302 (form invalid), recebeu {resp.status_code}",
        )
        # Garante que o arquivo .exe NÃO foi salvo no banco
        p.refresh_from_db()
        self.assertFalse(
            p.header_image and p.header_image.name.endswith(".exe"),
            "Arquivo .exe não deveria ter sido salvo",
        )

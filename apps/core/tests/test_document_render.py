"""Testes da camada compartilhada de render de documentos."""
import io
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.core.document_render.pdf import media_url_fetcher


class MediaUrlFetcherTests(TestCase):
    """media_url_fetcher resolve /media/* via storage e bloqueia esquemas perigosos."""

    def test_blocks_file_scheme(self):
        with self.assertRaises(ValueError) as ctx:
            media_url_fetcher("file:///etc/passwd")
        self.assertIn("Esquema bloqueado", str(ctx.exception))

    def test_blocks_ftp_scheme(self):
        with self.assertRaises(ValueError):
            media_url_fetcher("ftp://internal.host/secret")

    def test_blocks_data_non_image(self):
        with self.assertRaises(ValueError):
            media_url_fetcher("data:text/html,<script>alert(1)</script>")

    def test_allows_data_image(self):
        # Deve delegar pro default_url_fetcher do WeasyPrint
        with patch("weasyprint.urls.default_url_fetcher") as mock_default:
            mock_default.return_value = {"file_obj": io.BytesIO(b"x"), "mime_type": "image/png"}
            result = media_url_fetcher("data:image/png;base64,iVBORw0K")
            self.assertIn("file_obj", result)
            mock_default.assert_called_once()

    def test_resolves_media_via_storage(self):
        # Mocka o default_storage para simular arquivo existente
        with patch("apps.core.document_render.pdf.default_storage") as mock_storage:
            mock_storage.exists.return_value = True
            mock_storage.open.return_value = io.BytesIO(b"PNG-BYTES")
            result = media_url_fetcher("/media/proposals/headers/1/logo.png")
            self.assertEqual(result["mime_type"], "image/png")
            self.assertEqual(result["file_obj"].read(), b"PNG-BYTES")
            mock_storage.exists.assert_called_once_with(
                "proposals/headers/1/logo.png"
            )

    def test_media_missing_falls_through_to_default(self):
        with patch("apps.core.document_render.pdf.default_storage") as mock_storage, \
             patch("weasyprint.urls.default_url_fetcher") as mock_default:
            mock_storage.exists.return_value = False
            mock_default.return_value = {"file_obj": io.BytesIO(b""), "mime_type": "image/png"}
            media_url_fetcher("/media/missing.png")
            mock_default.assert_called_once()

    def test_external_http_delegates_to_default(self):
        with patch("weasyprint.urls.default_url_fetcher") as mock_default:
            mock_default.return_value = {"file_obj": io.BytesIO(b"x"), "mime_type": "image/png"}
            media_url_fetcher("https://example.com/img.png")
            mock_default.assert_called_once_with("https://example.com/img.png")


class RenderHtmlToPdfTests(TestCase):
    """render_html_to_pdf gera PDF válido."""

    def test_simple_html_produces_pdf_magic(self):
        try:
            from apps.core.document_render.pdf import render_html_to_pdf
            pdf = render_html_to_pdf("<p>hello</p>")
        except OSError as exc:
            # WeasyPrint sem libs nativas (Windows sem GTK) — skip
            self.skipTest(f"WeasyPrint libs nativas indisponíveis: {exc}")
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf[-512:])

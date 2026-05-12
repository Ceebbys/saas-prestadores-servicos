"""Testes da camada compartilhada de render de documentos."""
import io
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from apps.core.document_render.pdf import media_url_fetcher
from apps.core.document_render.sanitizer import sanitize_rich_html, SAFE_STYLE_PROPS
from apps.core.document_render.image_validation import validate_document_image


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

    def test_resolves_media_via_storage_with_localhost_netloc(self):
        # WeasyPrint após urljoin com DEFAULT_BASE_URL transforma /media/x.png em
        # http://localhost/media/x.png. Fetcher precisa aceitar ambos.
        with patch("apps.core.document_render.pdf.default_storage") as mock_storage:
            mock_storage.exists.return_value = True
            mock_storage.open.return_value = io.BytesIO(b"DATA")
            result = media_url_fetcher("http://localhost/media/proposals/headers/1/logo.png")
            self.assertEqual(result["file_obj"].read(), b"DATA")

    def test_external_host_with_media_path_does_not_read_local(self):
        # SSRF defense: https://attacker.com/media/x.png NÃO resolve via storage local.
        with patch("apps.core.document_render.pdf.default_storage") as mock_storage, \
             patch("weasyprint.urls.default_url_fetcher") as mock_default:
            mock_default.return_value = {"file_obj": io.BytesIO(b""), "mime_type": "image/png"}
            media_url_fetcher("https://attacker.com/media/secret.png")
            # storage NÃO deve ser tocado para hosts externos
            mock_storage.exists.assert_not_called()
            mock_default.assert_called_once()


class MakeMediaUrlFetcherTests(TestCase):
    """Factory `_make_media_url_fetcher` permite host do request como interno."""

    def test_includes_request_host_in_allowed_set(self):
        from apps.core.document_render.pdf import _make_media_url_fetcher
        fetcher = _make_media_url_fetcher(frozenset({"servicos.cebs-server.cloud"}))
        with patch("apps.core.document_render.pdf.default_storage") as mock_storage:
            mock_storage.exists.return_value = True
            mock_storage.open.return_value = io.BytesIO(b"DATA")
            result = fetcher("https://servicos.cebs-server.cloud/media/proposals/headers/1/logo.png")
            self.assertEqual(result["file_obj"].read(), b"DATA")

    def test_factory_still_blocks_external_attacker(self):
        from apps.core.document_render.pdf import _make_media_url_fetcher
        fetcher = _make_media_url_fetcher(frozenset({"servicos.cebs-server.cloud"}))
        with patch("apps.core.document_render.pdf.default_storage") as mock_storage, \
             patch("weasyprint.urls.default_url_fetcher") as mock_default:
            mock_default.return_value = {"file_obj": io.BytesIO(b""), "mime_type": "image/png"}
            # Host externo — não passa pelo storage
            fetcher("https://attacker.com/media/secret.png")
            mock_storage.exists.assert_not_called()
            mock_default.assert_called_once()

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


class SanitizerRichHtmlTests(TestCase):
    """sanitize_rich_html preserva formatação Quill segura, bloqueia CSS perigoso."""

    def test_preserves_font_family(self):
        html = '<p><span style="font-family: Arial;">Arial text</span></p>'
        clean = sanitize_rich_html(html)
        self.assertIn("font-family", clean)
        self.assertIn("Arial", clean)

    def test_preserves_font_size(self):
        html = '<p><span style="font-size: 18px;">Grande</span></p>'
        clean = sanitize_rich_html(html)
        self.assertIn("font-size", clean)
        self.assertIn("18px", clean)

    def test_blocks_background_url_javascript(self):
        # CSS injection clássico — antes do RV05, style era preservado cru.
        # Agora `filter_style_properties` remove background-image.
        html = '<p style="background:url(javascript:alert(1))">Texto</p>'
        clean = sanitize_rich_html(html)
        self.assertNotIn("javascript:", clean)
        self.assertNotIn("background:", clean)
        # Texto preservado
        self.assertIn("Texto", clean)

    def test_blocks_position_absolute(self):
        # Defesa: posicionamento absoluto pode quebrar UI
        html = '<p style="position: absolute; top: 0;">Hijack</p>'
        clean = sanitize_rich_html(html)
        self.assertNotIn("position", clean)
        self.assertNotIn("absolute", clean)

    def test_preserves_text_align_center(self):
        html = '<p style="text-align: center;">Centro</p>'
        clean = sanitize_rich_html(html)
        self.assertIn("text-align", clean)
        self.assertIn("center", clean)

    def test_strips_script_tags(self):
        html = '<p>OK</p><script>alert(1)</script>'
        clean = sanitize_rich_html(html)
        self.assertNotIn("script", clean)
        self.assertNotIn("alert", clean)

    def test_empty_returns_empty(self):
        self.assertEqual(sanitize_rich_html(""), "")
        self.assertEqual(sanitize_rich_html(None), "")

    def test_legacy_proposal_alias_works(self):
        """O alias antigo sanitize_proposal_html ainda funciona (compat)."""
        from apps.proposals.sanitizer import sanitize_proposal_html
        self.assertEqual(sanitize_proposal_html(""), "")
        html = '<p><strong>oi</strong></p>'
        self.assertIn("<strong>", sanitize_proposal_html(html))


class ImageValidationTests(TestCase):
    """validate_document_image: extensão + tamanho."""

    def test_accepts_png(self):
        f = MagicMock(name="logo.png", size=100_000)
        f.name = "logo.png"
        validate_document_image(f)  # não levanta

    def test_accepts_webp(self):
        f = MagicMock()
        f.name = "logo.webp"
        f.size = 100_000
        validate_document_image(f)

    def test_rejects_exe(self):
        f = MagicMock()
        f.name = "evil.exe"
        f.size = 100
        with self.assertRaises(ValidationError):
            validate_document_image(f)

    def test_rejects_oversized(self):
        f = MagicMock()
        f.name = "huge.png"
        f.size = 5 * 1024 * 1024  # 5MB
        with self.assertRaises(ValidationError):
            validate_document_image(f)

    def test_none_passes_through(self):
        # Campo opcional sem imagem
        self.assertIsNone(validate_document_image(None))

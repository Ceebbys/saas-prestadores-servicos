"""Testes de sanitização de HTML rich-text de propostas."""
from django.test import TestCase

from apps.proposals.sanitizer import sanitize_proposal_html


class SanitizerTests(TestCase):
    """Garante que tags perigosas são removidas e formatação válida preservada."""

    def test_strips_script_tags(self):
        dirty = '<p>Olá</p><script>alert("xss")</script>'
        clean = sanitize_proposal_html(dirty)
        self.assertNotIn("<script", clean)
        self.assertNotIn("alert", clean)
        self.assertIn("<p>Olá</p>", clean)

    def test_strips_event_handlers(self):
        dirty = '<p onclick="alert(1)">Texto</p>'
        clean = sanitize_proposal_html(dirty)
        self.assertNotIn("onclick", clean)
        self.assertIn("Texto", clean)

    def test_strips_img_with_onerror(self):
        dirty = '<img src=x onerror="alert(1)">'
        clean = sanitize_proposal_html(dirty)
        self.assertNotIn("onerror", clean)
        # img não está na allowlist, deve ser removida toda
        self.assertNotIn("<img", clean)

    def test_preserves_alignment(self):
        html = '<p style="text-align: center;">Centro</p>'
        clean = sanitize_proposal_html(html)
        self.assertIn("text-align", clean)
        self.assertIn("Centro", clean)

    def test_preserves_basic_formatting(self):
        html = "<p><strong>Negrito</strong> e <em>itálico</em></p>"
        clean = sanitize_proposal_html(html)
        self.assertIn("<strong>", clean)
        self.assertIn("<em>", clean)

    def test_preserves_lists(self):
        html = "<ol><li>Um</li><li>Dois</li></ol><ul><li>A</li></ul>"
        clean = sanitize_proposal_html(html)
        self.assertIn("<ol>", clean)
        self.assertIn("<ul>", clean)
        self.assertIn("<li>Um</li>", clean)

    def test_preserves_quill_size_class(self):
        # Quill 2.x usa style="font-size: 18px"
        html = '<p><span style="font-size: 18px;">Grande</span></p>'
        clean = sanitize_proposal_html(html)
        self.assertIn("font-size", clean)

    def test_links_get_safe_rel(self):
        html = '<a href="https://example.com">link</a>'
        clean = sanitize_proposal_html(html)
        self.assertIn("href", clean)
        self.assertIn("noopener", clean)

    def test_javascript_links_stripped(self):
        html = '<a href="javascript:alert(1)">click</a>'
        clean = sanitize_proposal_html(html)
        self.assertNotIn("javascript:", clean)

    def test_empty_returns_empty(self):
        self.assertEqual(sanitize_proposal_html(""), "")
        self.assertEqual(sanitize_proposal_html(None), "")

    def test_plain_text_passes_through(self):
        text = "Texto sem nenhum HTML"
        clean = sanitize_proposal_html(text)
        self.assertIn("Texto sem nenhum HTML", clean)

"""Teste do shim deprecated `apps.proposals.sanitizer`.

A lógica do sanitizer foi extraída para `apps.core.document_render.sanitizer`
em RV05 FASE 2. Os testes de comportamento ficaram em
`apps/core/tests/test_document_render.py::SanitizerRichHtmlTests`.

Aqui ficam apenas testes de compatibilidade do shim: garantir que o
alias antigo (`sanitize_proposal_html`) continua importável e funcional
para código legado que ainda referencia o caminho antigo.

Drop do shim previsto para RV06 (depois que todos os importadores
migrarem para o core).
"""
from django.test import TestCase


class ProposalSanitizerShimTests(TestCase):
    """Verifica que o alias deprecated continua funcional."""

    def test_alias_importable(self):
        """`sanitize_proposal_html` continua importável do caminho antigo."""
        from apps.proposals.sanitizer import sanitize_proposal_html
        self.assertTrue(callable(sanitize_proposal_html))

    def test_alias_delegates_to_core(self):
        """Alias é o mesmo objeto que `sanitize_rich_html` do core."""
        from apps.proposals.sanitizer import sanitize_proposal_html
        from apps.core.document_render.sanitizer import sanitize_rich_html
        self.assertIs(sanitize_proposal_html, sanitize_rich_html)

    def test_alias_strips_script_basic_smoke(self):
        """Smoke: o alias ainda sanitiza corretamente."""
        from apps.proposals.sanitizer import sanitize_proposal_html
        out = sanitize_proposal_html('<p>OK</p><script>x</script>')
        self.assertIn("<p>OK</p>", out)
        self.assertNotIn("script", out)

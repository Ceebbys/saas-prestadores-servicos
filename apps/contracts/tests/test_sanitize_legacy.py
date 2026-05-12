"""Testes do RV05-F — Migration sanitize_legacy_content (idempotência + segurança)."""
import importlib
from decimal import Decimal

from django.test import TestCase

from apps.contracts.models import Contract, ContractTemplate
from apps.crm.models import Lead
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _import_sanitize():
    """Importa o módulo de migration (nome começa com dígitos — precisa importlib)."""
    mod = importlib.import_module(
        "apps.contracts.migrations.0005_sanitize_legacy_content"
    )
    return mod._sanitize_html_inplace, mod.sanitize_and_copy_legacy_content


class SanitizeLegacyContentTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("sl@t.com", "SL", self.empresa)
        create_pipeline_for_empresa(self.empresa)

    def test_sanitize_helper_removes_scripts(self):
        sanitize, _ = _import_sanitize()
        out = sanitize("<p>OK</p><script>alert(1)</script>")
        self.assertIn("<p>OK</p>", out)
        self.assertNotIn("script", out)

    def test_sanitize_helper_empty_input(self):
        sanitize, _ = _import_sanitize()
        self.assertEqual(sanitize(""), "")
        self.assertEqual(sanitize(None), "")  # type: ignore

    def test_runpython_copies_content_to_body(self):
        """Simula contract antigo com content rich e body vazio."""
        _, run = _import_sanitize()
        from django.apps import apps as django_apps

        lead = Lead.objects.create(empresa=self.empresa, name="Legacy", email="l@l.com")
        c = Contract.objects.create(
            empresa=self.empresa, lead=lead,
            title="Legado",
            content="<p>Conteúdo antigo</p><script>evil</script>",
            body="",
            value=Decimal("500"),
        )
        # Roda manualmente o RunPython operativo
        run(django_apps, None)
        c.refresh_from_db()
        self.assertIn("<p>", c.body)
        self.assertNotIn("script", c.body)
        # Content legado preservado para auditoria
        self.assertIn("Conteúdo antigo", c.content)

    def test_runpython_idempotent(self):
        """Rodar duas vezes não altera body já preenchido."""
        _, run = _import_sanitize()
        from django.apps import apps as django_apps

        lead = Lead.objects.create(empresa=self.empresa, name="Idem", email="i@i.com")
        c = Contract.objects.create(
            empresa=self.empresa, lead=lead,
            title="Idem",
            content="<p>X</p>",
            body="",
            value=Decimal("100"),
        )
        run(django_apps, None)
        c.refresh_from_db()
        body_after_first = c.body
        # Modifica content; segunda execução não deve mexer (body já não está vazio)
        c.content = "<p>Y</p><script>bad</script>"
        c.save(update_fields=["content"])
        run(django_apps, None)
        c.refresh_from_db()
        self.assertEqual(c.body, body_after_first)

    def test_runpython_skips_if_body_already_set(self):
        """Body já preenchido não é sobrescrito."""
        _, run = _import_sanitize()
        from django.apps import apps as django_apps

        lead = Lead.objects.create(empresa=self.empresa, name="K", email="k@k.com")
        c = Contract.objects.create(
            empresa=self.empresa, lead=lead,
            title="Keep",
            content="<p>OLD</p>",
            body="<p>NEW</p>",
            value=Decimal("100"),
        )
        run(django_apps, None)
        c.refresh_from_db()
        self.assertEqual(c.body, "<p>NEW</p>")

    def test_runpython_handles_template(self):
        """Funciona também para ContractTemplate."""
        _, run = _import_sanitize()
        from django.apps import apps as django_apps

        t = ContractTemplate.objects.create(
            empresa=self.empresa, name="T1",
            content="<p>Template legado</p><script>x</script>",
            body="",
        )
        run(django_apps, None)
        t.refresh_from_db()
        self.assertIn("Template legado", t.body)
        self.assertNotIn("script", t.body)

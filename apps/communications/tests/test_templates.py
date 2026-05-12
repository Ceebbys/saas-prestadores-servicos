"""Testes de MessageTemplate + render service + endpoints API."""
from __future__ import annotations

import json

from django.test import TestCase
from django.urls import reverse

from apps.communications.models import (
    Conversation,
    MessageTemplate,
    get_or_create_conversation,
)
from apps.contacts.models import Contato
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead


class TemplateModelTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("u@t.com", "U", self.empresa)

    def test_shortcut_normalizes_to_lower_no_slash(self):
        t = MessageTemplate.objects.create(
            empresa=self.empresa,
            name="Saudação", content="Olá",
            shortcut="/Olá-Cli ente",
        )
        # Slash removido, lowercase, espaços viram _
        self.assertNotIn("/", t.shortcut)
        self.assertEqual(t.shortcut, "olá-cli_ente")

    def test_unique_shortcut_per_empresa(self):
        MessageTemplate.objects.create(
            empresa=self.empresa, name="A", content="x", shortcut="a",
        )
        with self.assertRaises(Exception):
            MessageTemplate.objects.create(
                empresa=self.empresa, name="B", content="y", shortcut="a",
            )

    def test_shortcut_unique_only_when_non_empty(self):
        # 2 templates sem shortcut, mesma empresa → OK
        MessageTemplate.objects.create(empresa=self.empresa, name="A", content="x")
        MessageTemplate.objects.create(empresa=self.empresa, name="B", content="y")
        self.assertEqual(MessageTemplate.objects.filter(empresa=self.empresa).count(), 2)


class TemplateRenderTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(name="ServiçoPro", slug="sp")
        self.user = create_test_user("at@t.com", "Atendente", self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="João Silva", email="j@cli.com",
        )
        self.conv = get_or_create_conversation(self.empresa, self.lead)

    def test_render_lead_name(self):
        from apps.communications.templates_service import render_template
        tpl = MessageTemplate.objects.create(
            empresa=self.empresa, name="Saud",
            content="Olá {{ lead.name }}!",
        )
        result = render_template(tpl, conversation=self.conv)
        self.assertEqual(result, "Olá João Silva!")

    def test_render_empresa_name(self):
        from apps.communications.templates_service import render_template
        tpl = MessageTemplate.objects.create(
            empresa=self.empresa, name="Emp",
            content="Atenciosamente, {{ empresa.name }}",
        )
        result = render_template(tpl, conversation=self.conv)
        self.assertEqual(result, "Atenciosamente, ServiçoPro")

    def test_render_user_first_name(self):
        from apps.communications.templates_service import render_template
        tpl = MessageTemplate.objects.create(
            empresa=self.empresa, name="User",
            content="Falou {{ user.first_name_display }}!",
        )
        result = render_template(tpl, conversation=self.conv, user=self.user)
        self.assertEqual(result, "Falou Atendente!")

    def test_render_now_date(self):
        from apps.communications.templates_service import render_template
        tpl = MessageTemplate.objects.create(
            empresa=self.empresa, name="Date",
            content="Hoje é {{ now.date }}",
        )
        result = render_template(tpl, conversation=self.conv)
        # Não checamos a data exata, mas o formato dd/mm/yyyy
        import re
        self.assertRegex(result, r"Hoje é \d{2}/\d{2}/\d{4}")

    def test_render_missing_var_becomes_empty(self):
        from apps.communications.templates_service import render_template
        tpl = MessageTemplate.objects.create(
            empresa=self.empresa, name="Miss",
            content="Olá {{ inexistente.foo }}!",
        )
        result = render_template(tpl, conversation=self.conv)
        self.assertEqual(result, "Olá !")

    def test_sandbox_blocks_dunder_access(self):
        from apps.communications.templates_service import render_template
        tpl = MessageTemplate.objects.create(
            empresa=self.empresa, name="Attack",
            content="{{ lead.__class__.__name__ }}",
        )
        result = render_template(tpl, conversation=self.conv)
        # Sandbox bloqueia __class__ → resultado vazio (não devolve "Lead")
        self.assertEqual(result, "")

    def test_render_and_track_increments_usage_count(self):
        from apps.communications.templates_service import render_and_track
        tpl = MessageTemplate.objects.create(
            empresa=self.empresa, name="Track",
            content="Oi",
        )
        self.assertEqual(tpl.usage_count, 0)
        render_and_track(tpl, conversation=self.conv)
        tpl.refresh_from_db()
        self.assertEqual(tpl.usage_count, 1)
        render_and_track(tpl, conversation=self.conv)
        tpl.refresh_from_db()
        self.assertEqual(tpl.usage_count, 2)

    def test_contato_via_lead(self):
        from apps.communications.templates_service import render_template
        contato = Contato.objects.create(
            empresa=self.empresa, name="Empresa do João",
            email="ej@cli.com",
        )
        self.lead.contato = contato
        self.lead.save()
        tpl = MessageTemplate.objects.create(
            empresa=self.empresa, name="Cont",
            content="Conta: {{ contato.name }}",
        )
        result = render_template(tpl, conversation=self.conv)
        self.assertEqual(result, "Conta: Empresa do João")


class TemplateAPITests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("api@t.com", "API", self.empresa)
        self.client.force_login(self.user)
        self.lead = Lead.objects.create(empresa=self.empresa, name="Cliente")
        self.conv = get_or_create_conversation(self.empresa, self.lead)
        for i, name in enumerate(["Saudação", "Preço", "Encerramento"]):
            MessageTemplate.objects.create(
                empresa=self.empresa, name=name,
                shortcut=name.lower()[:5],
                content=f"Conteúdo {name}",
            )

    def test_search_returns_active_templates(self):
        resp = self.client.get(reverse("communications:template_search"))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        names = [t["name"] for t in data["templates"]]
        self.assertEqual(set(names), {"Saudação", "Preço", "Encerramento"})

    def test_search_filters_by_query(self):
        resp = self.client.get(reverse("communications:template_search") + "?q=preco")
        # "preco" no shortcut "preço"... actually shortcut starts with 'preço'[:5]='preço'
        # Mais simples: busca por "saud"
        resp = self.client.get(reverse("communications:template_search") + "?q=saud")
        data = json.loads(resp.content)
        names = [t["name"] for t in data["templates"]]
        self.assertIn("Saudação", names)
        self.assertNotIn("Encerramento", names)

    def test_search_cross_tenant_blocked(self):
        other = create_test_empresa("Other", "o")
        MessageTemplate.objects.create(
            empresa=other, name="Estrangeiro", content="x",
        )
        resp = self.client.get(reverse("communications:template_search"))
        data = json.loads(resp.content)
        names = [t["name"] for t in data["templates"]]
        self.assertNotIn("Estrangeiro", names)

    def test_render_endpoint(self):
        tpl = MessageTemplate.objects.create(
            empresa=self.empresa, name="Render",
            content="Olá {{ lead.name }}!",
        )
        resp = self.client.get(reverse(
            "communications:template_render", args=[tpl.pk, self.conv.pk],
        ))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data["rendered"], "Olá Cliente!")
        self.assertEqual(data["template_id"], tpl.pk)
        # Usage count incrementado
        tpl.refresh_from_db()
        self.assertEqual(tpl.usage_count, 1)

    def test_render_cross_tenant_blocked(self):
        other = create_test_empresa("Other", "o")
        tpl_other = MessageTemplate.objects.create(
            empresa=other, name="Outro", content="x",
        )
        resp = self.client.get(reverse(
            "communications:template_render", args=[tpl_other.pk, self.conv.pk],
        ))
        self.assertEqual(resp.status_code, 404)


class TemplateCRUDViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client.force_login(self.user)

    def test_list_view(self):
        MessageTemplate.objects.create(
            empresa=self.empresa, name="Test", content="x",
        )
        resp = self.client.get(reverse("communications:template_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test")

    def test_create_view(self):
        resp = self.client.post(
            reverse("communications:template_create"),
            data={
                "name": "Novo",
                "shortcut": "n",
                "category": "greeting",
                "channel": "any",
                "content": "Olá {{ lead.name }}",
                "is_active": "on",
            },
        )
        # Sucesso = redirect 302
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            MessageTemplate.objects.filter(empresa=self.empresa, name="Novo").exists()
        )

    def test_update_view(self):
        t = MessageTemplate.objects.create(
            empresa=self.empresa, name="Original", content="x",
        )
        resp = self.client.post(
            reverse("communications:template_update", args=[t.pk]),
            data={
                "name": "Editado",
                "shortcut": "",
                "category": "other",
                "channel": "any",
                "content": "x novo",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        t.refresh_from_db()
        self.assertEqual(t.name, "Editado")

    def test_delete_view(self):
        t = MessageTemplate.objects.create(
            empresa=self.empresa, name="DeleteMe", content="x",
        )
        resp = self.client.post(
            reverse("communications:template_delete", args=[t.pk]),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(MessageTemplate.objects.filter(pk=t.pk).exists())

    def test_cross_tenant_isolation(self):
        other_e = create_test_empresa("Other", "o")
        other_t = MessageTemplate.objects.create(
            empresa=other_e, name="NotMine", content="x",
        )
        resp = self.client.get(
            reverse("communications:template_update", args=[other_t.pk]),
        )
        self.assertEqual(resp.status_code, 404)

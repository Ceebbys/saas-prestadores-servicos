"""RV06 — Tests do helper de render de variáveis em mensagens do chatbot.

Cliente pediu: 'colocar para buscar coisas ja cadastradas no sistema,
no meu caso eu quero q ele busque o serviço q o cara selecionou'.
Renderiza {{ lead.name }}, {{ servico.name }}, {{ empresa.name }} etc.
"""
from decimal import Decimal

from django.test import TestCase

from apps.chatbot.builder.services.text_renderer import (
    AVAILABLE_VARIABLES, render_chatbot_text,
)
from apps.chatbot.models import ChatbotFlow, ChatbotSession
from apps.core.tests.helpers import create_test_empresa
from apps.crm.models import Lead
from apps.operations.models import ServiceType


class RenderChatbotTextTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-tpl", name="Mapper")
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="whatsapp",
        )
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="João Silva", phone="11999990000",
            email="joao@email.com",
        )
        self.svc = ServiceType.objects.create(
            empresa=self.empresa, name="Topografia Premium",
            default_price=Decimal("5500.00"), default_prazo_dias=14,
            default_description="Levantamento topográfico completo",
        )
        self.session = ChatbotSession.objects.create(
            flow=self.flow, sender_id="11999990000", lead=self.lead,
            lead_data={
                "servico_id": self.svc.pk,
                "servico_snapshot": {
                    "id": self.svc.pk,
                    "name": "Topografia Premium",
                    "default_description": "Levantamento topográfico completo",
                    "default_price": "5500.00",
                    "default_prazo_dias": 14,
                },
            },
        )

    def test_renders_lead_name(self):
        out = render_chatbot_text("Olá {{ lead.name }}!", self.session)
        self.assertEqual(out, "Olá João Silva!")

    def test_renders_servico_name(self):
        out = render_chatbot_text(
            "Perfeito! Você selecionou: {{ servico.name }} 🎯",
            self.session,
        )
        self.assertEqual(out, "Perfeito! Você selecionou: Topografia Premium 🎯")

    def test_renders_servico_price_and_prazo(self):
        out = render_chatbot_text(
            "R$ {{ servico.price }} em {{ servico.prazo_dias }} dias",
            self.session,
        )
        self.assertEqual(out, "R$ 5500.00 em 14 dias")

    def test_renders_servico_description(self):
        out = render_chatbot_text(
            "Descrição: {{ servico.description }}",
            self.session,
        )
        self.assertEqual(out, "Descrição: Levantamento topográfico completo")

    def test_renders_empresa_name(self):
        out = render_chatbot_text(
            "Bem-vindo à {{ empresa.name }}!", self.session,
        )
        self.assertEqual(out, "Bem-vindo à Mapper!")

    def test_renders_multiple_vars(self):
        template = (
            "Olá {{ lead.name }}, na {{ empresa.name }}, "
            "{{ servico.name }} sai por R$ {{ servico.price }}"
        )
        out = render_chatbot_text(template, self.session)
        self.assertIn("João Silva", out)
        self.assertIn("Mapper", out)
        self.assertIn("Topografia Premium", out)
        self.assertIn("5500.00", out)

    def test_missing_variable_renders_empty(self):
        """Variável inexistente → vazio, sem quebrar."""
        out = render_chatbot_text(
            "{{ servico.nao_existe }}", self.session,
        )
        self.assertEqual(out, "")

    def test_no_template_tag_returns_original(self):
        """Texto sem {{ }} retorna o texto original (perf optimization)."""
        out = render_chatbot_text("Olá mundo", self.session)
        self.assertEqual(out, "Olá mundo")

    def test_empty_text(self):
        self.assertEqual(render_chatbot_text("", self.session), "")
        self.assertEqual(render_chatbot_text(None, self.session), "")

    def test_simulator_state_dict_works(self):
        """Aceita dict no formato do simulator (state) também."""
        state = {
            "lead_data": {
                "name": "Maria",
                "servico_snapshot": {
                    "name": "Express",
                    "default_price": "1500.00",
                    "default_prazo_dias": 3,
                },
            },
        }
        out = render_chatbot_text(
            "Olá! {{ servico.name }} sai por R$ {{ servico.price }}.",
            state,
        )
        self.assertEqual(out, "Olá! Express sai por R$ 1500.00.")

    def test_available_variables_list_exposed(self):
        """AVAILABLE_VARIABLES contém pelo menos lead.name e servico.name."""
        paths = [v["path"] for v in AVAILABLE_VARIABLES]
        self.assertIn("lead.name", paths)
        self.assertIn("servico.name", paths)
        self.assertIn("servico.price", paths)
        self.assertIn("empresa.name", paths)

    def test_real_world_template(self):
        """Cenário exato do print do cliente."""
        template = (
            "Perfeito! 👍 Você selecionou: 📌 {{ servico.name }} "
            "🎁 O que está incluso: {{ servico.description }}"
        )
        out = render_chatbot_text(template, self.session)
        self.assertIn("Topografia Premium", out)
        self.assertIn("Levantamento topográfico completo", out)

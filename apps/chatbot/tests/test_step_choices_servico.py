"""Bug reportado em prod: dropdown 'Serviço associado' vazio no editor
legacy de choices.

Causa: StepChoicesEditView._get_form_kwargs_for_choices populava apenas
o queryset de 'next_step', deixando 'servico' como
ServiceType.objects.none() (fallback do ChatbotChoiceForm quando
flow=None — e o inlineformset_factory não passa flow).

Cobertura:
- GET /step/<pk>/choices/edit/ retorna formset com queryset de servico
  contendo apenas serviços ATIVOS da empresa do flow
- Cross-tenant: serviços de outra empresa não aparecem
- Serviços inativos não aparecem
- POST salva ChatbotChoice.servico
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.chatbot.models import ChatbotChoice, ChatbotFlow, ChatbotStep
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.operations.models import ServiceType


class StepChoicesServicoQuerysetTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-servico-edit")
        self.user = create_test_user("svc@t.com", "SVC", self.empresa)
        self.client.force_login(self.user)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Test", channel="whatsapp",
        )
        self.step = ChatbotStep.objects.create(
            flow=self.flow, order=0, step_type="choice",
            question_text="Escolha:",
        )
        ChatbotChoice.objects.create(step=self.step, text="A", order=0)
        ChatbotChoice.objects.create(step=self.step, text="B", order=1)

        # Serviços da empresa: 2 ativos + 1 inativo
        self.s_ativo1 = ServiceType.objects.create(
            empresa=self.empresa, name="Topografia",
            default_price=Decimal("5500"), default_prazo_dias=14, is_active=True,
        )
        self.s_ativo2 = ServiceType.objects.create(
            empresa=self.empresa, name="Express",
            default_price=Decimal("1500"), default_prazo_dias=3, is_active=True,
        )
        self.s_inativo = ServiceType.objects.create(
            empresa=self.empresa, name="Inativo",
            default_price=Decimal("100"), default_prazo_dias=1, is_active=False,
        )
        # Serviço de OUTRA empresa (cross-tenant)
        self.outra_empresa = create_test_empresa(
            name="Outra Empresa", slug="rv06-svc-outra",
        )
        self.s_outra_empresa = ServiceType.objects.create(
            empresa=self.outra_empresa, name="Serviço outra empresa",
            default_price=Decimal("999"), default_prazo_dias=5, is_active=True,
        )

    def test_get_returns_formset_with_active_services(self):
        url = reverse(
            "chatbot:step_choices_edit",
            kwargs={"pk": self.flow.pk, "step_pk": self.step.pk},
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        formset = resp.context["formset"]
        for form in formset.forms:
            servico_qs = form.fields["servico"].queryset
            names = list(servico_qs.values_list("name", flat=True))
            # Os 2 ativos devem estar; o inativo e o de outra empresa NÃO
            self.assertIn("Topografia", names)
            self.assertIn("Express", names)
            self.assertNotIn("Inativo", names)
            self.assertNotIn("Serviço outra empresa", names)
            # Empty label customizada
            self.assertEqual(
                form.fields["servico"].empty_label, "— Sem serviço associado —",
            )

    def test_post_saves_servico_on_choice(self):
        url = reverse(
            "chatbot:step_choices_edit",
            kwargs={"pk": self.flow.pk, "step_pk": self.step.pk},
        )
        # Pega o formset GET pra extrair management_form e IDs
        get_resp = self.client.get(url)
        formset = get_resp.context["formset"]
        prefix = formset.prefix

        choice_a = ChatbotChoice.objects.get(step=self.step, text="A")
        choice_b = ChatbotChoice.objects.get(step=self.step, text="B")

        post_data = {
            f"{prefix}-TOTAL_FORMS": "2",
            f"{prefix}-INITIAL_FORMS": "2",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": str(choice_a.pk),
            f"{prefix}-0-step": str(self.step.pk),
            f"{prefix}-0-text": "A",
            f"{prefix}-0-order": "0",
            f"{prefix}-0-servico": str(self.s_ativo1.pk),
            f"{prefix}-1-id": str(choice_b.pk),
            f"{prefix}-1-step": str(self.step.pk),
            f"{prefix}-1-text": "B",
            f"{prefix}-1-order": "1",
            f"{prefix}-1-servico": str(self.s_ativo2.pk),
        }
        resp = self.client.post(url, post_data)
        self.assertIn(resp.status_code, (200, 302))

        # Confirma persistência
        choice_a.refresh_from_db()
        choice_b.refresh_from_db()
        self.assertEqual(choice_a.servico_id, self.s_ativo1.pk)
        self.assertEqual(choice_b.servico_id, self.s_ativo2.pk)

    def test_post_rejects_cross_tenant_servico(self):
        """Tentar associar serviço de outra empresa deve falhar (queryset
        não inclui ⇒ ChoiceField rejeita)."""
        url = reverse(
            "chatbot:step_choices_edit",
            kwargs={"pk": self.flow.pk, "step_pk": self.step.pk},
        )
        get_resp = self.client.get(url)
        formset = get_resp.context["formset"]
        prefix = formset.prefix

        choice_a = ChatbotChoice.objects.get(step=self.step, text="A")
        choice_b = ChatbotChoice.objects.get(step=self.step, text="B")

        post_data = {
            f"{prefix}-TOTAL_FORMS": "2",
            f"{prefix}-INITIAL_FORMS": "2",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": str(choice_a.pk),
            f"{prefix}-0-step": str(self.step.pk),
            f"{prefix}-0-text": "A",
            f"{prefix}-0-order": "0",
            f"{prefix}-0-servico": str(self.s_outra_empresa.pk),
            f"{prefix}-1-id": str(choice_b.pk),
            f"{prefix}-1-step": str(self.step.pk),
            f"{prefix}-1-text": "B",
            f"{prefix}-1-order": "1",
        }
        self.client.post(url, post_data)
        # Não deve ter persistido — fica None
        choice_a.refresh_from_db()
        self.assertIsNone(choice_a.servico_id)

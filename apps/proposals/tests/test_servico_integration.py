"""Testes de integração: Serviço Pré-Fixado ↔ Chatbot ↔ Lead ↔ Proposta."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.automation.services import create_lead_from_chatbot
from apps.chatbot.models import (
    ChatbotChoice,
    ChatbotFlow,
    ChatbotSession,
    ChatbotStep,
)
from apps.chatbot.services import process_response, start_session
from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.operations.models import ServiceType
from apps.proposals.models import Proposal
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _flow_with_choice(empresa, servico):
    flow = ChatbotFlow.objects.create(
        empresa=empresa, name="Servicos", channel="whatsapp", is_active=True,
    )
    step = ChatbotStep.objects.create(
        flow=flow, order=0, question_text="Qual serviço?",
        step_type=ChatbotStep.StepType.CHOICE,
        is_final=True,
    )
    ChatbotChoice.objects.create(
        step=step, text="Regularização", order=0, servico=servico,
    )
    return flow


class ChatbotChoiceServicoTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.servico = ServiceType.objects.create(
            empresa=self.empresa, name="Regularização",
            default_price=Decimal("4000.00"),
        )

    def test_choice_with_servico_writes_to_session(self):
        flow = _flow_with_choice(self.empresa, self.servico)
        s = start_session(flow, channel="webchat", sender_id="t1")
        process_response(s["session_key"], "1")
        sess = ChatbotSession.objects.get(session_key=s["session_key"])
        self.assertEqual(sess.lead_data.get("servico_id"), self.servico.pk)
        self.assertEqual(sess.lead_data.get("servico_name"), self.servico.name)


class LeadFromChatbotWithServicoTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_pipeline_for_empresa(self.empresa)
        self.servico = ServiceType.objects.create(
            empresa=self.empresa, name="Topografia",
            default_price=Decimal("2500.00"),
        )

    def test_lead_inherits_servico(self):
        lead = create_lead_from_chatbot(
            empresa=self.empresa, flow=None,
            session_data={
                "name": "João", "email": "j@e.com",
                "session_id": "s1", "servico_id": self.servico.pk,
            },
        )
        self.assertEqual(lead.servico_id, self.servico.pk)

    def test_lead_inherits_default_stage_when_servico_has_one(self):
        pipeline = Pipeline.objects.filter(empresa=self.empresa, is_default=True).first()
        target_stage = pipeline.stages.order_by("order")[2]
        self.servico.default_pipeline = pipeline
        self.servico.default_stage = target_stage
        self.servico.save()

        lead = create_lead_from_chatbot(
            empresa=self.empresa, flow=None,
            session_data={
                "name": "Maria", "email": "m@e.com",
                "session_id": "s2", "servico_id": self.servico.pk,
            },
        )
        # Deve ter pulado da etapa default (0) para a do serviço (2)
        self.assertEqual(lead.pipeline_stage_id, target_stage.pk)


class ProposalCreateFromServicoTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("p@t.com", "P", self.empresa)
        self.client.force_login(self.user)
        create_pipeline_for_empresa(self.empresa)
        self.servico = ServiceType.objects.create(
            empresa=self.empresa, name="Levantamento",
            default_price=Decimal("1500.00"),
            default_description="<p>Descrição padrão</p>",
            default_prazo_dias=30,
        )
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Lead",
            servico=self.servico,
        )

    def test_create_view_prefills_from_lead_servico(self):
        url = reverse("proposals:create") + f"?lead_id={self.lead.pk}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Inicial deve ter o servico vinculado e título do serviço
        form = resp.context["form"]
        self.assertEqual(form.initial.get("lead"), str(self.lead.pk))
        self.assertEqual(form.initial.get("servico"), self.servico.pk)
        self.assertEqual(form.initial.get("title"), "Levantamento")

    def test_create_view_prefills_from_explicit_servico_id(self):
        url = reverse("proposals:create") + f"?servico_id={self.servico.pk}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        form = resp.context["form"]
        self.assertEqual(form.initial.get("servico"), self.servico.pk)
        # valid_until = hoje + 30
        expected = (timezone.now().date() + timedelta(days=30))
        self.assertEqual(form.initial.get("valid_until"), expected)

    def test_other_tenant_servico_ignored(self):
        outra = create_test_empresa(name="X", slug="x")
        outra_servico = ServiceType.objects.create(
            empresa=outra, name="ProibidoVer",
            default_price=Decimal("999"),
        )
        url = reverse("proposals:create") + f"?servico_id={outra_servico.pk}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        form = resp.context["form"]
        # serviço de outro tenant não pré-preenche
        self.assertNotIn("servico", form.initial)

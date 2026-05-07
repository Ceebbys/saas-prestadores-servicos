"""Testes da engine de fluxos: ramificação, fallback, terminal."""

from django.test import TestCase

from apps.chatbot.models import ChatbotChoice, ChatbotFlow, ChatbotStep
from apps.chatbot.services import (
    process_response,
    select_flow_for_message,
    start_session,
)
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _bare_flow(empresa, name="Fluxo", **kwargs):
    return ChatbotFlow.objects.create(
        empresa=empresa, name=name, channel="whatsapp",
        is_active=True, **kwargs,
    )


class FlowBranchingTests(TestCase):
    """Garante que ChatbotChoice.next_step direciona corretamente."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("e@t.com", "E", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.flow = _bare_flow(self.empresa)
        # Step 0: pergunta com 2 opções
        self.step0 = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Escolha:",
            step_type=ChatbotStep.StepType.CHOICE,
        )
        # Step 1 (linear) — não deve ser usado quando opção tem next_step
        self.step1 = ChatbotStep.objects.create(
            flow=self.flow, order=1, question_text="Etapa 1 linear",
            step_type=ChatbotStep.StepType.TEXT, is_final=True,
        )
        self.step_a = ChatbotStep.objects.create(
            flow=self.flow, order=10, question_text="Etapa A",
            step_type=ChatbotStep.StepType.TEXT, is_final=True,
        )
        self.step_b = ChatbotStep.objects.create(
            flow=self.flow, order=20, question_text="Etapa B",
            step_type=ChatbotStep.StepType.TEXT, is_final=True,
        )
        ChatbotChoice.objects.create(
            step=self.step0, text="Opção A", order=0, next_step=self.step_a,
        )
        ChatbotChoice.objects.create(
            step=self.step0, text="Opção B", order=1, next_step=self.step_b,
        )

    def test_choice_1_goes_to_step_a(self):
        s = start_session(self.flow, channel="webchat", sender_id="111")
        result = process_response(s["session_key"], "1")
        self.assertFalse(result["error"])
        self.assertEqual(result["step"]["question"], "Etapa A")

    def test_choice_2_goes_to_step_b(self):
        s = start_session(self.flow, channel="webchat", sender_id="222")
        result = process_response(s["session_key"], "2")
        self.assertFalse(result["error"])
        self.assertEqual(result["step"]["question"], "Etapa B")

    def test_invalid_choice_returns_fallback_error(self):
        s = start_session(self.flow, channel="webchat", sender_id="333")
        result = process_response(s["session_key"], "xyz invalid")
        self.assertTrue(result["error"])
        self.assertIn("Opção A", result["message"])

    def test_step_without_choices_advances_linear(self):
        # Cria fluxo separado sem choices, só ordem linear
        flow2 = _bare_flow(self.empresa, name="Linear")
        s0 = ChatbotStep.objects.create(
            flow=flow2, order=0, question_text="Q1",
            step_type=ChatbotStep.StepType.TEXT,
        )
        s1 = ChatbotStep.objects.create(
            flow=flow2, order=1, question_text="Q2",
            step_type=ChatbotStep.StepType.TEXT, is_final=True,
        )
        sess = start_session(flow2, channel="webchat", sender_id="abc")
        result = process_response(sess["session_key"], "qualquer texto")
        self.assertFalse(result["error"])
        self.assertEqual(result["step"]["question"], "Q2")


class FlowSelectionTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_pipeline_for_empresa(self.empresa)

    def test_first_message_selects_first_message_flow(self):
        flow = _bare_flow(self.empresa, name="Boas-vindas")
        ChatbotStep.objects.create(flow=flow, order=0, question_text="Q")
        chosen = select_flow_for_message(self.empresa, "111", "olá")
        self.assertEqual(chosen, flow)

    def test_keyword_match_dispatches(self):
        flow_kw = _bare_flow(
            self.empresa, name="Suporte",
            trigger_type=ChatbotFlow.TriggerType.KEYWORD,
            trigger_keywords="suporte, ajuda",
        )
        ChatbotStep.objects.create(flow=flow_kw, order=0, question_text="Q")
        chosen = select_flow_for_message(self.empresa, "222", "preciso de ajuda")
        self.assertEqual(chosen, flow_kw)

    def test_priority_breaks_ties(self):
        f_lo = _bare_flow(self.empresa, name="Geral", priority=200)
        f_hi = _bare_flow(self.empresa, name="VIP", priority=10)
        ChatbotStep.objects.create(flow=f_lo, order=0, question_text="Q")
        ChatbotStep.objects.create(flow=f_hi, order=0, question_text="Q")
        chosen = select_flow_for_message(self.empresa, "333", "olá")
        self.assertEqual(chosen, f_hi)

    def test_active_exclusive_session_blocks_new_flow(self):
        flow = _bare_flow(self.empresa, name="Onboarding", exclusive=True)
        ChatbotStep.objects.create(flow=flow, order=0, question_text="Q")
        # Inicia sessão exclusiva
        start_session(flow, channel="whatsapp", sender_id="44455")
        # Outra mensagem chega — deve retornar None (não inicia outro fluxo)
        chosen = select_flow_for_message(self.empresa, "44455", "qualquer")
        self.assertIsNone(chosen)

    def test_cooldown_blocks_repeat(self):
        from datetime import timedelta
        from django.utils import timezone

        from apps.chatbot.models import ChatbotFlowDispatch

        flow = _bare_flow(self.empresa, name="Recente", cooldown_minutes=60)
        ChatbotStep.objects.create(flow=flow, order=0, question_text="Q")
        ChatbotFlowDispatch.objects.create(
            empresa=self.empresa,
            flow=flow,
            sender_id="555",
            triggered_at=timezone.now() - timedelta(minutes=10),
            reason="first_message",
            blocked=False,
        )
        chosen = select_flow_for_message(self.empresa, "555", "olá")
        self.assertIsNone(chosen)

    def test_cooldown_counts_blocked_dispatches_too(self):
        """Cooldown deve incluir dispatches blocked=True (defesa anti-flood)."""
        from datetime import timedelta
        from django.utils import timezone

        from apps.chatbot.models import ChatbotFlowDispatch

        flow = _bare_flow(self.empresa, name="Bloqueado", cooldown_minutes=60)
        ChatbotStep.objects.create(flow=flow, order=0, question_text="Q")
        # Dispatch BLOQUEADO recente — antigo cooldown ignorava, novo conta
        ChatbotFlowDispatch.objects.create(
            empresa=self.empresa,
            flow=flow,
            sender_id="666",
            triggered_at=timezone.now() - timedelta(minutes=5),
            reason="blocked_by:other_flow",
            blocked=True,
        )
        chosen = select_flow_for_message(self.empresa, "666", "olá")
        self.assertIsNone(chosen)

"""Testes do RV05 FASE 3 — Ações por etapa + Encerrar conversa por step."""
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.chatbot.models import (
    ChatbotAction,
    ChatbotChoice,
    ChatbotFlow,
    ChatbotFlowDispatch,
    ChatbotStep,
)
from apps.chatbot.services import process_response, start_session
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _bare_flow(empresa, **kwargs):
    return ChatbotFlow.objects.create(
        empresa=empresa, name="F", channel="whatsapp", is_active=True, **kwargs,
    )


class StepIsFinalAsEncerrarConversaTests(TestCase):
    """`is_final` semanticamente = 'Encerrar conversa neste passo' (RV05 #2 PDF)."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("e@t.com", "E", self.empresa)
        create_pipeline_for_empresa(self.empresa)

    def test_step_marked_final_completes_session(self):
        flow = _bare_flow(self.empresa)
        s0 = ChatbotStep.objects.create(
            flow=flow, order=0, question_text="Q1",
            step_type=ChatbotStep.StepType.TEXT, is_final=True,  # encerra aqui
        )
        # Cria outro step depois — não deveria ser alcançado
        ChatbotStep.objects.create(
            flow=flow, order=1, question_text="Should not reach",
            step_type=ChatbotStep.StepType.TEXT,
        )

        s = start_session(flow, channel="webchat", sender_id="111")
        result = process_response(s["session_key"], "qualquer resposta")
        self.assertTrue(result["is_complete"])
        self.assertIsNone(result["step"])

    def test_session_completed_dispatches_audit_log(self):
        flow = _bare_flow(self.empresa)
        ChatbotStep.objects.create(
            flow=flow, order=0, question_text="Final",
            step_type=ChatbotStep.StepType.TEXT, is_final=True,
        )
        s = start_session(flow, channel="webchat", sender_id="222")
        process_response(s["session_key"], "x")
        # Dispatch com reason começando em 'session_completed'
        self.assertTrue(
            ChatbotFlowDispatch.objects.filter(
                empresa=self.empresa,
                flow=flow,
                reason__startswith="session_completed",
            ).exists()
        )


class PerStepActionExecutionTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("psa@t.com", "PSA", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.flow = _bare_flow(self.empresa)
        self.step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Step com ação",
            step_type=ChatbotStep.StepType.NAME,
            lead_field_mapping="name",
            is_final=True,  # garante encerramento
        )

    def test_action_on_step_executes_create_lead(self):
        ChatbotAction.objects.create(
            flow=self.flow, step=self.step,
            trigger=ChatbotAction.Trigger.ON_STEP,
            action_type=ChatbotAction.ActionType.CREATE_LEAD,
            is_active=True,
        )
        s = start_session(self.flow, channel="webchat", sender_id="psa1")
        result = process_response(s["session_key"], "João da Silva")
        self.assertTrue(result["is_complete"])
        self.assertIsNotNone(result["lead_id"])

    def test_inactive_action_not_executed(self):
        action = ChatbotAction.objects.create(
            flow=self.flow, step=self.step,
            trigger=ChatbotAction.Trigger.ON_STEP,
            action_type=ChatbotAction.ActionType.CREATE_LEAD,
            is_active=False,  # desativada
        )
        # Sem outras ações globais que criariam lead automaticamente —
        # garantir que o flow tenha um config explícito.
        s = start_session(self.flow, channel="webchat", sender_id="psa2")
        result = process_response(s["session_key"], "Maria")
        # O fallback do _execute_flow_actions cria lead se lead_data tem name,
        # então `lead_id` pode estar setado pela ação legada (não pela inativa).
        # O importante é: a action inativa NÃO foi executada — confirma via mock:
        from apps.chatbot import services as svc
        with patch.object(svc, "_execute_action") as mock_exec:
            s2 = start_session(self.flow, channel="webchat", sender_id="psa2b")
            process_response(s2["session_key"], "Marta")
            mock_exec.assert_not_called()

    def test_error_in_action_does_not_break_conversation(self):
        ChatbotAction.objects.create(
            flow=self.flow, step=self.step,
            trigger=ChatbotAction.Trigger.ON_STEP,
            action_type=ChatbotAction.ActionType.CREATE_LEAD,
            is_active=True,
        )
        s = start_session(self.flow, channel="webchat", sender_id="psa3")
        from apps.chatbot import services as svc
        with patch.object(svc, "_execute_action", side_effect=RuntimeError("boom")):
            result = process_response(s["session_key"], "Pedro")
        # Conversa segue até completion mesmo com a ação falhando
        self.assertTrue(result["is_complete"])

    def test_actions_execute_in_order(self):
        executed = []
        ChatbotAction.objects.create(
            flow=self.flow, step=self.step,
            trigger=ChatbotAction.Trigger.ON_STEP,
            action_type=ChatbotAction.ActionType.CREATE_LEAD,
            is_active=True, order=2,
            config={"name": "second"},
        )
        ChatbotAction.objects.create(
            flow=self.flow, step=self.step,
            trigger=ChatbotAction.Trigger.ON_STEP,
            action_type=ChatbotAction.ActionType.APPLY_TAG,
            is_active=True, order=1,
            config={"name": "first"},
        )

        from apps.chatbot import services as svc

        def capture(action, session):
            executed.append(action.config.get("name"))

        s = start_session(self.flow, channel="webchat", sender_id="psa4")
        with patch.object(svc, "_execute_action", side_effect=capture):
            process_response(s["session_key"], "Ana")
        self.assertEqual(executed, ["first", "second"])


class ActionConstraintTests(TestCase):
    """CheckConstraint impede config ambígua."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow = _bare_flow(self.empresa)
        self.step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Q", is_final=True,
        )

    def test_step_with_on_complete_rejected(self):
        # step=X com trigger=on_complete → constraint viola
        with self.assertRaises(IntegrityError):
            ChatbotAction.objects.create(
                flow=self.flow, step=self.step,
                trigger=ChatbotAction.Trigger.ON_COMPLETE,  # inválido com step
                action_type=ChatbotAction.ActionType.CREATE_LEAD,
            )

    def test_no_step_with_on_step_rejected(self):
        # step=None com trigger=on_step → constraint viola
        with self.assertRaises(IntegrityError):
            ChatbotAction.objects.create(
                flow=self.flow, step=None,
                trigger=ChatbotAction.Trigger.ON_STEP,  # inválido sem step
                action_type=ChatbotAction.ActionType.CREATE_LEAD,
            )

    def test_legacy_on_complete_without_step_still_works(self):
        # Compat retroativa: actions globais (step=None, on_complete) continuam OK
        a = ChatbotAction.objects.create(
            flow=self.flow, step=None,
            trigger=ChatbotAction.Trigger.ON_COMPLETE,
            action_type=ChatbotAction.ActionType.CREATE_LEAD,
        )
        self.assertIsNotNone(a.pk)

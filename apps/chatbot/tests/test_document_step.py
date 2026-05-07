"""Testes do step_type DOCUMENT: integração com Contato."""

from django.test import TestCase

from apps.chatbot.models import ChatbotFlow, ChatbotStep
from apps.chatbot.services import process_response, start_session
from apps.contacts.models import Contato
from apps.core.tests.helpers import create_pipeline_for_empresa, create_test_empresa


class DocumentStepTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_pipeline_for_empresa(self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F", channel="whatsapp", is_active=True,
        )
        self.s0 = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="CPF?",
            step_type=ChatbotStep.StepType.DOCUMENT,
            lead_field_mapping="cpf_cnpj",
        )
        self.s1 = ChatbotStep.objects.create(
            flow=self.flow, order=1, question_text="OK",
            step_type=ChatbotStep.StepType.TEXT,
            is_final=True,
        )

    def test_document_links_existing_contato(self):
        existing = Contato.objects.create(
            empresa=self.empresa, name="João Salvo", cpf_cnpj="529.982.247-25",
            phone="11999990000",
        )
        sess = start_session(self.flow, channel="whatsapp", sender_id="555")
        result = process_response(sess["session_key"], "529.982.247-25")
        self.assertFalse(result["error"])

        # Recarrega a sessão e verifica que contato_id foi salvo no lead_data
        from apps.chatbot.models import ChatbotSession
        s = ChatbotSession.objects.get(session_key=sess["session_key"])
        self.assertEqual(s.lead_data.get("contato_id"), existing.pk)

    def test_document_with_unknown_doc_keeps_normalized_in_session(self):
        sess = start_session(self.flow, channel="whatsapp", sender_id="666")
        result = process_response(sess["session_key"], "529.982.247-25")
        self.assertFalse(result["error"])
        from apps.chatbot.models import ChatbotSession
        s = ChatbotSession.objects.get(session_key=sess["session_key"])
        self.assertEqual(s.lead_data.get("cpf_cnpj_normalized"), "52998224725")
        self.assertNotIn("contato_id", s.lead_data)

    def test_document_invalid_returns_validation_error(self):
        sess = start_session(self.flow, channel="whatsapp", sender_id="777")
        result = process_response(sess["session_key"], "111.111.111-11")
        self.assertTrue(result["error"])

    def test_document_is_isolated_per_empresa(self):
        empresa_b = create_test_empresa("B", "b")
        # Contato existe na empresa B, NÃO na empresa A
        Contato.objects.create(
            empresa=empresa_b, name="Outro", cpf_cnpj="529.982.247-25",
        )
        sess = start_session(self.flow, channel="whatsapp", sender_id="888")
        result = process_response(sess["session_key"], "529.982.247-25")
        self.assertFalse(result["error"])
        from apps.chatbot.models import ChatbotSession
        s = ChatbotSession.objects.get(session_key=sess["session_key"])
        self.assertNotIn("contato_id", s.lead_data)

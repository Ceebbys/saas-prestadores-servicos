"""RV05-G — Garante que campos visuais (3C) persistem corretamente.

Auditoria mostrou que `position_x/y`, `node_type` e `visual_config` foram
adicionados ao modelo mas sem teste cobrindo persistência.
"""
from django.test import TestCase

from apps.chatbot.models import ChatbotFlow, ChatbotStep
from apps.core.tests.helpers import create_test_empresa, create_test_user


class ChatbotStepVisualFieldsTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("v@t.com", "V", self.empresa)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Visual Flow", channel="webchat",
        )

    def test_position_persisted(self):
        step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="X",
            position_x=120.5, position_y=300.75,
        )
        step.refresh_from_db()
        self.assertEqual(step.position_x, 120.5)
        self.assertEqual(step.position_y, 300.75)

    def test_position_default_zero(self):
        step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="X",
        )
        step.refresh_from_db()
        self.assertEqual(step.position_x, 0.0)
        self.assertEqual(step.position_y, 0.0)

    def test_node_type_persisted(self):
        step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="X",
            node_type=ChatbotStep.NodeType.CONDITION,
        )
        step.refresh_from_db()
        self.assertEqual(step.node_type, "condition")

    def test_node_type_default_message(self):
        step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="X",
        )
        step.refresh_from_db()
        self.assertEqual(step.node_type, ChatbotStep.NodeType.MESSAGE)

    def test_visual_config_jsonfield_persists(self):
        cfg = {"color": "#ff6347", "icon": "branch", "metadata": {"foo": "bar"}}
        step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="X",
            visual_config=cfg,
        )
        step.refresh_from_db()
        self.assertEqual(step.visual_config, cfg)
        self.assertEqual(step.visual_config["metadata"]["foo"], "bar")

    def test_visual_config_default_empty_dict(self):
        step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="X",
        )
        step.refresh_from_db()
        self.assertEqual(step.visual_config, {})

    def test_all_visual_fields_together(self):
        step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="X",
            position_x=50.0, position_y=75.0,
            node_type=ChatbotStep.NodeType.ACTION,
            visual_config={"width": 200, "height": 80},
        )
        step.refresh_from_db()
        self.assertEqual(step.position_x, 50.0)
        self.assertEqual(step.position_y, 75.0)
        self.assertEqual(step.node_type, "action")
        self.assertEqual(step.visual_config, {"width": 200, "height": 80})

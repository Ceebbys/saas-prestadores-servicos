"""Testes da hierarquia de etapas (parent/subordem/codigo_hierarquico)."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.chatbot.models import ChatbotFlow, ChatbotStep
from apps.core.tests.helpers import create_pipeline_for_empresa, create_test_empresa


def _flow(empresa, name="F"):
    return ChatbotFlow.objects.create(
        empresa=empresa, name=name, channel="whatsapp", is_active=True,
    )


class HierarchyCodeTests(TestCase):
    """codigo_hierarquico denormalizado deve refletir a estrutura."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_pipeline_for_empresa(self.empresa)
        self.flow = _flow(self.empresa)

    def test_root_step_gets_code_one(self):
        s = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Q",
            subordem=0,
        )
        self.assertEqual(s.codigo_hierarquico, "1")
        self.assertEqual(s.nivel, 0)

    def test_two_roots_get_distinct_codes(self):
        a = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="A", subordem=0,
        )
        b = ChatbotStep.objects.create(
            flow=self.flow, order=1, question_text="B", subordem=1,
        )
        self.assertEqual(a.codigo_hierarquico, "1")
        self.assertEqual(b.codigo_hierarquico, "2")

    def test_children_inherit_parent_code(self):
        root = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Pai", subordem=0,
        )
        c1 = ChatbotStep.objects.create(
            flow=self.flow, order=10, question_text="Filho1",
            parent=root, subordem=0,
        )
        c2 = ChatbotStep.objects.create(
            flow=self.flow, order=11, question_text="Filho2",
            parent=root, subordem=1,
        )
        self.assertEqual(c1.codigo_hierarquico, "1.1")
        self.assertEqual(c2.codigo_hierarquico, "1.2")
        self.assertEqual(c1.nivel, 1)

    def test_grandchild_three_levels(self):
        root = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="R", subordem=0,
        )
        child = ChatbotStep.objects.create(
            flow=self.flow, order=10, question_text="C",
            parent=root, subordem=1,
        )
        grand = ChatbotStep.objects.create(
            flow=self.flow, order=20, question_text="G",
            parent=child, subordem=0,
        )
        self.assertEqual(grand.codigo_hierarquico, "1.2.1")
        self.assertEqual(grand.nivel, 2)

    def test_moving_step_rewrites_descendants(self):
        a = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="A", subordem=0,
        )
        b = ChatbotStep.objects.create(
            flow=self.flow, order=1, question_text="B", subordem=1,
        )
        child = ChatbotStep.objects.create(
            flow=self.flow, order=10, question_text="X",
            parent=a, subordem=0,
        )
        self.assertEqual(child.codigo_hierarquico, "1.1")
        # Move child de a para b
        child.parent = b
        child.subordem = 0
        child.save()
        child.refresh_from_db()
        self.assertEqual(child.codigo_hierarquico, "2.1")


class HierarchyClenTests(TestCase):
    """clean() rejeita ciclos e cross-flow."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_pipeline_for_empresa(self.empresa)

    def test_self_parent_rejected(self):
        flow = _flow(self.empresa)
        s = ChatbotStep.objects.create(
            flow=flow, order=0, question_text="Q", subordem=0,
        )
        s.parent = s
        with self.assertRaises(ValidationError):
            s.clean()

    def test_cycle_rejected(self):
        flow = _flow(self.empresa)
        a = ChatbotStep.objects.create(
            flow=flow, order=0, question_text="A", subordem=0,
        )
        b = ChatbotStep.objects.create(
            flow=flow, order=1, question_text="B",
            parent=a, subordem=0,
        )
        # Tentar setar a como filho de b cria ciclo a -> b -> a
        a.parent = b
        with self.assertRaises(ValidationError):
            a.clean()

    def test_cross_flow_parent_rejected(self):
        flow1 = _flow(self.empresa, "F1")
        flow2 = _flow(self.empresa, "F2")
        a = ChatbotStep.objects.create(
            flow=flow1, order=0, question_text="A", subordem=0,
        )
        b = ChatbotStep.objects.create(
            flow=flow2, order=0, question_text="B", subordem=0,
        )
        b.parent = a  # pai está em outro flow
        with self.assertRaises(ValidationError):
            b.clean()


class StepsTreeTests(TestCase):
    """flow.steps_tree() retorna lista achatada em ordem visual (preorder)."""

    def setUp(self):
        self.empresa = create_test_empresa()
        create_pipeline_for_empresa(self.empresa)
        self.flow = _flow(self.empresa)

    def test_preorder_traversal(self):
        # Estrutura desejada:
        #   1 — A
        #     1.1 — A1
        #     1.2 — A2
        #   2 — B
        #     2.1 — B1
        a = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="A", subordem=0,
        )
        b = ChatbotStep.objects.create(
            flow=self.flow, order=1, question_text="B", subordem=1,
        )
        a1 = ChatbotStep.objects.create(
            flow=self.flow, order=10, question_text="A1",
            parent=a, subordem=0,
        )
        a2 = ChatbotStep.objects.create(
            flow=self.flow, order=11, question_text="A2",
            parent=a, subordem=1,
        )
        b1 = ChatbotStep.objects.create(
            flow=self.flow, order=20, question_text="B1",
            parent=b, subordem=0,
        )

        tree = self.flow.steps_tree()
        codes = [entry["step"].codigo_hierarquico for entry in tree]
        levels = [entry["nivel"] for entry in tree]
        self.assertEqual(codes, ["1", "1.1", "1.2", "2", "2.1"])
        self.assertEqual(levels, [0, 1, 1, 0, 1])

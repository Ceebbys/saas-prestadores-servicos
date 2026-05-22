"""RV06 Item 2 — Editor legacy fica read-only quando use_visual_builder=True.

Cobre:
- Save no FlowUpdateView é rejeitado quando visual ativo
- Step/Action CRUD bloqueados quando visual ativo
- FlowDisableVisualView reativa o editor legacy + arquiva versão visual
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.chatbot.models import (
    ChatbotAction, ChatbotFlow, ChatbotFlowVersion, ChatbotStep,
)
from apps.core.tests.helpers import create_test_empresa, create_test_user


class LegacyEditReadOnlyTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("ro@t.com", "RO", self.empresa)
        self.client.force_login(self.user)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Test RO", channel="whatsapp",
            is_active=True, use_visual_builder=True,
        )

    def test_flow_update_blocked_when_visual_active(self):
        url = reverse("chatbot:flow_update", args=[self.flow.pk])
        # Tenta editar via POST (deve ser bloqueado)
        resp = self.client.post(url, {
            "name": "Novo Nome", "channel": "whatsapp",
            "trigger_type": "first_message",
            "priority": 10, "cooldown_minutes": 0,
            "is_active": "on",
            "send_completion_message": "on",
            "completion_message": "fim",
            "welcome_message": "oi",
        })
        # Não muda o nome
        self.flow.refresh_from_db()
        self.assertEqual(self.flow.name, "Test RO")

    def test_step_add_blocked_when_visual_active(self):
        url = reverse("chatbot:step_add", args=[self.flow.pk])
        resp = self.client.post(url, {
            "order": 1, "question_text": "?", "step_type": "text",
        })
        # Não cria step
        self.assertEqual(ChatbotStep.objects.filter(flow=self.flow).count(), 0)
        # Redireciona com mensagem de erro
        self.assertEqual(resp.status_code, 302)

    def test_action_add_blocked_when_visual_active(self):
        url = reverse("chatbot:action_add", args=[self.flow.pk])
        resp = self.client.post(url, {
            "action_type": "create_lead", "trigger": "on_complete",
            "order": 0, "is_active": "on",
        })
        self.assertEqual(ChatbotAction.objects.filter(flow=self.flow).count(), 0)

    def test_disable_visual_archives_version_and_unlocks_editor(self):
        # Cria versão PUBLISHED ativa
        version = ChatbotFlowVersion.objects.create(
            flow=self.flow,
            status=ChatbotFlowVersion.Status.PUBLISHED,
            graph_json={"schema_version": 1, "nodes": [], "edges": []},
            published_at=timezone.now(),
        )
        self.flow.current_published_version = version
        self.flow.save(update_fields=["current_published_version"])

        url = reverse("chatbot:flow_disable_visual", args=[self.flow.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

        # Flow não usa mais visual; versão arquivada
        self.flow.refresh_from_db()
        version.refresh_from_db()
        self.assertFalse(self.flow.use_visual_builder)
        self.assertIsNone(self.flow.current_published_version)
        self.assertEqual(version.status, ChatbotFlowVersion.Status.ARCHIVED)

    def test_disable_visual_is_idempotent(self):
        self.flow.use_visual_builder = False
        self.flow.save(update_fields=["use_visual_builder"])
        url = reverse("chatbot:flow_disable_visual", args=[self.flow.pk])
        resp = self.client.post(url)
        # Não quebra, mostra mensagem info
        self.assertEqual(resp.status_code, 302)

    def test_guard_does_not_block_when_visual_disabled(self):
        """Sanity: guard só bloqueia quando use_visual_builder=True."""
        from apps.chatbot.views import _guard_legacy_edit
        self.flow.use_visual_builder = False
        self.flow.save(update_fields=["use_visual_builder"])
        # Mock request com .empresa apenas para messages
        class FakeRequest:
            _messages = None
        # Sem visual: guard retorna None (não bloqueia)
        # OBS: messages framework precisa de request real; testamos só o
        # caminho de retorno None para use_visual_builder=False
        # (caso True foi testado nos outros tests acima).
        result = _guard_legacy_edit(self.flow, None)
        # Como flow.use_visual_builder=False, guard retorna None imediatamente
        # antes de tocar request → não levanta
        self.assertIsNone(result)


class FlowMigrateToVisualTests(TestCase):
    """Onda 1 — Botão 'Migrar para construtor visual' no editor legacy."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="migrate-test")
        self.user = create_test_user("mig@t.com", "MIG", self.empresa)
        self.client.force_login(self.user)
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Test Migration", channel="whatsapp",
            is_active=True, use_visual_builder=False,
        )

    def test_migration_with_legacy_steps_converts_to_draft(self):
        """Flow com etapas legacy: convertidas para graph_json no draft."""
        ChatbotStep.objects.create(
            flow=self.flow, order=0,
            question_text="Qual seu nome?", step_type="name",
        )
        ChatbotStep.objects.create(
            flow=self.flow, order=1,
            question_text="Qual seu e-mail?", step_type="email",
        )
        url = reverse("chatbot:flow_migrate_to_visual", args=[self.flow.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/builder/", resp.url)

        self.flow.refresh_from_db()
        self.assertTrue(self.flow.use_visual_builder)

        from apps.chatbot.models import ChatbotFlowVersion
        draft = ChatbotFlowVersion.objects.filter(
            flow=self.flow, status=ChatbotFlowVersion.Status.DRAFT,
        ).first()
        self.assertIsNotNone(draft)
        types = [n["type"] for n in draft.graph_json["nodes"]]
        # Esperado: start + 2 question/collect_data + (talvez end)
        self.assertIn("start", types)
        self.assertGreater(len(draft.graph_json["nodes"]), 1)

    def test_migration_without_legacy_creates_empty_canvas(self):
        """Flow sem etapas legacy: cria draft com apenas o bloco 'Início'."""
        url = reverse("chatbot:flow_migrate_to_visual", args=[self.flow.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

        self.flow.refresh_from_db()
        self.assertTrue(self.flow.use_visual_builder)

        from apps.chatbot.models import ChatbotFlowVersion
        draft = ChatbotFlowVersion.objects.get(
            flow=self.flow, status=ChatbotFlowVersion.Status.DRAFT,
        )
        types = [n["type"] for n in draft.graph_json["nodes"]]
        self.assertEqual(types, ["start"])

    def test_migration_is_idempotent(self):
        """Chamar 2x: 2ª vez apenas redireciona (info message)."""
        url = reverse("chatbot:flow_migrate_to_visual", args=[self.flow.pk])
        self.client.post(url)
        from apps.chatbot.models import ChatbotFlowVersion
        n_drafts_after_first = ChatbotFlowVersion.objects.filter(
            flow=self.flow, status=ChatbotFlowVersion.Status.DRAFT,
        ).count()

        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        # Não cria 2º draft
        self.assertEqual(
            ChatbotFlowVersion.objects.filter(
                flow=self.flow, status=ChatbotFlowVersion.Status.DRAFT,
            ).count(),
            n_drafts_after_first,
        )

    def test_migration_cross_tenant_blocked(self):
        """User não pode migrar fluxo de outra empresa."""
        other = create_test_empresa(slug="migrate-other")
        other_flow = ChatbotFlow.objects.create(
            empresa=other, name="Outro", channel="whatsapp",
        )
        url = reverse("chatbot:flow_migrate_to_visual", args=[other_flow.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)
        other_flow.refresh_from_db()
        self.assertFalse(other_flow.use_visual_builder)

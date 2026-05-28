"""QA Smoke — 10 cenários integrados ponta-a-ponta dos 5 hotfixes do
commit d84eb3c + features do dia.

NÃO modifica código de produção — apenas exercita os fluxos com input real.
Cada cenário cria sua própria empresa (slug='cenario-N') pra isolamento
multi-tenant.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


# ============================================================================
# Cenário 1 — Fluxo central RV10: regra automação cria entry
# ============================================================================

class Cenario1AutomationCreatesEntryTests(TestCase):
    """RV10 fluxo central: PROPOSTA_ACEITA → regra move lead pra Ganho →
    signal gera FinancialEntry com amount=estimated_value."""

    def _setup_empresa(self):
        empresa = create_test_empresa(slug="cenario-1")
        create_test_user("c1@t.com", "C1", empresa)
        create_pipeline_for_empresa(empresa)  # cria Novo/Negociando/Fechado(won)
        from apps.crm.models import Pipeline
        pipeline = Pipeline.objects.get(empresa=empresa, is_default=True)
        stages = list(pipeline.stages.order_by("order"))
        return empresa, pipeline, stages[0], stages[-1]

    def test_full_flow(self):
        from apps.automation.models import PipelineAutomationRule
        from apps.crm.models import Lead
        from apps.finance.models import FinancialEntry
        from apps.proposals.models import Proposal

        empresa, pipeline, stage_novo, stage_ganho = self._setup_empresa()

        # Regra: PROPOSTA_ACEITA → mover pra Ganho
        rule = PipelineAutomationRule.objects.create(
            empresa=empresa,
            name="Aceita → Ganho",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=pipeline,
            target_stage=stage_ganho,
            is_active=True,
        )

        # Lead em Novo
        lead = Lead.objects.create(
            empresa=empresa,
            name="Cliente Cenário 1",
            estimated_value=Decimal("2500.00"),
            pipeline_stage=stage_novo,
        )
        self.assertEqual(lead.pipeline_stage_id, stage_novo.pk)

        # Proposta DRAFT
        proposal = Proposal.objects.create(
            empresa=empresa,
            lead=lead,
            title="Proposta C1",
            discount_percent=Decimal("0"),
            status=Proposal.Status.DRAFT,
        )

        # Aceita proposta + força execução do on_commit
        with self.captureOnCommitCallbacks(execute=True):
            proposal.status = Proposal.Status.ACCEPTED
            proposal.accepted_at = timezone.now()
            proposal.save()

        # ----- Verificações -----
        lead.refresh_from_db()
        # 1. Lead foi movido para Ganho pela regra
        self.assertEqual(
            lead.pipeline_stage_id, stage_ganho.pk,
            "Regra deveria ter movido o lead pra Ganho",
        )
        # 2. FinancialEntry criada apesar do _suppress_automation
        entries = FinancialEntry.objects.filter(related_lead=lead)
        self.assertEqual(
            entries.count(), 1,
            "Entry deveria ter sido criada (hotfix #1)",
        )
        entry = entries.first()
        # 3. Amount = estimated_value
        self.assertEqual(entry.amount, Decimal("2500.00"))
        self.assertEqual(entry.type, FinancialEntry.Type.INCOME)
        self.assertEqual(entry.status, FinancialEntry.Status.PENDING)
        self.assertTrue(entry.auto_generated)


# ============================================================================
# Cenário 2 — Parcelamento atomic
# ============================================================================

class Cenario2InstallmentsAtomicTests(TestCase):
    """save_installments com @transaction.atomic — falha na 3ª deve
    rollback as 2 anteriores."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="cenario-2")

    def test_happy_path_3_installments(self):
        from apps.finance.forms import FinancialEntryForm
        from apps.finance.models import FinancialEntry

        form = FinancialEntryForm(
            data={
                "type": "income",
                "description": "Serviço C2",
                "amount": "1500.00",
                "date": "2026-06-01",
                "status": "pending",
                "is_installment": "on",
                "installment_count": "3",
                "installment_interval_days": "30",
            },
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        entries = form.save_installments(self.empresa)
        self.assertEqual(len(entries), 3)
        total = sum(e.amount for e in entries)
        self.assertEqual(total, Decimal("1500.00"))
        # Todas têm R$ 500 (par)
        for e in entries:
            self.assertEqual(e.amount, Decimal("500.00"))

    def test_rollback_on_failure_at_3rd_installment(self):
        from apps.finance.forms import FinancialEntryForm
        from apps.finance.models import FinancialEntry

        form = FinancialEntryForm(
            data={
                "type": "income",
                "description": "Rollback C2",
                "amount": "1500.00",
                "date": "2026-06-01",
                "status": "pending",
                "is_installment": "on",
                "installment_count": "3",
                "installment_interval_days": "30",
            },
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)

        original_save = FinancialEntry.save
        count = {"n": 0}

        def flaky_save(self, *args, **kwargs):
            count["n"] += 1
            if count["n"] == 3:
                raise RuntimeError("simulated DB failure")
            return original_save(self, *args, **kwargs)

        with patch.object(FinancialEntry, "save", flaky_save):
            with self.assertRaises(RuntimeError):
                form.save_installments(self.empresa)

        # Nenhuma entry persiste
        self.assertEqual(
            FinancialEntry.objects.filter(empresa=self.empresa).count(),
            0,
            "Rollback falhou — entries órfãs ficaram (hotfix #2)",
        )


# ============================================================================
# Cenário 3 — Banner remaining nunca negativo
# ============================================================================

class Cenario3BannerRemainingNeverNegativeTests(TestCase):
    """`won_leads_pending_remaining = max(0, N - 5)` — testando 0, 3 e 8."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="cenario-3")
        self.user = create_test_user("c3@t.com", "C3", self.empresa)
        self.client.force_login(self.user)
        from apps.crm.models import Pipeline, PipelineStage
        p = Pipeline.objects.create(empresa=self.empresa, name="P")
        self.s_ganho = PipelineStage.objects.create(
            pipeline=p, name="Ganho", order=0, is_won=True,
        )

    def _add_won_leads(self, n):
        from apps.crm.models import Lead
        for i in range(n):
            lead = Lead(
                empresa=self.empresa,
                name=f"L{i}",
                pipeline_stage=self.s_ganho,
            )
            lead._suppress_finance_entry = True
            lead.save()

    def test_zero_remaining_zero(self):
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["won_leads_pending"], 0)
        self.assertEqual(response.context["won_leads_pending_remaining"], 0)
        # Verifica HTML — não pode haver "e mais -"
        html = response.content.decode("utf-8")
        self.assertNotIn("e mais -", html)

    def test_three_pending_remaining_zero(self):
        self._add_won_leads(3)
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["won_leads_pending"], 3)
        self.assertEqual(response.context["won_leads_pending_remaining"], 0)
        self.assertEqual(len(response.context["won_leads_pending_preview"]), 3)
        html = response.content.decode("utf-8")
        self.assertNotIn("e mais -", html)

    def test_eight_pending_remaining_three(self):
        self._add_won_leads(8)
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["won_leads_pending"], 8)
        self.assertEqual(response.context["won_leads_pending_remaining"], 3)
        self.assertEqual(len(response.context["won_leads_pending_preview"]), 5)
        html = response.content.decode("utf-8")
        self.assertNotIn("e mais -", html)


# ============================================================================
# Cenário 4 — Cascata de proposta delete
# ============================================================================

class Cenario4ProposalCascadeDeleteTests(TestCase):
    """delete_entries=1 deve apagar pendentes, preservar pagas, e mensagem
    deve mostrar count correto."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="cenario-4")
        self.user = create_test_user("c4@t.com", "C4", self.empresa)
        self.client.force_login(self.user)
        from apps.crm.models import Pipeline, PipelineStage
        from apps.crm.models import Lead
        from apps.proposals.models import Proposal
        p = Pipeline.objects.create(empresa=self.empresa, name="P")
        s = PipelineStage.objects.create(pipeline=p, name="N", order=0)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="C4 Lead", pipeline_stage=s,
        )
        self.proposal = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="C4 Proposta", discount_percent=Decimal("0"),
        )

    def test_cascade_preserves_paid_entries(self):
        from apps.finance.models import FinancialEntry
        from apps.proposals.models import Proposal

        # 2 pendentes
        pending_ids = []
        for i in range(2):
            e = FinancialEntry.objects.create(
                empresa=self.empresa, type="income",
                description=f"Pendente{i}",
                amount=Decimal("100.00"),
                date=date(2026, 6, 15),
                status="pending",
                related_proposal=self.proposal,
            )
            pending_ids.append(e.pk)

        # 1 paga
        paid = FinancialEntry.objects.create(
            empresa=self.empresa, type="income",
            description="Paga",
            amount=Decimal("100.00"),
            date=date(2026, 6, 15),
            status="paid",
            paid_date=date(2026, 6, 16),
            related_proposal=self.proposal,
        )

        # POST delete com delete_entries=1
        response = self.client.post(
            reverse("proposals:delete", args=[self.proposal.pk]),
            data={"delete_entries": "1"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        # Proposta foi soft-deleted
        self.proposal.refresh_from_db()
        self.assertIsNotNone(self.proposal.deleted_at)

        # Pendentes apagadas
        self.assertEqual(
            FinancialEntry.objects.filter(pk__in=pending_ids).count(), 0,
            "Pendentes deveriam ter sido apagadas",
        )
        # Paga preservada
        self.assertEqual(
            FinancialEntry.objects.filter(pk=paid.pk).count(), 1,
            "Entry PAGA NUNCA deve ser apagada (preserva caixa)",
        )

        # Mensagem inclui "2 lançamento"
        msgs = list(response.context["messages"])
        msg_text = " ".join(str(m) for m in msgs)
        self.assertIn("2 lançamento", msg_text)


# ============================================================================
# Cenário 5 — Backfill sem spam de notificações
# ============================================================================

class Cenario5BackfillNoSpamTests(TestCase):
    """backfill_won_lead_entries() processa N leads e NÃO chama notify."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="cenario-5")
        from apps.crm.models import Pipeline, PipelineStage
        p = Pipeline.objects.create(empresa=self.empresa, name="P")
        self.s_ganho = PipelineStage.objects.create(
            pipeline=p, name="G", order=0, is_won=True,
        )

    def test_backfill_5_leads_no_notify(self):
        from apps.crm.models import Lead
        from apps.finance.models import FinancialEntry
        from apps.finance.services import backfill_won_lead_entries

        # 5 leads em won_stage sem entry (suppress)
        for i in range(5):
            lead = Lead(
                empresa=self.empresa,
                name=f"Lead{i}",
                estimated_value=Decimal("500.00"),
                pipeline_stage=self.s_ganho,
            )
            lead._suppress_finance_entry = True
            lead.save()
        # Confirma: 0 entries
        self.assertEqual(
            FinancialEntry.objects.filter(empresa=self.empresa).count(), 0,
        )

        # Roda backfill com mock
        with patch("apps.finance.services._notify_lead_won") as mock_notify:
            result = backfill_won_lead_entries(self.empresa)

        # 5 entries criadas
        self.assertEqual(result["scanned"], 5)
        self.assertEqual(len(result["created"]), 5)
        self.assertEqual(
            FinancialEntry.objects.filter(empresa=self.empresa).count(), 5,
        )
        # _notify_lead_won NUNCA foi chamado
        mock_notify.assert_not_called()


# ============================================================================
# Cenário 6 — Eventos cross-source não criam dupla entry
# ============================================================================

class Cenario6NoDoubleEntryFromCrossEventsTests(TestCase):
    """Regra LEAD_CRIADO → mover pra outra stage que é WON. Verifica que
    apesar de cadeia de eventos (criar + mover), só 1 entry é criada."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="cenario-6")
        from apps.crm.models import Pipeline, PipelineStage
        self.pipeline = Pipeline.objects.create(
            empresa=self.empresa, name="P", is_default=True,
        )
        self.s_novo = PipelineStage.objects.create(
            pipeline=self.pipeline, name="Novo", order=0,
        )
        self.s_ganho = PipelineStage.objects.create(
            pipeline=self.pipeline, name="Ganho", order=1, is_won=True,
        )

    def test_only_one_entry_on_lead_created_to_won(self):
        from apps.automation.models import PipelineAutomationRule
        from apps.crm.models import Lead
        from apps.finance.models import FinancialEntry

        # Regra: LEAD_CRIADO → Ganho (won)
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Criado → Ganho",
            event=PipelineAutomationRule.Event.LEAD_CRIADO,
            target_pipeline=self.pipeline, target_stage=self.s_ganho,
            is_active=True,
        )

        # Lead novo em "Novo" — depois move pra Ganho pela regra
        with self.captureOnCommitCallbacks(execute=True):
            lead = Lead.objects.create(
                empresa=self.empresa,
                name="C6 Lead",
                estimated_value=Decimal("1000.00"),
                pipeline_stage=self.s_novo,
            )

        lead.refresh_from_db()
        # Verifica: regra moveu pra Ganho
        self.assertEqual(lead.pipeline_stage_id, self.s_ganho.pk)
        # SÓ 1 entry criada (não 2+)
        entries = FinancialEntry.objects.filter(related_lead=lead)
        self.assertEqual(
            entries.count(), 1,
            f"Esperado 1 entry, encontrado {entries.count()} — "
            f"sequência de eventos pode estar duplicando",
        )


# ============================================================================
# Cenário 7 — Calendário range cruza ano
# ============================================================================

class Cenario7CalendarRangeAcrossYearsTests(TestCase):
    """OS scheduled=2026-12-30, expected_end=2027-01-05.
    GET ?year=2026&month=12 mostra 30, 31. GET ?year=2027&month=1 mostra 1-5."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="cenario-7")
        self.user = create_test_user("c7@t.com", "C7", self.empresa)
        self.client.force_login(self.user)

    def test_os_spans_year_boundary(self):
        from apps.operations.models import WorkOrder

        wo = WorkOrder.objects.create(
            empresa=self.empresa,
            title="OS Cruza Ano",
            status=WorkOrder.Status.SCHEDULED,
            priority=WorkOrder.Priority.MEDIUM,
            scheduled_date=date(2026, 12, 30),
            expected_end_date=date(2027, 1, 5),
        )

        # GET dezembro/2026
        url_dec = reverse("operations:calendar")
        resp_dec = self.client.get(url_dec + "?year=2026&month=12")
        self.assertEqual(resp_dec.status_code, 200)
        wo_by_day_dec = resp_dec.context["wo_by_day"]
        # 30 e 31 devem ter a WO
        self.assertIn(30, wo_by_day_dec, f"Dia 30 ausente. keys={list(wo_by_day_dec.keys())}")
        self.assertIn(31, wo_by_day_dec, f"Dia 31 ausente. keys={list(wo_by_day_dec.keys())}")
        # WO referenciada
        self.assertIn(wo, wo_by_day_dec[30])
        self.assertIn(wo, wo_by_day_dec[31])

        # GET janeiro/2027 — dias 1, 2, 3, 4, 5
        resp_jan = self.client.get(url_dec + "?year=2027&month=1")
        self.assertEqual(resp_jan.status_code, 200)
        wo_by_day_jan = resp_jan.context["wo_by_day"]
        for d in (1, 2, 3, 4, 5):
            self.assertIn(d, wo_by_day_jan, f"Dia {d}/jan ausente.")
            self.assertIn(wo, wo_by_day_jan[d])
        # Dia 6 NÃO deve ter
        self.assertNotIn(6, wo_by_day_jan, "Dia 6 não deveria ter a OS")


# ============================================================================
# Cenário 8 — Checklist OS persistente
# ============================================================================

class Cenario8ChecklistPersistentTests(TestCase):
    """work_order_create com checklist_json — depois update mantendo apenas
    1 item editado deve deletar os outros."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="cenario-8")
        self.user = create_test_user("c8@t.com", "C8", self.empresa)
        self.client.force_login(self.user)

    def test_checklist_create_then_replace(self):
        from apps.operations.models import WorkOrder, WorkOrderChecklist

        # 1. CREATE com 2 itens (checklist_json sem ID)
        checklist = [
            {"description": "Item 1", "is_completed": False},
            {"description": "Item 2", "is_completed": False},
        ]
        create_url = reverse("operations:work_order_create")
        resp = self.client.post(
            create_url,
            data={
                "title": "OS C8",
                "service_type": "",
                "priority": "medium",
                "description": "",
                "scheduled_date": "2026-07-01",
                "scheduled_time": "",
                "expected_end_date": "2026-07-05",
                "location": "",
                "google_maps_url": "",
                "notes": "",
                "checklist_json": json.dumps(checklist),
                "cloud_storage_links_json": "",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200, resp.content[:500])
        wo = WorkOrder.objects.filter(empresa=self.empresa).first()
        self.assertIsNotNone(wo, "WorkOrder não foi criada")

        items = list(wo.checklist_items.all().order_by("order"))
        self.assertEqual(
            len(items), 2,
            f"Esperado 2 itens, encontrado {len(items)}: {[i.description for i in items]}",
        )
        existing_id_1 = items[0].pk
        existing_id_2 = items[1].pk

        # 2. UPDATE — mantém apenas o item_1 editado (item_2 será deletado)
        update_url = reverse("operations:work_order_update", args=[wo.pk])
        updated = [
            {"id": existing_id_1, "description": "Item 1 EDITADO", "is_completed": False},
        ]
        resp2 = self.client.post(
            update_url,
            data={
                "title": "OS C8",
                "service_type": "",
                "priority": "medium",
                "description": "",
                "scheduled_date": "2026-07-01",
                "scheduled_time": "",
                "expected_end_date": "2026-07-05",
                "location": "",
                "google_maps_url": "",
                "notes": "",
                "checklist_json": json.dumps(updated),
                "cloud_storage_links_json": "",
            },
            follow=True,
        )
        self.assertEqual(resp2.status_code, 200, resp2.content[:500])

        # Verificações
        wo.refresh_from_db()
        items_after = list(wo.checklist_items.all())
        self.assertEqual(
            len(items_after), 1,
            f"Esperado 1 item após update, encontrado {len(items_after)}",
        )
        self.assertEqual(items_after[0].description, "Item 1 EDITADO")
        self.assertEqual(items_after[0].pk, existing_id_1)
        # Item 2 deletado
        self.assertFalse(
            WorkOrderChecklist.objects.filter(pk=existing_id_2).exists(),
            "Item 2 deveria ter sido deletado",
        )


# ============================================================================
# Cenário 9 — Inline actions do chatbot
# ============================================================================

class Cenario9InlineActionsTests(TestCase):
    """Bloco 'message' com inline_actions=[register_event] → dispatch_action
    é chamado E log é criado."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="cenario-9")

    def test_inline_action_fires_and_logs(self):
        from apps.chatbot.builder.services.flow_executor import start_session_v2
        from apps.chatbot.models import (
            ChatbotExecutionLog, ChatbotFlow, ChatbotFlowVersion,
        )

        flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="F9", channel="webchat", is_active=True,
        )
        graph = {
            "schema_version": 1,
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "metadata": {},
            "nodes": [
                {
                    "id": "s1", "type": "start",
                    "position": {"x": 0, "y": 0}, "data": {},
                },
                {
                    "id": "m1", "type": "message",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "text": "Bem-vindo!",
                        "inline_actions": [
                            {
                                "action_type": "register_event",
                                "event_name": "welcome_c9",
                            },
                        ],
                    },
                },
                {
                    "id": "e1", "type": "end",
                    "position": {"x": 0, "y": 0},
                    "data": {"completion_message": "Pronto"},
                },
            ],
            "edges": [
                {
                    "id": "e1", "source": "s1", "target": "m1",
                    "sourceHandle": "next", "targetHandle": "in",
                },
                {
                    "id": "e2", "source": "m1", "target": "e1",
                    "sourceHandle": "next", "targetHandle": "in",
                },
            ],
        }
        version = ChatbotFlowVersion.objects.create(
            flow=flow,
            graph_json=graph,
            status=ChatbotFlowVersion.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        flow.use_visual_builder = True
        flow.current_published_version = version
        flow.save()

        with patch(
            "apps.chatbot.action_handlers.dispatch_action",
            return_value={"ok": True, "message": "ok"},
        ) as mock_dispatch:
            result = start_session_v2(flow)

        self.assertTrue(result["is_complete"])
        # dispatch_action chamado com register_event
        mock_dispatch.assert_called()
        called_types = [c.args[0] for c in mock_dispatch.call_args_list]
        self.assertIn("register_event", called_types)

        # Log inline_action_executing E inline_action_executed criados
        execing_logs = ChatbotExecutionLog.objects.filter(
            event="inline_action_executing",
        )
        executed_logs = ChatbotExecutionLog.objects.filter(
            event="inline_action_executed",
        )
        self.assertGreaterEqual(
            execing_logs.count(), 1,
            "Esperava ao menos 1 log inline_action_executing",
        )
        self.assertGreaterEqual(
            executed_logs.count(), 1,
            "Esperava ao menos 1 log inline_action_executed",
        )


# ============================================================================
# Cenário 10 — expected_end_date editável após auto-calc
# ============================================================================

class Cenario10ExpectedEndDateRespectsExplicitTests(TestCase):
    """ServiceType.default_prazo_dias=10. POST sem expected_end → auto-calc.
    PUT com explícito → mantém valor explícito."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="cenario-10")
        self.user = create_test_user("c10@t.com", "C10", self.empresa)
        self.client.force_login(self.user)

    def test_explicit_end_date_is_preserved(self):
        from apps.operations.models import ServiceType, WorkOrder

        st = ServiceType.objects.create(
            empresa=self.empresa,
            name="Topografia",
            default_prazo_dias=10,
            is_active=True,
        )

        # CREATE — sem expected_end_date → backend deveria calcular
        scheduled = date(2026, 8, 1)
        expected_auto = scheduled + timedelta(days=10)  # 2026-08-11
        create_url = reverse("operations:work_order_create")
        resp = self.client.post(
            create_url,
            data={
                "title": "OS C10",
                "service_type": str(st.pk),
                "priority": "medium",
                "description": "",
                "scheduled_date": "2026-08-01",
                "scheduled_time": "",
                "expected_end_date": "",  # vazio → auto-calc
                "location": "",
                "google_maps_url": "",
                "notes": "",
                "checklist_json": "",
                "cloud_storage_links_json": "",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200, resp.content[:500])
        wo = WorkOrder.objects.filter(
            empresa=self.empresa, title="OS C10",
        ).first()
        self.assertIsNotNone(wo)
        self.assertEqual(
            wo.expected_end_date, expected_auto,
            f"Auto-calc falhou: esperado {expected_auto}, "
            f"got {wo.expected_end_date}",
        )

        # UPDATE — com expected_end_date EXPLÍCITO (diferente)
        explicit_end = date(2026, 8, 20)
        update_url = reverse("operations:work_order_update", args=[wo.pk])
        resp2 = self.client.post(
            update_url,
            data={
                "title": "OS C10",
                "service_type": str(st.pk),
                "priority": "medium",
                "description": "",
                "scheduled_date": "2026-08-01",
                "scheduled_time": "",
                "expected_end_date": "2026-08-20",  # explícito
                "location": "",
                "google_maps_url": "",
                "notes": "",
                "checklist_json": "",
                "cloud_storage_links_json": "",
            },
            follow=True,
        )
        self.assertEqual(resp2.status_code, 200, resp2.content[:500])
        wo.refresh_from_db()
        self.assertEqual(
            wo.expected_end_date, explicit_end,
            f"Valor explícito sobrescrito: esperado {explicit_end}, "
            f"got {wo.expected_end_date}",
        )

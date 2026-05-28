"""RV10 — Tests de REGRESSÃO para os bugs do pente fino do dia.

Cinco bugs identificados e corrigidos:

1. CRÍTICO — Automação de pipeline → won_stage suprimia geração de
   FinancialEntry (flag `_suppress_automation` reusada em duplo papel).
   Quebrava o fluxo central do RV10. Fix: separar em
   `_suppress_pipeline_automation` (anti-loop) e `_suppress_finance_entry`
   (raro; só pra seeds/scripts). `_maybe_generate_finance_entry` agora
   roda mesmo quando regra de automação move o lead.

2. CRÍTICO — save_installments sem `@transaction.atomic`. Se a 5ª de 10
   parcelas falhasse, as 4 anteriores ficavam órfãs. Fix: envolver loop
   em `with transaction.atomic()`.

3. CRÍTICO — Banner "leads ganhos sem lançamento" mostrava "…e mais -5"
   por uso errado de filtros add+length+add. Fix: calcular `remaining`
   na view e usar diretamente no template.

4. GRAVE — Cascata na exclusão de proposta fazia count() + delete()
   em queries separadas (race). Fix: usar tuple-return de .delete().

5. GRAVE — backfill_won_lead_entries chamava notify N vezes (uma por
   lead × N membros). Fix: novo parâmetro `notify=False` em
   generate_entry_from_lead_won, usado no backfill.

Cada bug tem teste dedicado para garantir que NÃO volte.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.automation.models import PipelineAutomationRule
from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.finance.forms import FinancialEntryForm
from apps.finance.models import FinancialEntry
from apps.finance.services import (
    backfill_won_lead_entries, generate_entry_from_lead_won,
)
from apps.proposals.models import Proposal
from apps.core.tests.helpers import (
    create_pipeline_for_empresa, create_test_empresa, create_test_user,
)


# ===========================================================================
# Hotfix #1 (CRÍTICO): automação de pipeline NÃO bloqueia geração de entry
# ===========================================================================


class AutomationPipelineDoesNotSuppressFinanceEntryTests(TestCase):
    """Cenário do bug: user cria regra 'Proposta Aceita → mover pra Ganho'.
    Ao aceitar proposta, automação move lead para won_stage. ANTES do fix,
    a flag `_suppress_automation` setada pelo `_apply_rule` impedia o
    signal de gerar a FinancialEntry — quebrando o fluxo do RV10 (lead
    aparecia no banner 'pendente de lançamento')."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-hf1")
        create_test_user("a@t.com", "A", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.pipeline = Pipeline.objects.filter(
            empresa=self.empresa, is_default=True,
        ).first()
        stages = list(self.pipeline.stages.order_by("order"))
        self.s_inicial = stages[0]
        # Última stage é o "Ganho" — marca is_won=True
        self.s_ganho = stages[-1]
        self.s_ganho.is_won = True
        self.s_ganho.save()

    def test_rule_moving_lead_to_won_creates_finance_entry(self):
        """A regra que move lead pra won_stage DEVE gerar FinancialEntry."""
        # Regra: PROPOSTA_ACEITA → mover pra Ganho
        PipelineAutomationRule.objects.create(
            empresa=self.empresa, name="Aceita → Ganho",
            event=PipelineAutomationRule.Event.PROPOSTA_ACEITA,
            target_pipeline=self.pipeline, target_stage=self.s_ganho,
            is_active=True,
        )
        lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente",
            estimated_value=Decimal("2500.00"),
            pipeline_stage=self.s_inicial,
        )
        # Cria proposta DRAFT
        proposal = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="P",
            discount_percent=Decimal("0"),
        )
        # Aceita a proposta → dispara signal → execute_proposal_event
        # → _apply_rule move lead pra Ganho com _suppress_automation=True
        with self.captureOnCommitCallbacks(execute=True):
            proposal.status = Proposal.Status.ACCEPTED
            proposal.save()
        # Lead foi movido pra Ganho
        lead.refresh_from_db()
        self.assertEqual(lead.pipeline_stage_id, self.s_ganho.pk)
        # FinancialEntry FOI criada (este é o fix do bug)
        entries = FinancialEntry.objects.filter(related_lead=lead)
        self.assertEqual(entries.count(), 1, "Entry deveria ter sido criada")
        self.assertEqual(entries.first().amount, Decimal("2500.00"))

    def test_suppress_finance_entry_flag_still_works_for_scripts(self):
        """Flag dedicada `_suppress_finance_entry` permite scripts/seeds
        criarem leads em won_stage sem entry (uso intencional)."""
        lead = Lead(
            empresa=self.empresa, name="Script",
            estimated_value=Decimal("1000.00"),
            pipeline_stage=self.s_ganho,  # já em won
        )
        lead._suppress_finance_entry = True
        lead.save()
        self.assertEqual(
            FinancialEntry.objects.filter(related_lead=lead).count(), 0,
        )


# ===========================================================================
# Hotfix #2 (CRÍTICO): save_installments é atômico
# ===========================================================================


class InstallmentsAreAtomicTests(TestCase):
    """Se a 5ª de 10 parcelas falhar, as 4 anteriores devem fazer rollback."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-hf2")

    def test_failure_mid_loop_rolls_back_all_entries(self):
        """Simula erro na 3ª parcela; nenhuma deve persistir."""
        form = FinancialEntryForm(
            data={
                "type": "income", "description": "Teste rollback",
                "amount": "900.00", "date": "2026-06-01",
                "status": "pending",
                "is_installment": "on", "installment_count": "3",
                "installment_interval_days": "30",
            },
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)

        # Faz o save explodir na 3ª chamada
        original_save = FinancialEntry.save
        call_count = {"n": 0}

        def flaky_save(self, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 3:
                raise RuntimeError("simulated DB failure")
            return original_save(self, *args, **kwargs)

        with patch.object(FinancialEntry, "save", flaky_save):
            with self.assertRaises(RuntimeError):
                form.save_installments(self.empresa)

        # Todas as parcelas devem ter sido revertidas (atomic)
        self.assertEqual(
            FinancialEntry.objects.filter(empresa=self.empresa).count(), 0,
            "Rollback falhou — parcelas órfãs ficaram no banco",
        )


# ===========================================================================
# Hotfix #3 (CRÍTICO): "…e mais N" mostra valor correto, não "-5"
# ===========================================================================


class BannerRemainingCountTests(TestCase):
    """Bug: o template fazia `won_leads_pending|add:preview|length|add:"-5"`
    que com 0 pendentes retornava `-5` literal. Fix: calcular `remaining`
    na view, garantindo `max(0, N - 5)`."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-hf3")
        self.user = create_test_user("b@t.com", "B", self.empresa)
        self.client.force_login(self.user)
        p = Pipeline.objects.create(empresa=self.empresa, name="P")
        self.s_ganho = PipelineStage.objects.create(
            pipeline=p, name="G", order=0, is_won=True,
        )

    def _create_lead_in_won(self, name):
        lead = Lead(
            empresa=self.empresa, name=name, pipeline_stage=self.s_ganho,
        )
        lead._suppress_finance_entry = True
        lead.save()
        return lead

    def test_no_pending_remaining_is_zero(self):
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["won_leads_pending_remaining"], 0)
        # E o template NÃO mostra "…e mais -X"
        self.assertNotContains(response, "e mais -")

    def test_three_pending_remaining_is_zero(self):
        """3 leads → preview mostra 3, remaining=0 (não negativo)."""
        for i in range(3):
            self._create_lead_in_won(f"L{i}")
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["won_leads_pending"], 3)
        self.assertEqual(response.context["won_leads_pending_remaining"], 0)
        self.assertNotContains(response, "e mais -")

    def test_eight_pending_remaining_is_three(self):
        """8 leads → preview mostra 5, remaining=3."""
        for i in range(8):
            self._create_lead_in_won(f"L{i}")
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["won_leads_pending"], 8)
        self.assertEqual(response.context["won_leads_pending_remaining"], 3)
        self.assertContains(response, "e mais 3")


# ===========================================================================
# Hotfix #4 (GRAVE): cascata usa tuple-return de delete()
# ===========================================================================


class CascadeDeleteUsesTupleReturnTests(TestCase):
    """Antes: .count() + .delete() em queries separadas (race).
    Agora: tuple-return único de .delete()."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-hf4")
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client.force_login(self.user)
        p = Pipeline.objects.create(empresa=self.empresa, name="P")
        s = PipelineStage.objects.create(pipeline=p, name="N", order=0)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="L", pipeline_stage=s,
        )
        self.proposal = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="P",
            discount_percent=Decimal("0"),
        )

    def test_cascade_message_reports_correct_count(self):
        """Cria 2 pendentes, cascateia, mensagem deve dizer '2'."""
        for i in range(2):
            FinancialEntry.objects.create(
                empresa=self.empresa, type="income",
                description=f"E{i}", amount=Decimal("100"),
                date="2026-06-15", status="pending",
                related_proposal=self.proposal,
            )
        response = self.client.post(
            reverse("proposals:delete", args=[self.proposal.pk]),
            data={"delete_entries": "1"},
            follow=True,
        )
        msgs = list(response.context["messages"])
        msg_text = " ".join(str(m) for m in msgs)
        # Mensagem inclui "2 lançamento" (cascata reportada corretamente)
        self.assertIn("2 lançamento", msg_text)


# ===========================================================================
# Hotfix #5 (GRAVE): backfill não dispara notify por lead
# ===========================================================================


class BackfillDoesNotSpamNotificationsTests(TestCase):
    """Backfill processa N leads em lote. Antes: chamava _notify_lead_won
    por lead × membro = N×M notificações. Agora: notify=False no backfill,
    user vê só a mensagem de retorno consolidada."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-hf5")
        p = Pipeline.objects.create(empresa=self.empresa, name="P")
        self.s_ganho = PipelineStage.objects.create(
            pipeline=p, name="G", order=0, is_won=True,
        )

    def test_backfill_does_not_call_notify(self):
        """Cria 3 leads em won; backfill NÃO chama _notify_lead_won."""
        for i in range(3):
            lead = Lead(
                empresa=self.empresa, name=f"L{i}",
                estimated_value=Decimal("500"),
                pipeline_stage=self.s_ganho,
            )
            lead._suppress_finance_entry = True
            lead.save()
        # Mock pra spy se foi chamado
        with patch("apps.finance.services._notify_lead_won") as mock_notify:
            result = backfill_won_lead_entries(self.empresa)
        self.assertEqual(len(result["created"]), 3)
        mock_notify.assert_not_called()

    def test_direct_call_still_notifies_by_default(self):
        """Chamada direta (não-backfill) MANTÉM notify=True por default."""
        lead = Lead(
            empresa=self.empresa, name="Direto",
            estimated_value=Decimal("500"),
            pipeline_stage=self.s_ganho,
        )
        lead._suppress_finance_entry = True
        lead.save()
        with patch("apps.finance.services._notify_lead_won") as mock_notify:
            generate_entry_from_lead_won(lead)  # notify=True default
        mock_notify.assert_called_once()

    def test_explicit_notify_false_does_not_notify(self):
        lead = Lead(
            empresa=self.empresa, name="Silencioso",
            estimated_value=Decimal("500"),
            pipeline_stage=self.s_ganho,
        )
        lead._suppress_finance_entry = True
        lead.save()
        with patch("apps.finance.services._notify_lead_won") as mock_notify:
            generate_entry_from_lead_won(lead, notify=False)
        mock_notify.assert_not_called()

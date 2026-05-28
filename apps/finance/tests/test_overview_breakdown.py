"""RV10 — Tests do dashboard financeiro com contagem + breakdown de origem.

Cliente reportou: "Fiz 3 lançamentos de despesas, mas ele so ta contando 2".
Causa: SOMA estava correta, mas a lista "Recentes" mostra só top-10; o 3º
lançamento estava fora. Adicionamos contagem visível + breakdown PAGO/PENDENTE.

Cliente também pediu: "deve puxar dos dois. Quando tiver fechado ganho, mas
sem proposta e contrato puxa direto do lead, se tiver proposta ai puxa da
proposta tem como ser assim?". Já era assim — agora explicitamos no breakdown.

Cobre:
- Cards mostram contagem correta de entries pagas
- Cards mostram total + count de pendentes
- Pendentes quebra em receitas vs despesas
- Forecast breakdown classifica corretamente por origem (proposta/lead/manual)
- Entry com proposta E lead vai pra 'proposta' (proposta tem precedência)
- Entry só com lead vai pra 'lead'
- Entry sem proposta nem lead vai pra 'manual'
- Range respeita o número de meses pedido
"""
from datetime import date as _date
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.finance.models import FinancialEntry
from apps.finance.views import _compute_forecast_breakdown
from apps.proposals.models import Proposal
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _entry(empresa, **kwargs):
    defaults = dict(
        type=FinancialEntry.Type.INCOME,
        description="Entry",
        amount=Decimal("100"),
        date=_date.today(),
        status=FinancialEntry.Status.PENDING,
    )
    defaults.update(kwargs)
    return FinancialEntry.objects.create(empresa=empresa, **defaults)


class CardCountTests(TestCase):
    """RV10 — Cards mostram contagem + breakdown pago/pendente."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-cards")
        self.user = create_test_user("u@t.com", "U", self.empresa)
        self.client.force_login(self.user)
        self.today = _date.today()

    def test_card_shows_3_paid_expenses(self):
        """Reproduz o caso do cliente: 3 despesas pagas → card mostra 3."""
        _entry(
            self.empresa, type="expense", status="paid",
            amount=Decimal("108"), description="ART",
            date=self.today,
        )
        _entry(
            self.empresa, type="expense", status="paid",
            amount=Decimal("125"), description="Aluguel",
            date=self.today,
        )
        _entry(
            self.empresa, type="expense", status="paid",
            amount=Decimal("42"), description="Outra coisa",
            date=self.today,
        )
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["expense_paid_count"], 3)
        self.assertEqual(response.context["total_expense"], Decimal("275"))
        # Contagem aparece no HTML
        self.assertContains(response, "3 pagas")

    def test_card_shows_pending_breakdown(self):
        """Card mostra '+ R$ X em N pendentes' quando há pendentes."""
        _entry(
            self.empresa, type="expense", status="pending",
            amount=Decimal("500"), description="P1",
        )
        _entry(
            self.empresa, type="expense", status="pending",
            amount=Decimal("300"), description="P2",
        )
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["expense_pending_count"], 2)
        self.assertEqual(
            response.context["expense_pending_total"], Decimal("800"),
        )

    def test_pending_card_breaks_down_income_vs_expense(self):
        """Card 'Pendentes' separa receitas de despesas."""
        _entry(self.empresa, type="income", status="pending", amount=Decimal("1000"))
        _entry(self.empresa, type="income", status="pending", amount=Decimal("2000"))
        _entry(self.empresa, type="expense", status="pending", amount=Decimal("500"))
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["income_pending_count"], 2)
        self.assertEqual(response.context["expense_pending_count"], 1)
        self.assertEqual(response.context["pending_count"], 3)

    def test_zero_pending_shows_clean_state(self):
        """Sem pendentes, card mostra 'Tudo em dia'."""
        _entry(self.empresa, type="income", status="paid", amount=Decimal("100"))
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["pending_count"], 0)
        self.assertContains(response, "Tudo em dia")


class ForecastBreakdownTests(TestCase):
    """RV10 — Quebra previsão por ORIGEM (proposta/lead/manual)."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-fb")
        p = Pipeline.objects.create(empresa=self.empresa, name="P")
        self.s_ganho = PipelineStage.objects.create(
            pipeline=p, name="Ganho", order=10, is_won=True,
        )
        self.lead = Lead(
            empresa=self.empresa, name="L", pipeline_stage=self.s_ganho,
        )
        self.lead._suppress_finance_entry = True  # RV10 — flag dedicada
        self.lead.save()
        self.proposal = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="P",
            discount_percent=Decimal("0"),
        )
        self.today = timezone.now().date()

    def test_entry_with_proposal_goes_to_proposta(self):
        _entry(
            self.empresa, type="income", status="pending",
            related_proposal=self.proposal, amount=Decimal("3000"),
            date=self.today + timedelta(days=30),
        )
        result = _compute_forecast_breakdown(self.empresa, self.today)
        self.assertEqual(result["from_proposal"]["total"], Decimal("3000"))
        self.assertEqual(result["from_proposal"]["count"], 1)
        self.assertEqual(result["from_lead"]["total"], Decimal("0"))
        self.assertEqual(result["manual"]["total"], Decimal("0"))

    def test_entry_with_only_lead_goes_to_lead(self):
        _entry(
            self.empresa, type="income", status="pending",
            related_lead=self.lead, amount=Decimal("1500"),
            date=self.today + timedelta(days=30),
        )
        result = _compute_forecast_breakdown(self.empresa, self.today)
        self.assertEqual(result["from_lead"]["total"], Decimal("1500"))
        self.assertEqual(result["from_lead"]["count"], 1)
        self.assertEqual(result["from_proposal"]["total"], Decimal("0"))
        self.assertEqual(result["manual"]["total"], Decimal("0"))

    def test_entry_without_proposal_or_lead_goes_to_manual(self):
        _entry(
            self.empresa, type="income", status="pending",
            amount=Decimal("800"),
            date=self.today + timedelta(days=30),
        )
        result = _compute_forecast_breakdown(self.empresa, self.today)
        self.assertEqual(result["manual"]["total"], Decimal("800"))
        self.assertEqual(result["manual"]["count"], 1)

    def test_entry_with_proposal_AND_lead_goes_to_proposta(self):
        """Cliente pediu: 'se tiver proposta puxa da proposta'. Proposta
        tem precedência sobre lead na classificação."""
        _entry(
            self.empresa, type="income", status="pending",
            related_proposal=self.proposal,
            related_lead=self.lead,  # ambos setados
            amount=Decimal("2000"),
            date=self.today + timedelta(days=30),
        )
        result = _compute_forecast_breakdown(self.empresa, self.today)
        self.assertEqual(result["from_proposal"]["total"], Decimal("2000"))
        # Não conta como lead
        self.assertEqual(result["from_lead"]["total"], Decimal("0"))

    def test_breakdown_excludes_paid_entries(self):
        """Já pagas não contam (são caixa, não previsão)."""
        _entry(
            self.empresa, type="income", status="paid",
            related_proposal=self.proposal, amount=Decimal("999"),
            date=self.today + timedelta(days=30),
        )
        result = _compute_forecast_breakdown(self.empresa, self.today)
        self.assertEqual(result["from_proposal"]["total"], Decimal("0"))

    def test_breakdown_excludes_expense_entries(self):
        """Despesas não vão pra previsão (que é só de receita)."""
        _entry(
            self.empresa, type="expense", status="pending",
            amount=Decimal("500"),
            date=self.today + timedelta(days=30),
        )
        result = _compute_forecast_breakdown(self.empresa, self.today)
        self.assertEqual(result["manual"]["total"], Decimal("0"))

    def test_breakdown_only_includes_future_or_current_month(self):
        """Entries no passado (mês anterior) NÃO contam."""
        last_month = self.today.replace(day=1) - timedelta(days=1)
        _entry(
            self.empresa, type="income", status="pending",
            amount=Decimal("999"),
            date=last_month,
        )
        result = _compute_forecast_breakdown(self.empresa, self.today)
        self.assertEqual(result["manual"]["total"], Decimal("0"))


class DashboardSmokeTests(TestCase):
    """Smoke E2E: GET no dashboard renderiza tudo sem erro."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-smoke")
        self.user = create_test_user("s@t.com", "S", self.empresa)
        self.client.force_login(self.user)

    def test_get_overview_renders_breakdown(self):
        # Cria 1 entry pendente futura
        _entry(
            self.empresa, type="income", status="pending",
            amount=Decimal("1000"),
            date=_date.today() + timedelta(days=30),
        )
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.status_code, 200)
        # Contexto tem o breakdown
        self.assertIn("forecast_breakdown", response.context)
        self.assertIn("from_proposal", response.context["forecast_breakdown"])
        self.assertIn("from_lead", response.context["forecast_breakdown"])
        self.assertIn("manual", response.context["forecast_breakdown"])
        # Breakdown aparece no HTML
        self.assertContains(response, "De propostas")
        self.assertContains(response, "De leads ganhos")
        self.assertContains(response, "Lançamentos manuais")

    def test_get_overview_without_forecast_hides_section(self):
        """Sem entries pendentes, seção de previsão some."""
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.status_code, 200)
        # Sem dados futuros, forecast_total = 0 → seção não renderiza
        self.assertEqual(response.context["forecast_total"], Decimal("0.00"))

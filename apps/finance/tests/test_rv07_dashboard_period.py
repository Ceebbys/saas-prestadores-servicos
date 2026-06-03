"""RV07 — Item 1.3: filtro de período do dashboard financeiro.

Cliente pediu: "tem q ter como filtra para vê o mês q vc quiser e tbm ter a
visão de todo o período e não ir trocando os dados do dashboard".
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.finance.models import FinancialEntry
from apps.finance.views import _finance_period_range


class FinancePeriodRangeHelperTests(TestCase):
    """Régua de datas determinística (não depende de 'hoje')."""

    def test_mes_atual(self):
        s, e, label = _finance_period_range("mes_atual", date(2026, 6, 15))
        self.assertEqual(s, date(2026, 6, 1))
        self.assertEqual(e, date(2026, 6, 30))
        self.assertEqual(label, "Mês atual")

    def test_3m_includes_current_month(self):
        s, e, _ = _finance_period_range("3m", date(2026, 6, 15))
        self.assertEqual(s, date(2026, 4, 1))
        self.assertEqual(e, date(2026, 6, 30))

    def test_3m_crosses_year_boundary(self):
        s, e, _ = _finance_period_range("3m", date(2026, 2, 10))
        self.assertEqual(s, date(2025, 12, 1))
        self.assertEqual(e, date(2026, 2, 28))

    def test_12m(self):
        s, e, _ = _finance_period_range("12m", date(2026, 6, 15))
        self.assertEqual(s, date(2025, 7, 1))
        self.assertEqual(e, date(2026, 6, 30))

    def test_ano(self):
        s, e, label = _finance_period_range("ano", date(2026, 6, 15))
        self.assertEqual(s, date(2026, 1, 1))
        self.assertEqual(e, date(2026, 12, 31))
        self.assertEqual(label, "Ano de 2026")

    def test_tudo_has_no_bounds(self):
        s, e, label = _finance_period_range("tudo", date(2026, 6, 15))
        self.assertIsNone(s)
        self.assertIsNone(e)
        self.assertEqual(label, "Todo o período")

    def test_mes_especifico(self):
        s, e, label = _finance_period_range("mes", date(2026, 6, 15), "2026-03")
        self.assertEqual(s, date(2026, 3, 1))
        self.assertEqual(e, date(2026, 3, 31))
        self.assertEqual(label, "Março/2026")

    def test_mes_especifico_fevereiro_bissexto(self):
        s, e, _ = _finance_period_range("mes", date(2024, 6, 15), "2024-02")
        self.assertEqual(s, date(2024, 2, 1))
        self.assertEqual(e, date(2024, 2, 29))  # 2024 é bissexto

    def test_mes_invalido_cai_para_mes_atual(self):
        s, e, label = _finance_period_range("mes", date(2026, 6, 15), "xxxx")
        self.assertEqual(label, "Mês atual")


class FinancePeriodViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-period")
        self.user = create_test_user("p@t.com", "P", self.empresa)
        self.client.force_login(self.user)
        self.today = date.today()

    def _income(self, amount, when):
        return FinancialEntry.objects.create(
            empresa=self.empresa,
            type=FinancialEntry.Type.INCOME,
            description="Receita",
            amount=Decimal(amount),
            date=when,
            status=FinancialEntry.Status.PAID,
        )

    def test_mes_atual_only_current_month(self):
        self._income("100", self.today)
        self._income("500", self.today - timedelta(days=400))  # fora de qualquer janela curta

        resp = self.client.get(reverse("finance:finance_overview"))  # default mes_atual
        self.assertEqual(resp.context["current_period"], "mes_atual")
        self.assertEqual(resp.context["total_income"], Decimal("100"))

    def test_tudo_includes_everything(self):
        self._income("100", self.today)
        self._income("500", self.today - timedelta(days=400))

        resp = self.client.get(reverse("finance:finance_overview"), {"period": "tudo"})
        self.assertEqual(resp.context["current_period"], "tudo")
        self.assertEqual(resp.context["total_income"], Decimal("600"))

    def test_invalid_period_falls_back_to_mes_atual(self):
        resp = self.client.get(reverse("finance:finance_overview"), {"period": "xpto"})
        self.assertEqual(resp.context["current_period"], "mes_atual")

    def test_specific_month_filter(self):
        self._income("250", date(2025, 1, 15))  # Janeiro/2025
        self._income("999", self.today)         # mês atual (não deve contar)

        resp = self.client.get(
            reverse("finance:finance_overview"), {"period": "mes", "mes": "2025-01"},
        )
        self.assertEqual(resp.context["current_period"], "mes")
        self.assertEqual(resp.context["selected_month"], "2025-01")
        self.assertEqual(resp.context["total_income"], Decimal("250"))
        self.assertEqual(resp.context["period_label"], "Janeiro/2025")

    def test_specific_month_invalid_falls_back(self):
        resp = self.client.get(
            reverse("finance:finance_overview"), {"period": "mes", "mes": "bad"},
        )
        self.assertEqual(resp.context["current_period"], "mes_atual")
        self.assertEqual(resp.context["selected_month"], "")

    def test_forecast_unchanged_by_period(self):
        """A Previsão de receita é consolidada — não muda com o período."""
        resp_mes = self.client.get(reverse("finance:finance_overview"))
        resp_tudo = self.client.get(reverse("finance:finance_overview"), {"period": "tudo"})
        self.assertEqual(
            resp_mes.context["forecast_total"], resp_tudo.context["forecast_total"]
        )

"""RV06 — Previsão de receita por mês no overview financeiro."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.finance.models import FinancialEntry
from apps.finance.views import _compute_revenue_forecast
from apps.core.tests.helpers import create_test_empresa


def _entry(empresa, amount, date_val, status=FinancialEntry.Status.PENDING,
           type_=FinancialEntry.Type.INCOME):
    return FinancialEntry.objects.create(
        empresa=empresa,
        type=type_,
        description="x",
        amount=Decimal(str(amount)),
        date=date_val,
        status=status,
    )


class RevenueForecastTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-forecast")
        self.today = date(2026, 5, 15)

    def test_empty_returns_zero_for_all_months(self):
        result = _compute_revenue_forecast(self.empresa, self.today, months=3)
        self.assertEqual(len(result["months"]), 3)
        self.assertEqual(result["total"], Decimal("0.00"))
        for m in result["months"]:
            self.assertEqual(m["total"], Decimal("0.00"))
            self.assertEqual(m["count"], 0)

    def test_pending_income_counted(self):
        _entry(self.empresa, 1000, date(2026, 5, 20))  # mês atual
        _entry(self.empresa, 2000, date(2026, 6, 15))  # próximo
        _entry(self.empresa, 500, date(2026, 5, 25))   # mês atual
        result = _compute_revenue_forecast(self.empresa, self.today, months=3)
        self.assertEqual(result["months"][0]["total"], Decimal("1500.00"))  # maio
        self.assertEqual(result["months"][0]["count"], 2)
        self.assertEqual(result["months"][1]["total"], Decimal("2000.00"))  # junho
        self.assertEqual(result["months"][1]["count"], 1)
        self.assertEqual(result["total"], Decimal("3500.00"))
        self.assertEqual(result["max"], Decimal("2000.00"))

    def test_paid_NOT_counted_in_forecast(self):
        """Receitas já pagas não aparecem em forecast (já estão no caixa)."""
        _entry(self.empresa, 5000, date(2026, 5, 20),
               status=FinancialEntry.Status.PAID)
        _entry(self.empresa, 1000, date(2026, 5, 25),
               status=FinancialEntry.Status.PENDING)
        result = _compute_revenue_forecast(self.empresa, self.today, months=3)
        self.assertEqual(result["months"][0]["total"], Decimal("1000.00"))

    def test_expense_NOT_counted(self):
        _entry(self.empresa, 800, date(2026, 5, 20),
               type_=FinancialEntry.Type.EXPENSE)
        result = _compute_revenue_forecast(self.empresa, self.today, months=3)
        self.assertEqual(result["total"], Decimal("0.00"))

    def test_overdue_counted(self):
        """status=OVERDUE também conta (ainda receita esperada)."""
        _entry(self.empresa, 1500, date(2026, 5, 1),
               status=FinancialEntry.Status.OVERDUE)
        result = _compute_revenue_forecast(self.empresa, self.today, months=3)
        self.assertEqual(result["months"][0]["total"], Decimal("1500.00"))

    def test_year_rollover(self):
        """6 meses partindo de novembro cobre nov/dez/jan/fev/mar/abr ano seguinte."""
        nov_15 = date(2026, 11, 15)
        result = _compute_revenue_forecast(self.empresa, nov_15, months=6)
        labels = [m["label"] for m in result["months"]]
        self.assertEqual(labels[0], "Nov/26")
        self.assertEqual(labels[1], "Dez/26")
        self.assertEqual(labels[2], "Jan/27")
        self.assertEqual(labels[5], "Abr/27")

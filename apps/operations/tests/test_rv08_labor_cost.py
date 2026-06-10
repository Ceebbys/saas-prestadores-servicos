"""RV08 (7.1) — Valor-hora aplicado a apontamentos antigos + custo operacional.

Cobre os dois sintomas do PDF:
- "configurei o valor-hora mas a OS continua dizendo que não está configurado";
- horas registradas precisam virar custo operacional (despesa) automaticamente.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.finance.models import FinancialEntry
from apps.finance.services import generate_labor_cost_entry
from apps.operations.models import HourRate, WorkOrder, WorkOrderTimeLog
from apps.operations.services import backfill_null_rates


def _finalized_log(wo, user, hours=2, rate=None):
    now = timezone.now()
    return WorkOrderTimeLog.objects.create(
        work_order=wo, user=user,
        started_at=now - timedelta(hours=hours), ended_at=now,
        duration_seconds=hours * 3600, is_billable=True,
        rate_applied=rate,
    )


class LaborCostRV08Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-labor")
        self.user = create_test_user("l@t.com", "L", self.empresa)
        self.wo = WorkOrder.objects.create(empresa=self.empresa, title="OS Custo")

    def test_backfill_prices_logs_created_before_rate(self):
        log = _finalized_log(self.wo, self.user, hours=3, rate=None)
        HourRate.objects.create(
            empresa=self.empresa, scope="team", hourly_value=Decimal("50"),
        )
        affected = backfill_null_rates(self.empresa)
        log.refresh_from_db()
        self.assertIn(self.wo.pk, affected)
        self.assertEqual(log.rate_applied, Decimal("50"))
        self.assertEqual(log.rate_source, "equipe")

    def test_generate_labor_cost_entry_creates_expense(self):
        HourRate.objects.create(
            empresa=self.empresa, scope="team", hourly_value=Decimal("50"),
        )
        _finalized_log(self.wo, self.user, hours=10, rate=None)  # 10h
        entry = generate_labor_cost_entry(self.wo)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.type, FinancialEntry.Type.EXPENSE)
        self.assertEqual(entry.amount, Decimal("500.00"))  # 10h × R$50
        self.assertTrue(entry.auto_generated)
        self.assertEqual(entry.related_work_order_id, self.wo.pk)

    def test_generate_is_idempotent(self):
        HourRate.objects.create(
            empresa=self.empresa, scope="team", hourly_value=Decimal("50"),
        )
        _finalized_log(self.wo, self.user, hours=2, rate=None)
        generate_labor_cost_entry(self.wo)
        generate_labor_cost_entry(self.wo)
        qs = FinancialEntry.objects.filter(
            related_work_order=self.wo, auto_generated=True,
            type=FinancialEntry.Type.EXPENSE,
        )
        self.assertEqual(qs.count(), 1)

    def test_zero_cost_removes_entry(self):
        HourRate.objects.create(
            empresa=self.empresa, scope="team", hourly_value=Decimal("50"),
        )
        log = _finalized_log(self.wo, self.user, hours=2, rate=None)
        generate_labor_cost_entry(self.wo)
        self.assertEqual(
            FinancialEntry.objects.filter(related_work_order=self.wo).count(), 1,
        )
        # Sem horas faturáveis → remove a despesa auto-gerada
        log.delete()
        generate_labor_cost_entry(self.wo)
        self.assertEqual(
            FinancialEntry.objects.filter(related_work_order=self.wo).count(), 0,
        )

    def test_hourrate_signal_resyncs_existing_logs(self):
        log = _finalized_log(self.wo, self.user, hours=4, rate=None)
        with self.captureOnCommitCallbacks(execute=True):
            HourRate.objects.create(
                empresa=self.empresa, scope="team", hourly_value=Decimal("80"),
            )
        log.refresh_from_db()
        self.assertEqual(log.rate_applied, Decimal("80"))
        self.assertTrue(
            FinancialEntry.objects.filter(
                related_work_order=self.wo, auto_generated=True,
                type=FinancialEntry.Type.EXPENSE,
            ).exists()
        )

    def test_detail_view_backfills_and_hides_warning(self):
        self.client.force_login(self.user)
        _finalized_log(self.wo, self.user, hours=1, rate=None)
        HourRate.objects.create(
            empresa=self.empresa, scope="team", hourly_value=Decimal("50"),
        )
        resp = self.client.get(
            reverse("operations:work_order_detail", args=[self.wo.pk]),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Valor-hora não configurado")
        self.assertContains(resp, "Custo operacional")

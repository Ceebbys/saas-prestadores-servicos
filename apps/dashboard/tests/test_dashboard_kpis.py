"""Tests for the 4 new strategic KPIs on the Dashboard."""

from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)
from apps.crm.models import Lead, LeadContact, Opportunity


class DashboardKPITests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("kpi@t.com", "KPI", self.empresa)
        self.pipeline, self.s0, self.s1, self.s_won = create_pipeline_for_empresa(
            self.empresa
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _dashboard_context(self):
        resp = self.client.get(reverse("dashboard:index"))
        self.assertEqual(resp.status_code, 200)
        return resp.context

    def test_avg_lead_closure_days_no_data(self):
        ctx = self._dashboard_context()
        self.assertEqual(ctx["avg_lead_closure_days"], 0)

    def test_followup_rate_no_data(self):
        ctx = self._dashboard_context()
        self.assertEqual(ctx["followup_rate"], 0)

    def test_followup_rate_with_contacts(self):
        # Create 4 leads, 3 with a LeadContact
        now = timezone.now()
        created = []
        for i in range(4):
            lead = Lead.objects.create(empresa=self.empresa, name=f"L{i}")
            Lead.objects.filter(pk=lead.pk).update(created_at=now)
            created.append(lead)
        for lead in created[:3]:
            LeadContact.objects.create(
                empresa=self.empresa, lead=lead, channel="phone"
            )
        ctx = self._dashboard_context()
        self.assertEqual(ctx["followup_total"], 4)
        self.assertEqual(ctx["followup_contacted"], 3)
        self.assertEqual(ctx["followup_rate"], 75.0)

    def test_avg_lead_closure_days_with_won_opp(self):
        # Create lead + opportunity and mark it won with known delta (5 days)
        lead = Lead.objects.create(empresa=self.empresa, name="Won Lead")
        opp = lead.opportunities.first()
        five_days_ago = timezone.now() - timedelta(days=5)
        Lead.objects.filter(pk=lead.pk).update(created_at=five_days_ago)
        opp.current_stage = self.s_won
        opp.won_at = timezone.now()
        opp.save()

        ctx = self._dashboard_context()
        self.assertGreaterEqual(ctx["avg_lead_closure_days"], 4)

    def test_overdue_rate_pct(self):
        from apps.finance.models import FinancialEntry

        today = timezone.now().date()
        # Create receivables: R$1000 total, R$300 overdue
        FinancialEntry.objects.create(
            empresa=self.empresa,
            type="income",
            status="paid",
            date=today.replace(day=1),
            paid_date=today.replace(day=1),
            amount=Decimal("700"),
            description="Paid",
        )
        FinancialEntry.objects.create(
            empresa=self.empresa,
            type="income",
            status="pending",
            date=today - timedelta(days=10),
            amount=Decimal("300"),
            description="Overdue",
        )
        ctx = self._dashboard_context()
        self.assertEqual(ctx["overdue_rate_pct"], 30.0)

    def test_avg_wo_execution_days(self):
        from apps.operations.models import WorkOrder

        scheduled = timezone.now().date() - timedelta(days=3)
        wo = WorkOrder.objects.create(
            empresa=self.empresa,
            title="WO test",
            status="completed",
            scheduled_date=scheduled,
            completed_at=timezone.now(),
        )
        ctx = self._dashboard_context()
        self.assertGreaterEqual(ctx["avg_wo_execution_days"], 2)

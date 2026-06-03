"""RV07 — Item 3.1: contador de horas da OS + valor-hora configurável."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Membership
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.operations.models import (
    HourRate,
    JobRole,
    WorkOrder,
    WorkOrderTimeLog,
)
from apps.operations.services import resolve_hour_rate


class ResolveHourRateTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-rates")
        self.user = create_test_user("u@t.com", "U", self.empresa)

    def _set_role(self, role):
        m = Membership.objects.get(user=self.user, empresa=self.empresa)
        m.job_role = role
        m.save(update_fields=["job_role"])

    def test_no_rate_returns_none(self):
        rate, source = resolve_hour_rate(self.empresa, self.user)
        self.assertIsNone(rate)
        self.assertEqual(source, "")

    def test_team_rate(self):
        HourRate.objects.create(empresa=self.empresa, scope="team", hourly_value=Decimal("100"))
        rate, source = resolve_hour_rate(self.empresa, self.user)
        self.assertEqual(rate, Decimal("100"))
        self.assertEqual(source, "equipe")

    def test_job_role_overrides_team(self):
        HourRate.objects.create(empresa=self.empresa, scope="team", hourly_value=Decimal("100"))
        role = JobRole.objects.create(empresa=self.empresa, name="Topógrafo")
        self._set_role(role)
        HourRate.objects.create(
            empresa=self.empresa, scope="job_role", job_role=role, hourly_value=Decimal("150"),
        )
        rate, source = resolve_hour_rate(self.empresa, self.user)
        self.assertEqual(rate, Decimal("150"))
        self.assertEqual(source, "funcao")

    def test_user_rate_overrides_all(self):
        HourRate.objects.create(empresa=self.empresa, scope="team", hourly_value=Decimal("100"))
        role = JobRole.objects.create(empresa=self.empresa, name="Topógrafo")
        self._set_role(role)
        HourRate.objects.create(
            empresa=self.empresa, scope="job_role", job_role=role, hourly_value=Decimal("150"),
        )
        HourRate.objects.create(
            empresa=self.empresa, scope="user", user=self.user, hourly_value=Decimal("200"),
        )
        rate, source = resolve_hour_rate(self.empresa, self.user)
        self.assertEqual(rate, Decimal("200"))
        self.assertEqual(source, "responsavel")

    def test_inactive_rate_ignored(self):
        HourRate.objects.create(
            empresa=self.empresa, scope="team", hourly_value=Decimal("100"), is_active=False,
        )
        rate, _ = resolve_hour_rate(self.empresa, self.user)
        self.assertIsNone(rate)


class TimerViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-timer")
        self.user = create_test_user("t@t.com", "T", self.empresa)
        self.client.force_login(self.user)
        self.wo = WorkOrder.objects.create(empresa=self.empresa, title="OS Teste")

    def test_start_creates_running_log_and_advances_status(self):
        self.client.post(reverse("operations:timer_start", args=[self.wo.pk]))
        self.assertEqual(self.wo.time_logs.filter(ended_at__isnull=True).count(), 1)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.Status.IN_PROGRESS)

    def test_start_twice_idempotent(self):
        self.client.post(reverse("operations:timer_start", args=[self.wo.pk]))
        self.client.post(reverse("operations:timer_start", args=[self.wo.pk]))
        self.assertEqual(self.wo.time_logs.filter(ended_at__isnull=True).count(), 1)

    def test_stop_closes_and_snapshots_rate(self):
        HourRate.objects.create(empresa=self.empresa, scope="team", hourly_value=Decimal("120"))
        self.client.post(reverse("operations:timer_start", args=[self.wo.pk]))
        log = self.wo.time_logs.get(ended_at__isnull=True)
        log.started_at = timezone.now() - timedelta(hours=1)
        log.save(update_fields=["started_at"])

        self.client.post(reverse("operations:timer_stop", args=[self.wo.pk, log.pk]))
        log.refresh_from_db()
        self.assertIsNotNone(log.ended_at)
        self.assertGreater(log.duration_seconds, 0)
        self.assertEqual(log.rate_applied, Decimal("120"))
        self.assertEqual(log.rate_source, "equipe")
        self.assertGreater(log.billable_value, Decimal("0"))

    def test_cross_tenant_start_404(self):
        other = create_test_empresa(slug="rv07-timer-other")
        other_user = create_test_user("o@t.com", "O", other)
        self.client.force_login(other_user)
        resp = self.client.post(reverse("operations:timer_start", args=[self.wo.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_edit_preserves_rate_snapshot(self):
        """Pente fino: editar um apontamento encerrado NÃO re-precifica pela
        tarifa atual — preserva o preço histórico."""
        log = WorkOrderTimeLog.objects.create(
            work_order=self.wo, user=self.user,
            started_at=timezone.now() - timedelta(hours=1),
            ended_at=timezone.now(), duration_seconds=3600,
            is_billable=True, rate_applied=Decimal("100"), rate_source="equipe",
        )
        # Empresa sobe a tarifa depois
        HourRate.objects.create(empresa=self.empresa, scope="team", hourly_value=Decimal("500"))
        start = log.started_at.strftime("%Y-%m-%dT%H:%M")
        end = log.ended_at.strftime("%Y-%m-%dT%H:%M")
        self.client.post(
            reverse("operations:time_log_update", args=[self.wo.pk, log.pk]),
            {"started_at": start, "ended_at": end, "is_billable": "on", "notes": "obs nova"},
        )
        log.refresh_from_db()
        self.assertEqual(log.rate_applied, Decimal("100"))  # preservado, não 500
        self.assertEqual(log.notes, "obs nova")


class ManualTimeLogTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-manual")
        self.user = create_test_user("m@t.com", "M", self.empresa)
        self.client.force_login(self.user)
        self.wo = WorkOrder.objects.create(empresa=self.empresa, title="OS")

    def test_manual_with_duration(self):
        start = timezone.now().replace(microsecond=0)
        self.client.post(reverse("operations:time_log_create", args=[self.wo.pk]), {
            "started_at": start.strftime("%Y-%m-%dT%H:%M"),
            "duration_minutes": "90",
            "is_billable": "on",
        })
        log = self.wo.time_logs.get()
        self.assertEqual(log.duration_seconds, 90 * 60)
        self.assertEqual(log.source, WorkOrderTimeLog.Source.MANUAL)
        self.assertTrue(log.is_billable)

    def test_manual_end_before_start_invalid(self):
        start = timezone.now().replace(microsecond=0)
        self.client.post(reverse("operations:time_log_create", args=[self.wo.pk]), {
            "started_at": start.strftime("%Y-%m-%dT%H:%M"),
            "ended_at": (start - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(self.wo.time_logs.count(), 0)

    def test_billable_value_zero_when_not_billable(self):
        log = WorkOrderTimeLog.objects.create(
            work_order=self.wo, user=self.user,
            started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now(), duration_seconds=7200,
            is_billable=False, rate_applied=Decimal("100"),
        )
        self.assertEqual(log.billable_value, Decimal("0.00"))

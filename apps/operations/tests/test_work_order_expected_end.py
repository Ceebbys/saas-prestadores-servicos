"""RV10 — Tests do campo `expected_end_date` em WorkOrder.

Cliente pediu: "colocar na os previsão de término. pq ai vai para o
calendario e ocara vê quem ta garrado ou não. AI a previsão se for de
serviço cadastrado puxa de lá mas pode ficar editavel para o cara ajustar"

Cobre:
- Form auto-calcula expected_end_date quando vazia (scheduled_date + prazo)
- User pode sobrescrever (campo editável)
- Sem service_type → sem cálculo
- Sem default_prazo_dias → sem cálculo
- Calendário inclui OS no range scheduled→expected_end (não só dia inicial)
- Calendário NÃO duplica OS de 1 dia (start=end)
- OS com expected_end_date no próximo mês ainda aparece nos dias do mês atual
"""
from datetime import date as _date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.operations.forms import WorkOrderForm
from apps.operations.models import ServiceType, WorkOrder
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _make_lead(empresa):
    p = Pipeline.objects.create(empresa=empresa, name="P", is_default=True)
    stage = PipelineStage.objects.create(pipeline=p, name="Novo", order=0)
    return Lead.objects.create(
        empresa=empresa, name="Cliente", phone="11999990000",
        pipeline_stage=stage,
    )


class WorkOrderFormExpectedEndTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-end-form")
        self.lead = _make_lead(self.empresa)
        self.servico = ServiceType.objects.create(
            empresa=self.empresa, name="Topografia",
            default_prazo_dias=15,
        )

    def _data(self, **extras):
        data = {
            "title": "OS",
            "lead": self.lead.pk,
            "priority": "medium",
            "scheduled_date": "2026-06-01",
            "service_type": self.servico.pk,
            "checklist_json": "",
        }
        data.update(extras)
        return data

    def test_auto_calculates_when_empty(self):
        """scheduled_date + service_type.default_prazo_dias → expected_end_date."""
        form = WorkOrderForm(data=self._data(), empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        # 01/06/2026 + 15 dias = 16/06/2026
        self.assertEqual(
            form.cleaned_data["expected_end_date"], _date(2026, 6, 16),
        )

    def test_user_value_is_preserved(self):
        """Se user informou, o cálculo NÃO sobrescreve."""
        form = WorkOrderForm(
            data=self._data(expected_end_date="2026-07-15"),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["expected_end_date"], _date(2026, 7, 15),
        )

    def test_no_service_type_no_calculation(self):
        """Sem serviço selecionado, não calcula nada."""
        form = WorkOrderForm(
            data=self._data(service_type=""),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data.get("expected_end_date"))

    def test_service_type_without_prazo_no_calculation(self):
        """Service type sem default_prazo_dias → não calcula."""
        servico_sem_prazo = ServiceType.objects.create(
            empresa=self.empresa, name="Avulso",
            default_prazo_dias=None,
        )
        form = WorkOrderForm(
            data=self._data(service_type=servico_sem_prazo.pk),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data.get("expected_end_date"))

    def test_no_scheduled_date_no_calculation(self):
        """Sem data agendada, não calcula término."""
        form = WorkOrderForm(
            data=self._data(scheduled_date=""),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data.get("expected_end_date"))


class CalendarRangeTests(TestCase):
    """Calendário mostra a OS em todos os dias do range."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-cal")
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.lead = _make_lead(self.empresa)
        self.client.force_login(self.user)

    def _wo(self, **kwargs):
        defaults = dict(
            empresa=self.empresa, title="WO", lead=self.lead,
            priority="medium",
        )
        defaults.update(kwargs)
        return WorkOrder.objects.create(**defaults)

    def test_os_in_single_day_appears_once(self):
        """OS sem expected_end_date só aparece no scheduled_date."""
        self._wo(scheduled_date=_date(2026, 6, 10))
        response = self.client.get(reverse("operations:calendar") + "?year=2026&month=6")
        wo_by_day = response.context["wo_by_day"]
        self.assertIn(10, wo_by_day)
        self.assertEqual(len(wo_by_day[10]), 1)
        # Não aparece em outros dias
        self.assertNotIn(11, wo_by_day)

    def test_os_with_range_appears_each_day(self):
        """OS de 3 dias aparece em 3 dias consecutivos."""
        self._wo(
            scheduled_date=_date(2026, 6, 10),
            expected_end_date=_date(2026, 6, 12),
        )
        response = self.client.get(reverse("operations:calendar") + "?year=2026&month=6")
        wo_by_day = response.context["wo_by_day"]
        self.assertIn(10, wo_by_day)
        self.assertIn(11, wo_by_day)
        self.assertIn(12, wo_by_day)
        self.assertNotIn(13, wo_by_day)

    def test_os_crossing_month_boundary(self):
        """OS começa em maio, termina em junho: aparece em ambos os calendários."""
        self._wo(
            scheduled_date=_date(2026, 5, 28),
            expected_end_date=_date(2026, 6, 3),
        )
        # Calendário de maio: dias 28, 29, 30, 31
        response_may = self.client.get(reverse("operations:calendar") + "?year=2026&month=5")
        wo_by_day_may = response_may.context["wo_by_day"]
        self.assertIn(28, wo_by_day_may)
        self.assertIn(31, wo_by_day_may)
        # Calendário de junho: dias 1, 2, 3
        response_jun = self.client.get(reverse("operations:calendar") + "?year=2026&month=6")
        wo_by_day_jun = response_jun.context["wo_by_day"]
        self.assertIn(1, wo_by_day_jun)
        self.assertIn(2, wo_by_day_jun)
        self.assertIn(3, wo_by_day_jun)
        self.assertNotIn(4, wo_by_day_jun)
        self.assertNotIn(27, wo_by_day_may)

    def test_os_outside_month_does_not_appear(self):
        """OS de julho não aparece no calendário de junho."""
        self._wo(
            scheduled_date=_date(2026, 7, 1),
            expected_end_date=_date(2026, 7, 5),
        )
        response = self.client.get(reverse("operations:calendar") + "?year=2026&month=6")
        wo_by_day = response.context["wo_by_day"]
        self.assertEqual(wo_by_day, {})


class FormViewIntegrationTests(TestCase):
    """E2E: POST cria OS com expected_end_date calculada."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-end-view")
        self.user = create_test_user("v@t.com", "V", self.empresa)
        self.lead = _make_lead(self.empresa)
        self.servico = ServiceType.objects.create(
            empresa=self.empresa, name="Levantamento",
            default_prazo_dias=10,
        )
        self.client.force_login(self.user)

    def test_post_create_calculates_end_date(self):
        response = self.client.post(
            reverse("operations:work_order_create"),
            data={
                "title": "OS Teste",
                "lead": self.lead.pk,
                "priority": "medium",
                "scheduled_date": "2026-06-15",
                "service_type": self.servico.pk,
                "checklist_json": "",
                "cloud_storage_links_json": "",
            },
        )
        self.assertIn(response.status_code, (200, 302))
        wo = WorkOrder.objects.filter(empresa=self.empresa).first()
        self.assertIsNotNone(wo)
        self.assertEqual(wo.expected_end_date, _date(2026, 6, 25))

    def test_get_create_includes_prazos_map(self):
        response = self.client.get(reverse("operations:work_order_create"))
        self.assertEqual(response.status_code, 200)
        # JSON tem o prazo do serviço
        self.assertIn(
            f'"{self.servico.pk}": 10',
            response.context["service_type_prazos_json"],
        )

"""RV07 — Smoke test de renderização: garante que todas as páginas
novas/alteradas renderizam (200) sem erro de template/URL.
"""
from django.test import TestCase
from django.urls import reverse

from apps.contacts.models import Contato
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.operations.models import HourRate, JobRole, WorkOrder


class RV07SmokeRenderTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-smoke")
        self.user = create_test_user("s@t.com", "S", self.empresa)
        self.client.force_login(self.user)
        self.pipeline = Pipeline.objects.create(
            empresa=self.empresa, name="Vendas", is_default=True,
        )
        self.stage = PipelineStage.objects.create(
            pipeline=self.pipeline, name="Novo", order=0,
        )
        self.contato = Contato.objects.create(empresa=self.empresa, name="Contato Smoke")
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Lead Smoke",
            pipeline_stage=self.stage, contato=self.contato,
        )
        self.wo = WorkOrder.objects.create(empresa=self.empresa, title="OS Smoke")

    def assert_ok(self, url_name, *args, **kwargs):
        resp = self.client.get(reverse(url_name, args=args, kwargs=kwargs))
        self.assertEqual(resp.status_code, 200, f"{url_name} -> {resp.status_code}")

    # Financeiro (1.1 / 1.3)
    def test_finance_overview_and_periods(self):
        self.assert_ok("finance:finance_overview")
        resp = self.client.get(reverse("finance:finance_overview"), {"period": "tudo"})
        self.assertEqual(resp.status_code, 200)
        self.assert_ok("finance:entry_create")

    # Pipeline (5.1) — Nova Oportunidade com seção de lead/contato
    def test_opportunity_create(self):
        self.assert_ok("crm:opportunity_create")

    # Leads (4.1) — form (com checklist) + detail (com checklist)
    def test_lead_form_and_detail(self):
        self.assert_ok("crm:lead_create")
        self.assert_ok("crm:lead_update", self.lead.pk)
        self.assert_ok("crm:lead_detail", pk=self.lead.pk)

    # Contatos (4.2) — form com múltiplos telefones + detail
    def test_contact_form_and_detail(self):
        self.assert_ok("contacts:create")
        self.assert_ok("contacts:update", pk=self.contato.pk)
        self.assert_ok("contacts:detail", pk=self.contato.pk)

    # OS (3.1) — detail com seção Tempo/Horas + form manual
    def test_work_order_detail_and_time_log_form(self):
        self.assert_ok("operations:work_order_detail", pk=self.wo.pk)
        self.assert_ok("operations:time_log_create", wo_pk=self.wo.pk)

    # Configurações (3.1) — index + CRUD de Função e Valor Hora
    def test_settings_pages(self):
        self.assert_ok("settings_app:index")
        self.assert_ok("settings_app:job_role_list")
        self.assert_ok("settings_app:job_role_create")
        self.assert_ok("settings_app:hour_rate_list")
        self.assert_ok("settings_app:hour_rate_create")
        role = JobRole.objects.create(empresa=self.empresa, name="Topógrafo")
        self.assert_ok("settings_app:job_role_update", pk=role.pk)
        rate = HourRate.objects.create(
            empresa=self.empresa, scope="team", hourly_value="100.00",
        )
        self.assert_ok("settings_app:hour_rate_update", pk=rate.pk)

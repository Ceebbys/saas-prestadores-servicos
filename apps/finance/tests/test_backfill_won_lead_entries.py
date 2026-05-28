"""RV10 — Tests do backfill de entries para leads ganhos sem entry.

Cliente reportou: "fechei 3 leads sem proposta mas não aparecem no
financeiro". O signal RV06 só dispara em saves novos; leads movidos
antes do deploy ou via script ficam sem entry. Este módulo testa o
backfill on-demand.

Cobre:
- count_won_leads_without_entry: contagem correta excluindo casos válidos
- list_won_leads_without_entry: queryset retorna apenas leads relevantes
- backfill_won_lead_entries: cria entries para leads sem entry; idempotente
- Lead com proposta auto-gerada NÃO é contado (proposta cuidou)
- Lead em lost_stage NÃO é contado
- BackfillView (POST) cria entries + redireciona com message
- View atualiza contagem para 0 após backfill (smoke E2E)
- Management command roda end-to-end
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.finance.models import FinancialEntry
from apps.finance.services import (
    backfill_won_lead_entries,
    count_won_leads_without_entry,
    list_won_leads_without_entry,
)
from apps.proposals.models import Proposal
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _pipeline_with_stages(empresa):
    p = Pipeline.objects.create(empresa=empresa, name="Vendas")
    s_novo = PipelineStage.objects.create(pipeline=p, name="Novo", order=0)
    s_ganho = PipelineStage.objects.create(
        pipeline=p, name="Ganho", order=10, is_won=True,
    )
    s_perdido = PipelineStage.objects.create(
        pipeline=p, name="Perdido", order=20, is_lost=True,
    )
    return p, s_novo, s_ganho, s_perdido


def _won_lead_without_entry(empresa, s_ganho, name="L", value=Decimal("1000")):
    """Cria lead em won_stage sem disparar o signal — simula leads antigos.

    RV10 — Usa `_suppress_finance_entry=True` (flag dedicada) para criar
    diretamente em won_stage sem que o signal gere entry. Reproduz o caso
    real: lead que já estava em won_stage antes do RV06 ou movido por
    script de import. A flag `_suppress_automation` foi separada e agora
    só previne loop de pipeline — NÃO impede criação de entry.
    """
    lead = Lead(
        empresa=empresa, name=name,
        estimated_value=value, pipeline_stage=s_ganho,
    )
    lead._suppress_finance_entry = True
    lead.save()
    return lead


class CountAndListTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-count")
        _, self.s_novo, self.s_ganho, self.s_perdido = _pipeline_with_stages(self.empresa)

    def test_empty_returns_zero(self):
        self.assertEqual(count_won_leads_without_entry(self.empresa), 0)
        self.assertEqual(list_won_leads_without_entry(self.empresa).count(), 0)

    def test_won_lead_without_entry_is_counted(self):
        _won_lead_without_entry(self.empresa, self.s_ganho, name="A")
        _won_lead_without_entry(self.empresa, self.s_ganho, name="B")
        self.assertEqual(count_won_leads_without_entry(self.empresa), 2)

    def test_lead_in_novo_stage_is_not_counted(self):
        Lead.objects.create(
            empresa=self.empresa, name="X",
            pipeline_stage=self.s_novo,
        )
        self.assertEqual(count_won_leads_without_entry(self.empresa), 0)

    def test_lead_in_lost_stage_is_not_counted(self):
        Lead.objects.create(
            empresa=self.empresa, name="Perdido",
            pipeline_stage=self.s_perdido,
        )
        self.assertEqual(count_won_leads_without_entry(self.empresa), 0)

    def test_won_lead_with_existing_entry_is_not_counted(self):
        """Lead em won_stage MAS já tem entry → não é counted (idempotência)."""
        lead = _won_lead_without_entry(self.empresa, self.s_ganho)
        FinancialEntry.objects.create(
            empresa=self.empresa,
            type=FinancialEntry.Type.INCOME,
            description="Já tem",
            amount=Decimal("500"),
            date="2026-05-15",
            related_lead=lead,
            auto_generated=True,
        )
        self.assertEqual(count_won_leads_without_entry(self.empresa), 0)

    def test_won_lead_with_proposal_entry_is_not_counted(self):
        """Lead ganho cuja proposta gerou entries é EXCLUÍDO (proposta cuidou)."""
        lead = _won_lead_without_entry(self.empresa, self.s_ganho)
        prop = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="P",
            total=Decimal("2000"),
        )
        FinancialEntry.objects.create(
            empresa=self.empresa,
            type=FinancialEntry.Type.INCOME,
            description="Da proposta",
            amount=Decimal("2000"),
            date="2026-05-15",
            related_proposal=prop,
            auto_generated=True,
        )
        self.assertEqual(count_won_leads_without_entry(self.empresa), 0)

    def test_multi_tenant_isolation(self):
        """Leads de outra empresa não contam pra esta."""
        outra = create_test_empresa(name="Outra", slug="rv10-outra")
        _, _, s_ganho_outra, _ = _pipeline_with_stages(outra)
        _won_lead_without_entry(outra, s_ganho_outra, name="Da outra")
        # Nosso empresa: zero
        self.assertEqual(count_won_leads_without_entry(self.empresa), 0)
        # Outra: 1
        self.assertEqual(count_won_leads_without_entry(outra), 1)


class BackfillHelperTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-backfill")
        _, self.s_novo, self.s_ganho, _ = _pipeline_with_stages(self.empresa)

    def test_backfill_creates_entries(self):
        _won_lead_without_entry(self.empresa, self.s_ganho, name="A", value=Decimal("1000"))
        _won_lead_without_entry(self.empresa, self.s_ganho, name="B", value=Decimal("2500"))
        _won_lead_without_entry(self.empresa, self.s_ganho, name="C", value=Decimal("500"))

        result = backfill_won_lead_entries(self.empresa)
        self.assertEqual(result["scanned"], 3)
        self.assertEqual(len(result["created"]), 3)
        self.assertEqual(result["skipped"], 0)
        # Entries criadas
        self.assertEqual(
            FinancialEntry.objects.filter(
                empresa=self.empresa, auto_generated=True,
                related_lead__isnull=False,
            ).count(),
            3,
        )

    def test_backfill_is_idempotent(self):
        _won_lead_without_entry(self.empresa, self.s_ganho, name="A")
        backfill_won_lead_entries(self.empresa)
        # Roda de novo
        result = backfill_won_lead_entries(self.empresa)
        self.assertEqual(result["scanned"], 0)
        self.assertEqual(len(result["created"]), 0)

    def test_backfill_with_no_pending_returns_empty(self):
        result = backfill_won_lead_entries(self.empresa)
        self.assertEqual(result["scanned"], 0)
        self.assertEqual(result["created"], [])


class BackfillViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-view")
        self.user = create_test_user("v@t.com", "V", self.empresa)
        _, self.s_novo, self.s_ganho, _ = _pipeline_with_stages(self.empresa)
        self.client.force_login(self.user)

    def test_post_creates_entries_and_redirects(self):
        _won_lead_without_entry(self.empresa, self.s_ganho, name="A", value=Decimal("1000"))
        _won_lead_without_entry(self.empresa, self.s_ganho, name="B", value=Decimal("2000"))

        response = self.client.post(reverse("finance:backfill_won_leads"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/finance", response.url)
        # Entries criadas
        self.assertEqual(
            FinancialEntry.objects.filter(
                empresa=self.empresa, auto_generated=True,
                related_lead__isnull=False,
            ).count(),
            2,
        )

    def test_get_returns_405(self):
        """View aceita só POST."""
        response = self.client.get(reverse("finance:backfill_won_leads"))
        self.assertEqual(response.status_code, 405)


class DashboardContextTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-dash")
        self.user = create_test_user("d@t.com", "D", self.empresa)
        _, self.s_novo, self.s_ganho, _ = _pipeline_with_stages(self.empresa)
        self.client.force_login(self.user)

    def test_dashboard_includes_won_leads_pending_count(self):
        _won_lead_without_entry(self.empresa, self.s_ganho, name="X")
        _won_lead_without_entry(self.empresa, self.s_ganho, name="Y")
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["won_leads_pending"], 2)
        # Preview tem até 5 leads
        self.assertEqual(len(response.context["won_leads_pending_preview"]), 2)
        # Smoke: o botão de sincronização aparece no HTML
        self.assertContains(response, "Sincronizar agora")

    def test_dashboard_hides_banner_when_no_pending(self):
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["won_leads_pending"], 0)
        # Banner não aparece
        self.assertNotContains(response, "Sincronizar agora")

    def test_zero_value_entries_count_in_context(self):
        """Entry auto-gerada com amount=0 aparece no contexto."""
        lead = _won_lead_without_entry(self.empresa, self.s_ganho, name="Z")
        # Cria entry com R$ 0
        FinancialEntry.objects.create(
            empresa=self.empresa,
            type=FinancialEntry.Type.INCOME,
            description="Zero",
            amount=Decimal("0"),
            date="2026-05-15",
            status=FinancialEntry.Status.PENDING,
            related_lead=lead,
            auto_generated=True,
        )
        response = self.client.get(reverse("finance:finance_overview"))
        self.assertEqual(response.context["zero_value_entries_count"], 1)


class ManagementCommandTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-cmd")
        _, self.s_novo, self.s_ganho, _ = _pipeline_with_stages(self.empresa)

    def test_dry_run_does_not_create_entries(self):
        _won_lead_without_entry(self.empresa, self.s_ganho, name="A")
        out = StringIO()
        call_command(
            "backfill_won_lead_entries", "--dry-run",
            "--empresa=rv10-cmd", stdout=out,
        )
        self.assertIn("DRY-RUN", out.getvalue())
        self.assertEqual(
            FinancialEntry.objects.filter(
                empresa=self.empresa, auto_generated=True,
            ).count(),
            0,
        )

    def test_real_run_creates_entries(self):
        _won_lead_without_entry(self.empresa, self.s_ganho, name="A")
        _won_lead_without_entry(self.empresa, self.s_ganho, name="B")
        out = StringIO()
        call_command(
            "backfill_won_lead_entries",
            "--empresa=rv10-cmd", stdout=out,
        )
        self.assertEqual(
            FinancialEntry.objects.filter(
                empresa=self.empresa, auto_generated=True,
            ).count(),
            2,
        )

    def test_unknown_empresa_returns_error(self):
        err = StringIO()
        call_command(
            "backfill_won_lead_entries",
            "--empresa=nao-existe", stderr=err,
        )
        self.assertIn("não encontrada", err.getvalue())

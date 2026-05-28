"""RV10 — Tests da exclusão de lançamento financeiro.

Cliente reportou: "não tem como excluir lançamento pendente". A coluna
Ações só tinha 'editar' e 'marcar como pago'. Sem essa view, o user só
conseguia excluir via Django admin.

Cobre:
- POST /finance/entries/<pk>/delete/ remove entry e retorna redirect
- HTMX POST retorna 204 No Content (linha some via swap)
- GET retorna 405 (apenas POST aceito)
- Excluir entry pendente, paga, vencida — todos funcionam
- Entry auto-gerada vinculada a Lead em won_stage: mensagem alerta sobre
  recriação no próximo save do lead
- Outro tenant não pode excluir
- Cascata na exclusão da proposta: opcionalmente apaga entries pendentes
- Entries PAGAS nunca são excluídas em cascata
"""
from datetime import date as _date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.finance.models import FinancialEntry
from apps.proposals.models import Proposal
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _entry(empresa, **kwargs):
    defaults = dict(
        type=FinancialEntry.Type.INCOME,
        description="Lançamento teste",
        amount=Decimal("1000"),
        date=_date(2026, 5, 15),
        status=FinancialEntry.Status.PENDING,
    )
    defaults.update(kwargs)
    return FinancialEntry.objects.create(empresa=empresa, **defaults)


class EntryDeleteViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-del")
        self.user = create_test_user("u@t.com", "U", self.empresa)
        self.client.force_login(self.user)

    def test_post_deletes_pending_entry_and_redirects(self):
        entry = _entry(self.empresa, description="Pendente")
        response = self.client.post(
            reverse("finance:entry_delete", args=[entry.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(FinancialEntry.objects.filter(pk=entry.pk).exists())

    def test_post_deletes_paid_entry(self):
        entry = _entry(
            self.empresa, status=FinancialEntry.Status.PAID,
            description="Pago",
        )
        self.client.post(reverse("finance:entry_delete", args=[entry.pk]))
        self.assertFalse(FinancialEntry.objects.filter(pk=entry.pk).exists())

    def test_post_deletes_overdue_entry(self):
        entry = _entry(
            self.empresa, status=FinancialEntry.Status.OVERDUE,
            description="Vencido",
        )
        self.client.post(reverse("finance:entry_delete", args=[entry.pk]))
        self.assertFalse(FinancialEntry.objects.filter(pk=entry.pk).exists())

    def test_get_returns_405(self):
        entry = _entry(self.empresa)
        response = self.client.get(
            reverse("finance:entry_delete", args=[entry.pk]),
        )
        self.assertEqual(response.status_code, 405)

    def test_htmx_returns_204(self):
        entry = _entry(self.empresa)
        response = self.client.post(
            reverse("finance:entry_delete", args=[entry.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get("HX-Trigger"), "entryDeleted")
        self.assertFalse(FinancialEntry.objects.filter(pk=entry.pk).exists())

    def test_cross_tenant_returns_404(self):
        outra = create_test_empresa(name="Outra", slug="rv10-outra-tenant")
        entry = _entry(outra, description="De outro tenant")
        response = self.client.post(
            reverse("finance:entry_delete", args=[entry.pk]),
        )
        self.assertEqual(response.status_code, 404)
        # Entry da outra empresa NÃO foi excluída
        self.assertTrue(FinancialEntry.objects.filter(pk=entry.pk).exists())

    def test_auto_generated_lead_entry_shows_warning(self):
        """RV06 entry vinculada a Lead em won_stage: mensagem deve avisar
        sobre recriação ao salvar o lead novamente."""
        p = Pipeline.objects.create(empresa=self.empresa, name="P")
        s_ganho = PipelineStage.objects.create(
            pipeline=p, name="Ganho", order=0, is_won=True,
        )
        lead = Lead(empresa=self.empresa, name="L", pipeline_stage=s_ganho)
        lead._suppress_automation = True
        lead.save()
        entry = _entry(
            self.empresa, auto_generated=True, related_lead=lead,
            description="Auto-gerada",
        )
        response = self.client.post(
            reverse("finance:entry_delete", args=[entry.pk]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        # Pega mensagens do request
        msgs = list(response.context["messages"])
        self.assertTrue(any("auto-gerado pelo lead" in str(m).lower() for m in msgs))


class ProposalDeleteCascadeTests(TestCase):
    """RV10 — Modal de delete da proposta oferece cascata de entries."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-cascade")
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client.force_login(self.user)
        p = Pipeline.objects.create(empresa=self.empresa, name="P")
        s = PipelineStage.objects.create(pipeline=p, name="Novo", order=0)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente", pipeline_stage=s,
        )
        self.proposal = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="P",
            discount_percent=Decimal("0"),
        )

    def test_get_modal_shows_pending_entries(self):
        _entry(
            self.empresa, related_proposal=self.proposal,
            description="Parcela 1", amount=Decimal("500"),
        )
        _entry(
            self.empresa, related_proposal=self.proposal,
            description="Parcela 2", amount=Decimal("500"),
        )
        response = self.client.get(
            reverse("proposals:delete", args=[self.proposal.pk]),
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("2 pendentes", body)
        self.assertIn("Também excluir os 2 lançamentos", body)

    def test_delete_without_cascade_keeps_entries_alive(self):
        """Sem checkbox marcado, entries sobrevivem (proposta é soft-deleted,
        FK aponta para proposta na lixeira; restaurar a proposta re-conecta)."""
        e1 = _entry(
            self.empresa, related_proposal=self.proposal,
            description="Parcela",
        )
        self.client.post(
            reverse("proposals:delete", args=[self.proposal.pk]),
        )
        # Entry sobrevive — não foi cascateado
        self.assertTrue(FinancialEntry.objects.filter(pk=e1.pk).exists())

    def test_delete_with_cascade_removes_pending_entries(self):
        """Com checkbox marcado, entries pendentes são deletados em cascata."""
        e_pending = _entry(
            self.empresa, related_proposal=self.proposal,
            description="Pendente", status=FinancialEntry.Status.PENDING,
        )
        self.client.post(
            reverse("proposals:delete", args=[self.proposal.pk]),
            data={"delete_entries": "1"},
        )
        # Pendente foi deletado
        self.assertFalse(FinancialEntry.objects.filter(pk=e_pending.pk).exists())

    def test_delete_with_cascade_preserves_paid_entries(self):
        """Entry PAGA nunca é excluída em cascata (preserva histórico de caixa)."""
        e_paid = _entry(
            self.empresa, related_proposal=self.proposal,
            description="Pago", status=FinancialEntry.Status.PAID,
        )
        e_pending = _entry(
            self.empresa, related_proposal=self.proposal,
            description="Pendente", status=FinancialEntry.Status.PENDING,
        )
        self.client.post(
            reverse("proposals:delete", args=[self.proposal.pk]),
            data={"delete_entries": "1"},
        )
        # PAGO sobrevive
        self.assertTrue(FinancialEntry.objects.filter(pk=e_paid.pk).exists())
        # PENDENTE deletado
        self.assertFalse(FinancialEntry.objects.filter(pk=e_pending.pk).exists())

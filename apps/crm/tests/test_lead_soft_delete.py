"""Testes do soft-delete + cancel button do Lead."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.crm.models import Lead, Opportunity, Pipeline, PipelineStage
from apps.contracts.models import Contract
from apps.proposals.models import Proposal
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


class LeadSoftDeleteTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("lsd@t.com", "LSD", self.empresa)
        create_pipeline_for_empresa(self.empresa)

    def test_default_manager_hides_soft_deleted(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Soft")
        lead.delete()
        self.assertFalse(Lead.objects.filter(pk=lead.pk).exists())
        self.assertTrue(Lead.all_objects.filter(pk=lead.pk).exists())

    def test_delete_cascades_to_opportunity_and_draft_proposals(self):
        """soft-delete cascateia: Opportunity (hard), Proposal pré-aceite (soft)."""
        lead = Lead.objects.create(empresa=self.empresa, name="Cascade")
        # Opportunity é criada automaticamente por signal post_save
        opp_count = lead.opportunities.count()
        self.assertGreater(opp_count, 0)

        # Cria propostas em estados diferentes
        p_draft = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="DRAFT",
            status=Proposal.Status.DRAFT, discount_percent=Decimal("0"),
        )
        p_accepted = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="ACCEPTED",
            status=Proposal.Status.ACCEPTED, discount_percent=Decimal("0"),
        )

        lead.delete()  # soft + cascade

        # Lead: soft
        self.assertIsNotNone(Lead.all_objects.get(pk=lead.pk).deleted_at)
        # Opportunity: hard (sumiu do banco)
        self.assertEqual(Opportunity.objects.filter(lead_id=lead.pk).count(), 0)
        # Proposta DRAFT: soft
        p_draft.refresh_from_db()
        self.assertIsNotNone(p_draft.deleted_at)
        # Proposta ACCEPTED: NÃO tocada
        p_accepted.refresh_from_db()
        self.assertIsNone(p_accepted.deleted_at)

    def test_contract_lead_protect_prevents_lead_delete(self):
        """Contract.lead = PROTECT: lead com contrato não pode ser excluído."""
        from django.db.models import ProtectedError

        lead = Lead.objects.create(empresa=self.empresa, name="Has Contract")
        Contract.objects.create(
            empresa=self.empresa, lead=lead, title="C1",
            value=Decimal("1000"),
        )

        with self.assertRaises(ProtectedError):
            lead.delete()  # PROTECT bloqueia mesmo soft-delete (django raises before save)

    def test_lead_list_view_hides_soft_deleted(self):
        self.client.force_login(self.user)
        alive = Lead.objects.create(empresa=self.empresa, name="alive_lead")
        dead = Lead.objects.create(empresa=self.empresa, name="dead_lead")
        dead.delete()
        resp = self.client.get(reverse("crm:lead_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"alive_lead", resp.content)
        self.assertNotIn(b"dead_lead", resp.content)


class LeadDeleteCascadeViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("ldc@t.com", "LDC", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.client.force_login(self.user)

    def test_cascade_view_soft_deletes_lead_and_redirects_to_pipeline(self):
        lead = Lead.objects.create(empresa=self.empresa, name="ToDelete")
        url = reverse("crm:lead_delete_cascade", args=[lead.pk])
        resp = self.client.post(url, follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("crm:pipeline_board"))
        lead.refresh_from_db()
        self.assertIsNotNone(lead.deleted_at)

    def test_cascade_view_404_for_other_tenant(self):
        outra = create_test_empresa(name="X", slug="x")
        lead_outra = Lead.objects.create(empresa=outra, name="outra")
        url = reverse("crm:lead_delete_cascade", args=[lead_outra.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)
        lead_outra.refresh_from_db()
        self.assertIsNone(lead_outra.deleted_at)


class LeadCancelButtonTests(TestCase):
    """Bug RV05 #10: Cancelar redirecionava para página incompleta (HTMX swap body)."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("lc@t.com", "LC", self.empresa)
        self.client.force_login(self.user)

    def test_cancel_url_defaults_to_lead_list(self):
        """Sem ?next=, cancel_url aponta para a lista de Leads."""
        resp = self.client.get(reverse("crm:lead_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.context["cancel_url"],
            reverse("crm:lead_list"),
        )

    def test_cancel_url_respects_valid_next(self):
        """?next= válido (mesmo host) é honrado."""
        resp = self.client.get(
            reverse("crm:lead_create") + "?next=/crm/pipeline/",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["cancel_url"], "/crm/pipeline/")

    def test_cancel_url_rejects_external_next(self):
        """?next=https://attacker.com cai no default (defesa open-redirect)."""
        resp = self.client.get(
            reverse("crm:lead_create") + "?next=https://attacker.com/steal",
        )
        self.assertEqual(resp.status_code, 200)
        # NÃO deve aceitar URL externa
        self.assertNotIn("attacker", resp.context["cancel_url"])
        self.assertEqual(resp.context["cancel_url"], reverse("crm:lead_list"))

    def test_cancel_link_renders_as_anchor_not_button(self):
        """O template precisa ter <a href> (não <button hx-get>)."""
        resp = self.client.get(reverse("crm:lead_create"))
        # Procura o anchor de Cancelar
        self.assertIn(b'href="/crm/leads/', resp.content)
        # NÃO deve ter hx-target=body no botão Cancelar
        # (busca por padrão problemático antigo)
        self.assertNotIn(b'hx-target="body"', resp.content[:50000])

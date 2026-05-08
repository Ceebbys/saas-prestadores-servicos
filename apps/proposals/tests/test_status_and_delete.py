"""Testes de transições de status e exclusão de propostas."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.automation.models import AutomationLog
from apps.crm.models import Lead
from apps.proposals.models import Proposal, ProposalStatusHistory
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _proposal(empresa, **kwargs):
    create_pipeline_for_empresa(empresa)
    lead = Lead.objects.create(empresa=empresa, name="Lead", email="l@e.com")
    return Proposal.objects.create(
        empresa=empresa, lead=lead, title="P",
        discount_percent=Decimal("0"),
        **kwargs,
    )


class StatusTransitionTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("st@t.com", "ST", self.empresa)
        self.client.force_login(self.user)

    def _post_status(self, proposal, status, note=""):
        url = reverse("proposals:status", args=[proposal.pk])
        return self.client.post(url, {"status": status, "note": note})

    def test_undo_accepted_returns_to_draft_and_clears_accepted_at(self):
        from django.utils import timezone

        p = _proposal(self.empresa, status=Proposal.Status.ACCEPTED)
        p.accepted_at = timezone.now()
        p.save()

        self._post_status(p, "draft")
        p.refresh_from_db()
        self.assertEqual(p.status, "draft")
        self.assertIsNone(p.accepted_at)

    def test_history_created_on_each_transition(self):
        p = _proposal(self.empresa, status=Proposal.Status.DRAFT)
        self._post_status(p, "sent")
        self._post_status(p, "accepted")
        self.assertEqual(p.status_history.count(), 2)

        history = list(p.status_history.order_by("created_at"))
        self.assertEqual(history[0].from_status, "draft")
        self.assertEqual(history[0].to_status, "sent")
        self.assertEqual(history[1].from_status, "sent")
        self.assertEqual(history[1].to_status, "accepted")

    def test_invalid_transition_blocks_change(self):
        # ACCEPTED não permite voltar direto para SENT (somente DRAFT/REJECTED/CANCELLED)
        p = _proposal(self.empresa, status=Proposal.Status.ACCEPTED)
        self._post_status(p, "sent")
        p.refresh_from_db()
        self.assertEqual(p.status, "accepted")  # não mudou

    def test_cancelled_status_allowed_from_any(self):
        p = _proposal(self.empresa, status=Proposal.Status.SENT)
        self._post_status(p, "cancelled")
        p.refresh_from_db()
        self.assertEqual(p.status, "cancelled")

    def test_rejected_can_go_back_to_accepted(self):
        p = _proposal(self.empresa, status=Proposal.Status.REJECTED)
        self._post_status(p, "accepted")
        p.refresh_from_db()
        self.assertEqual(p.status, "accepted")


class DeleteTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("d@t.com", "D", self.empresa)
        self.client.force_login(self.user)

    def test_delete_get_returns_confirm_modal(self):
        p = _proposal(self.empresa)
        url = reverse("proposals:delete", args=[p.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Excluir proposta", resp.content)
        self.assertIn(p.number.encode(), resp.content)

    def test_delete_post_removes_proposal_and_logs(self):
        p = _proposal(self.empresa)
        pk = p.pk
        number = p.number
        url = reverse("proposals:delete", args=[pk])
        resp = self.client.post(url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Proposal.objects.filter(pk=pk).exists())
        log = AutomationLog.objects.filter(
            empresa=self.empresa,
            entity_type="proposal", entity_id=pk,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get("event"), "proposal_deleted")
        self.assertEqual(log.metadata.get("number"), number)

    def test_other_tenant_cannot_delete(self):
        outra = create_test_empresa(name="Outra", slug="outra")
        p = _proposal(outra)
        url = reverse("proposals:delete", args=[p.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Proposal.objects.filter(pk=p.pk).exists())

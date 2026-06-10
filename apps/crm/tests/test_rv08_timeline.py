"""RV08 (3.2) — Timeline (histórico de movimentações) do Lead."""
from django.test import TestCase
from django.urls import reverse

from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)
from apps.crm.models import Lead, LeadEvent
from apps.proposals.models import Proposal


class LeadTimelineRV08Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-tl")
        self.user = create_test_user("tl@t.com", "TL", self.empresa)
        self.client.force_login(self.user)
        (
            self.pipeline, self.novo, self.negociando, self.fechado,
        ) = create_pipeline_for_empresa(self.empresa)

    def _lead(self):
        return Lead.objects.create(
            empresa=self.empresa, name="Lead TL", pipeline_stage=self.novo,
        )

    def test_lead_created_event(self):
        lead = self._lead()
        self.assertTrue(
            LeadEvent.objects.filter(lead=lead, event_type="lead_created").exists()
        )

    def test_won_transition_event(self):
        lead = self._lead()
        lead.pipeline_stage = self.fechado  # is_won=True
        lead.save()
        self.assertTrue(
            LeadEvent.objects.filter(lead=lead, event_type="lead_won").exists()
        )

    def test_assignee_change_event(self):
        lead = self._lead()
        lead.assigned_to = self.user
        lead.save()
        self.assertTrue(
            LeadEvent.objects.filter(lead=lead, event_type="assignee_changed").exists()
        )

    def test_stage_moved_event(self):
        lead = self._lead()
        with self.captureOnCommitCallbacks(execute=True):
            lead.pipeline_stage = self.negociando  # etapa normal (não won/lost)
            lead.save()
        self.assertTrue(
            LeadEvent.objects.filter(lead=lead, event_type="lead_moved").exists()
        )

    def test_contact_logged_event(self):
        lead = self._lead()
        self.client.post(
            reverse("crm:lead_contact_create", args=[lead.pk]),
            {"channel": "phone", "note": "Ligação de teste"},
        )
        ev = LeadEvent.objects.filter(lead=lead, event_type="contact_logged").first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.actor, self.user)

    def test_proposal_sent_event(self):
        from apps.communications.notifications_events import notify_proposal_sent

        lead = self._lead()
        proposal = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="Proposta TL",
        )
        with self.captureOnCommitCallbacks(execute=True):
            notify_proposal_sent(proposal)
        self.assertTrue(
            LeadEvent.objects.filter(lead=lead, event_type="proposal_sent").exists()
        )

    def test_timeline_rendered_on_detail(self):
        lead = self._lead()
        resp = self.client.get(reverse("crm:lead_detail", args=[lead.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Histórico de Movimentações")
        self.assertContains(resp, "Lead criado")

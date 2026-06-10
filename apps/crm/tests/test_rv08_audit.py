"""RV08 — Regressão do pente fino: mover card no board registra a timeline."""
from django.test import TestCase
from django.urls import reverse

from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)
from apps.crm.models import Lead, LeadEvent


class OpportunityMoveTimelineTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-aud-crm")
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client.force_login(self.user)
        (
            self.pipeline, self.novo, self.negociando, self.fechado,
        ) = create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Lead Board", pipeline_stage=self.novo,
        )
        # Lead criado gera uma Opportunity automaticamente (signal).
        self.opp = self.lead.opportunities.first()
        self.assertIsNotNone(self.opp)

    def test_move_to_won_logs_timeline(self):
        self.client.post(
            reverse("crm:opportunity_move", args=[self.opp.pk]),
            {"stage_id": self.fechado.pk},
        )
        self.assertTrue(
            LeadEvent.objects.filter(lead=self.lead, event_type="lead_won").exists()
        )

    def test_normal_move_logs_lead_moved(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("crm:opportunity_move", args=[self.opp.pk]),
                {"stage_id": self.negociando.pk},
            )
        self.assertTrue(
            LeadEvent.objects.filter(lead=self.lead, event_type="lead_moved").exists()
        )

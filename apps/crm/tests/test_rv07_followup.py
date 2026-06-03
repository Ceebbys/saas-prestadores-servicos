"""RV07 — Item 6.2 PART B: follow-up automático de leads (task Celery)."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.communications.models import Notification
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import (
    FollowUpSettings,
    Lead,
    LeadContact,
    LeadFollowUpReminder,
    Pipeline,
    PipelineStage,
)
from apps.crm.tasks import evaluate_lead_followups


class FollowUpTaskTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-followup")
        self.user = create_test_user("f@t.com", "F", self.empresa)
        self.p = Pipeline.objects.create(empresa=self.empresa, name="V", is_default=True)
        self.novo = PipelineStage.objects.create(pipeline=self.p, name="Novo", order=0)
        self.ganho = PipelineStage.objects.create(
            pipeline=self.p, name="Ganho", order=10, is_won=True,
        )

    def _age_lead(self, lead, days):
        Lead.objects.filter(pk=lead.pk).update(
            created_at=timezone.now() - timedelta(days=days),
        )

    def _followup_count(self, lead):
        return Notification.objects.filter(
            empresa=self.empresa,
            type=Notification.Type.LEAD_FOLLOWUP,
            payload__lead_id=lead.pk,
        ).count()

    def test_first_threshold_fires_once_idempotent(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Velho", pipeline_stage=self.novo)
        self._age_lead(lead, 8)
        evaluate_lead_followups()
        self.assertEqual(self._followup_count(lead), 1)
        self.assertTrue(
            LeadFollowUpReminder.objects.filter(lead=lead, threshold_days=7).exists()
        )
        evaluate_lead_followups()  # mesma janela → sem novo
        self.assertEqual(self._followup_count(lead), 1)

    def test_old_lead_fires_only_highest_threshold(self):
        lead = Lead.objects.create(empresa=self.empresa, name="MuitoVelho", pipeline_stage=self.novo)
        self._age_lead(lead, 200)
        evaluate_lead_followups()
        self.assertEqual(self._followup_count(lead), 1)
        self.assertTrue(
            LeadFollowUpReminder.objects.filter(lead=lead, threshold_days=90).exists()
        )
        # 7/14/30/90 todos registrados (só o 90 notificou)
        self.assertEqual(LeadFollowUpReminder.objects.filter(lead=lead).count(), 4)

    def test_won_lead_excluded(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Ganhou", pipeline_stage=self.ganho)
        self._age_lead(lead, 200)
        evaluate_lead_followups()
        self.assertEqual(self._followup_count(lead), 0)

    def test_new_contact_resets_cycle(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Reset", pipeline_stage=self.novo)
        self._age_lead(lead, 20)
        evaluate_lead_followups()  # top cruzado = 14
        self.assertEqual(self._followup_count(lead), 1)
        # novo contato 8 dias atrás → base muda → limiar 7 dispara de novo
        LeadContact.objects.create(
            empresa=self.empresa, lead=lead,
            contacted_at=timezone.now() - timedelta(days=8),
        )
        evaluate_lead_followups()
        self.assertEqual(self._followup_count(lead), 2)

    def test_disabled_settings_no_reminders(self):
        FollowUpSettings.objects.create(empresa=self.empresa, user=None, enabled=False)
        lead = Lead.objects.create(empresa=self.empresa, name="X", pipeline_stage=self.novo)
        self._age_lead(lead, 50)
        evaluate_lead_followups()
        self.assertEqual(self._followup_count(lead), 0)

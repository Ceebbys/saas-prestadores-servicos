"""RV07 — Item 6.2 PART A: notificações de eventos de pipeline/operacional."""
from decimal import Decimal

from django.test import TestCase

from apps.communications.models import Notification
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.operations.models import WorkOrder
from apps.proposals.models import Proposal


def _pipeline(empresa):
    p = Pipeline.objects.create(empresa=empresa, name="Vendas", is_default=True)
    novo = PipelineStage.objects.create(pipeline=p, name="Novo", order=0)
    contato = PipelineStage.objects.create(pipeline=p, name="Contato", order=5)
    ganho = PipelineStage.objects.create(pipeline=p, name="Ganho", order=10, is_won=True)
    return p, novo, contato, ganho


class EventNotificationTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-notif")
        self.user = create_test_user("n@t.com", "N", self.empresa)
        self.p, self.novo, self.contato, self.ganho = _pipeline(self.empresa)

    def _count(self, type_):
        return Notification.objects.filter(empresa=self.empresa, type=type_).count()

    def test_proposal_sent_and_accepted(self):
        lead = Lead.objects.create(empresa=self.empresa, name="L", pipeline_stage=self.novo)
        prop = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="P", total=Decimal("1000"),
        )
        with self.captureOnCommitCallbacks(execute=True):
            prop.status = Proposal.Status.SENT
            prop.save()
        self.assertGreaterEqual(self._count(Notification.Type.PROPOSAL_SENT), 1)

        with self.captureOnCommitCallbacks(execute=True):
            prop.status = Proposal.Status.ACCEPTED
            prop.save()
        self.assertGreaterEqual(self._count(Notification.Type.PROPOSAL_ACCEPTED), 1)

    def test_lead_moved_between_open_stages(self):
        lead = Lead.objects.create(empresa=self.empresa, name="L2", pipeline_stage=self.novo)
        with self.captureOnCommitCallbacks(execute=True):
            lead.pipeline_stage = self.contato
            lead.save()
        self.assertGreaterEqual(self._count(Notification.Type.LEAD_MOVED), 1)

    def test_move_to_won_does_not_emit_lead_moved(self):
        lead = Lead.objects.create(empresa=self.empresa, name="L3", pipeline_stage=self.novo)
        before = self._count(Notification.Type.LEAD_MOVED)
        with self.captureOnCommitCallbacks(execute=True):
            lead.pipeline_stage = self.ganho
            lead.save()
        # won não gera LEAD_MOVED (gera LEAD_WON pela finance)
        self.assertEqual(self._count(Notification.Type.LEAD_MOVED), before)

    def test_service_started_and_completed(self):
        wo = WorkOrder.objects.create(empresa=self.empresa, title="OS")
        # pending -> in_progress
        with self.captureOnCommitCallbacks(execute=True):
            self.client.force_login(self.user)
            from django.urls import reverse
            self.client.post(reverse("operations:work_order_status", args=[wo.pk]), {"status": "in_progress"})
        self.assertGreaterEqual(self._count(Notification.Type.SERVICE_STARTED), 1)
        # in_progress -> completed
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("operations:work_order_status", args=[wo.pk]), {"status": "completed"})
        self.assertGreaterEqual(self._count(Notification.Type.SERVICE_COMPLETED), 1)

    def test_timer_start_fires_service_started(self):
        """Pente fino: iniciar o cronômetro (auto-avança p/ Em Andamento)
        também notifica 'Serviço iniciado'."""
        from django.urls import reverse
        wo = WorkOrder.objects.create(empresa=self.empresa, title="OS timer")
        self.client.force_login(self.user)
        before = self._count(Notification.Type.SERVICE_STARTED)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("operations:timer_start", args=[wo.pk]))
        self.assertGreater(self._count(Notification.Type.SERVICE_STARTED), before)

    def test_suppress_notification_flag(self):
        lead = Lead.objects.create(empresa=self.empresa, name="L4", pipeline_stage=self.novo)
        before = self._count(Notification.Type.LEAD_MOVED)
        with self.captureOnCommitCallbacks(execute=True):
            lead._suppress_notification = True
            lead.pipeline_stage = self.contato
            lead.save()
        self.assertEqual(self._count(Notification.Type.LEAD_MOVED), before)

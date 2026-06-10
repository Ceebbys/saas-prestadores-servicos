"""RV08 (3.1) — Ponto roxo no card da Pipeline quando o lead tem notificação
não lida do usuário atual."""
from django.test import TestCase
from django.urls import reverse

from apps.communications.models import Notification
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)
from apps.crm.models import Lead, Opportunity

_DOT_MARKER = "Há notificações ou pendências"


class PipelineAlertDotRV08Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-dot")
        self.user = create_test_user("d@t.com", "D", self.empresa)
        self.client.force_login(self.user)
        self.pipeline, self.stage, *_ = create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="Lead Dot")
        self.opp = Opportunity.objects.create(
            empresa=self.empresa, lead=self.lead, pipeline=self.pipeline,
            current_stage=self.stage, title="Oportunidade Dot",
        )

    def _board(self):
        return self.client.get(reverse("crm:pipeline_board"))

    def test_dot_shown_when_unread_notification_with_lead_fk(self):
        Notification.objects.create(
            user=self.user, empresa=self.empresa, lead=self.lead,
            type=Notification.Type.LEAD_MOVED, title="Mudou de etapa",
        )
        self.assertContains(self._board(), _DOT_MARKER)

    def test_dot_shown_via_payload_fallback(self):
        Notification.objects.create(
            user=self.user, empresa=self.empresa,
            type=Notification.Type.LEAD_MOVED, title="Mudou",
            payload={"lead_id": self.lead.pk},
        )
        self.assertContains(self._board(), _DOT_MARKER)

    def test_no_dot_when_notification_is_read(self):
        from django.utils import timezone
        Notification.objects.create(
            user=self.user, empresa=self.empresa, lead=self.lead,
            type=Notification.Type.LEAD_MOVED, title="Lida",
            read_at=timezone.now(),
        )
        self.assertNotContains(self._board(), _DOT_MARKER)

    def test_no_dot_without_notifications(self):
        self.assertNotContains(self._board(), _DOT_MARKER)

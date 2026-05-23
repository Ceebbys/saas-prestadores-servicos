"""RV06 — Notificação quando Lead vai para WON.

Quando generate_entry_from_lead_won cria a entry, dispara Notification
para o assigned_to do Lead (ou todos os membros se sem responsável).
"""
from decimal import Decimal

from django.test import TestCase

from apps.communications.models import Notification
from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.finance.models import FinancialEntry
from apps.finance.services import generate_entry_from_lead_won
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _pipeline_won(empresa):
    p = Pipeline.objects.create(empresa=empresa, name="Vendas")
    s_won = PipelineStage.objects.create(pipeline=p, name="Ganho", is_won=True)
    return p, s_won


class LeadWonNotificationTests(TestCase):

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-notif-won")
        _, self.s_won = _pipeline_won(self.empresa)
        self.user = create_test_user("a@t.com", "A", self.empresa)

    def test_assigned_user_receives_notification(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente A",
            estimated_value=Decimal("2500.00"),
            assigned_to=self.user,
            pipeline_stage=self.s_won,
        )
        # Limpa entries criadas pelo signal pra rodar helper isolado
        FinancialEntry.objects.filter(related_lead=lead).delete()
        Notification.objects.all().delete()

        generate_entry_from_lead_won(lead)

        notifs = Notification.objects.filter(
            user=self.user, type=Notification.Type.LEAD_WON,
        )
        self.assertEqual(notifs.count(), 1)
        n = notifs.first()
        self.assertIn("Cliente A", n.title)
        self.assertIn("2.500,00", n.body)

    def test_unassigned_lead_notifies_all_members(self):
        # Mais um user na empresa
        user2 = create_test_user("b@t.com", "B", self.empresa)
        lead = Lead.objects.create(
            empresa=self.empresa, name="Sem dono",
            estimated_value=Decimal("100.00"),
            pipeline_stage=self.s_won,
            # assigned_to=None
        )
        FinancialEntry.objects.filter(related_lead=lead).delete()
        Notification.objects.all().delete()

        generate_entry_from_lead_won(lead)

        # Ambos os users receberam
        self.assertEqual(
            Notification.objects.filter(type=Notification.Type.LEAD_WON, user=self.user).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(type=Notification.Type.LEAD_WON, user=user2).count(),
            1,
        )

    def test_zero_value_notification_has_warning(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="Sem valor",
            assigned_to=self.user,
            pipeline_stage=self.s_won,
        )
        FinancialEntry.objects.filter(related_lead=lead).delete()
        Notification.objects.all().delete()

        generate_entry_from_lead_won(lead)

        n = Notification.objects.get(user=self.user, type=Notification.Type.LEAD_WON)
        self.assertIn("Valor não definido", n.body)

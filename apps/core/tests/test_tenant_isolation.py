"""Testes de isolamento multi-tenant.

Verifica que dados de uma empresa nunca vazam para outra.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.automation.models import AutomationLog
from apps.chatbot.models import ChatbotFlow
from apps.contracts.models import Contract
from apps.crm.models import Lead
from apps.finance.models import FinancialEntry
from apps.operations.models import WorkOrder
from apps.proposals.models import Proposal

from .helpers import create_two_tenants


class TenantIsolationTests(TestCase):
    """Dados de empresa_a nunca visíveis para user_b e vice-versa."""

    def setUp(self):
        t = create_two_tenants()
        self.empresa_a = t["empresa_a"]
        self.user_a = t["user_a"]
        self.empresa_b = t["empresa_b"]
        self.user_b = t["user_b"]

        # Dados empresa_a
        self.lead_a = Lead.objects.create(
            empresa=self.empresa_a, name="Lead A",
        )
        self.proposal_a = Proposal.objects.create(
            empresa=self.empresa_a, lead=self.lead_a, title="Prop A",
        )
        self.contract_a = Contract.objects.create(
            empresa=self.empresa_a, lead=self.lead_a, title="Cont A",
            content="...", value=Decimal("1000"),
        )
        self.wo_a = WorkOrder.objects.create(
            empresa=self.empresa_a, lead=self.lead_a, title="OS A",
        )
        self.entry_a = FinancialEntry.objects.create(
            empresa=self.empresa_a, type=FinancialEntry.Type.INCOME,
            description="Entry A", amount=Decimal("500"), date=timezone.now().date(),
        )
        self.flow_a = ChatbotFlow.objects.create(
            empresa=self.empresa_a, name="Flow A",
        )
        self.log_a = AutomationLog.objects.create(
            empresa=self.empresa_a,
            action=AutomationLog.Action.FULL_PIPELINE,
            entity_type=AutomationLog.EntityType.LEAD,
            entity_id=self.lead_a.pk,
        )

        # Dados empresa_b
        self.lead_b = Lead.objects.create(
            empresa=self.empresa_b, name="Lead B",
        )

    # ---- List isolation ----

    def test_lead_list_isolation(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("crm:lead_list"))
        self.assertEqual(resp.status_code, 200)
        leads = list(resp.context["object_list"])
        self.assertIn(self.lead_a, leads)
        self.assertNotIn(self.lead_b, leads)

    def test_proposal_list_isolation(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("proposals:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.proposal_a, list(resp.context["object_list"]))

        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("proposals:list"))
        self.assertNotIn(self.proposal_a, list(resp.context["object_list"]))

    def test_work_order_isolation(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("operations:work_order_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.wo_a, list(resp.context["object_list"]))

    def test_contract_isolation(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("contracts:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.contract_a, list(resp.context["object_list"]))

    def test_financial_entry_isolation(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("finance:entry_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.entry_a, list(resp.context["object_list"]))

    def test_chatbot_flow_isolation(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("chatbot:flow_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.flow_a, list(resp.context["object_list"]))

    def test_automation_log_isolation(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("automation:log_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.log_a, list(resp.context["object_list"]))

    # ---- Detail cross-tenant 404 ----

    def test_lead_detail_404_cross_tenant(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(
            reverse("crm:lead_detail", kwargs={"pk": self.lead_a.pk}),
        )
        self.assertEqual(resp.status_code, 404)

    def test_proposal_detail_404_cross_tenant(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(
            reverse("proposals:detail", kwargs={"pk": self.proposal_a.pk}),
        )
        self.assertEqual(resp.status_code, 404)

    # ---- Dashboard ----

    def test_dashboard_both_tenants_accessible(self):
        self.client.force_login(self.user_a)
        resp_a = self.client.get(reverse("dashboard:index"))
        self.assertEqual(resp_a.status_code, 200)

        self.client.force_login(self.user_b)
        resp_b = self.client.get(reverse("dashboard:index"))
        self.assertEqual(resp_b.status_code, 200)

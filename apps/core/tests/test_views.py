"""Testes de acesso a views — status codes e autenticação."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.automation.models import AutomationLog
from apps.chatbot.models import ChatbotFlow, ChatbotStep
from apps.contracts.models import Contract, ContractTemplate
from apps.crm.models import Lead, Opportunity
from apps.finance.models import BankAccount, FinancialCategory, FinancialEntry
from apps.operations.models import ServiceType, Team, WorkOrder
from apps.proposals.models import Proposal, ProposalTemplate

from .helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


class ViewAccessTests(TestCase):
    """Verifica que views autenticadas retornam 200 e não-autenticadas redirecionam."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("views@test.com", "View User", self.empresa)

        # Objects needed for detail/edit URLs
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="Lead View",
        )
        self.pipeline, self.stage, _, _ = create_pipeline_for_empresa(self.empresa)
        self.opportunity = Opportunity.objects.create(
            empresa=self.empresa, lead=self.lead, pipeline=self.pipeline,
            current_stage=self.stage, title="Opp View", value=Decimal("5000"),
        )
        self.proposal = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead, title="Prop View",
        )
        self.proposal_tpl = ProposalTemplate.objects.create(
            empresa=self.empresa, name="Tpl View",
        )
        self.contract = Contract.objects.create(
            empresa=self.empresa, lead=self.lead, title="Cont View",
            content="...", value=Decimal("1000"),
        )
        self.contract_tpl = ContractTemplate.objects.create(
            empresa=self.empresa, name="CT View", content="...",
        )
        self.service_type = ServiceType.objects.create(
            empresa=self.empresa, name="ST View",
        )
        self.work_order = WorkOrder.objects.create(
            empresa=self.empresa, lead=self.lead, title="OS View",
        )
        self.bank_account = BankAccount.objects.create(
            empresa=self.empresa, name="BA View", bank_name="Banco",
        )
        self.category = FinancialCategory.objects.create(
            empresa=self.empresa, name="Cat View",
            type=FinancialCategory.Type.INCOME,
        )
        self.entry = FinancialEntry.objects.create(
            empresa=self.empresa, type=FinancialEntry.Type.INCOME,
            description="Entry View", amount=Decimal("100"),
            date=timezone.now().date(),
        )
        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Flow View",
        )
        self.step = ChatbotStep.objects.create(
            flow=self.flow, order=0, question_text="Test?",
        )
        self.team = Team.objects.create(
            empresa=self.empresa, name="Team View",
        )

    # ---- Helper ----

    def _get_authenticated(self, url_name, kwargs=None):
        self.client.force_login(self.user)
        url = reverse(url_name, kwargs=kwargs)
        return self.client.get(url)

    # ---- GET list views (expect 200) ----

    def test_dashboard(self):
        resp = self._get_authenticated("dashboard:index")
        self.assertEqual(resp.status_code, 200)

    def test_lead_list(self):
        resp = self._get_authenticated("crm:lead_list")
        self.assertEqual(resp.status_code, 200)

    def test_pipeline_board(self):
        resp = self._get_authenticated("crm:pipeline_board")
        self.assertEqual(resp.status_code, 200)

    def test_proposal_list(self):
        resp = self._get_authenticated("proposals:list")
        self.assertEqual(resp.status_code, 200)

    def test_contract_list(self):
        resp = self._get_authenticated("contracts:list")
        self.assertEqual(resp.status_code, 200)

    def test_work_order_list(self):
        resp = self._get_authenticated("operations:work_order_list")
        self.assertEqual(resp.status_code, 200)

    def test_calendar(self):
        resp = self._get_authenticated("operations:calendar")
        self.assertEqual(resp.status_code, 200)

    def test_finance_overview(self):
        resp = self._get_authenticated("finance:finance_overview")
        self.assertEqual(resp.status_code, 200)

    def test_entry_list(self):
        resp = self._get_authenticated("finance:entry_list")
        self.assertEqual(resp.status_code, 200)

    def test_chatbot_flow_list(self):
        resp = self._get_authenticated("chatbot:flow_list")
        self.assertEqual(resp.status_code, 200)

    def test_automation_pipeline_demo(self):
        resp = self._get_authenticated("automation:pipeline_demo")
        self.assertEqual(resp.status_code, 200)

    def test_automation_log_list(self):
        resp = self._get_authenticated("automation:log_list")
        self.assertEqual(resp.status_code, 200)

    def test_settings_index(self):
        resp = self._get_authenticated("settings_app:index")
        self.assertEqual(resp.status_code, 200)

    def test_settings_service_types(self):
        resp = self._get_authenticated("settings_app:service_type_list")
        self.assertEqual(resp.status_code, 200)

    def test_settings_pipeline_stages(self):
        resp = self._get_authenticated("settings_app:pipeline_stages")
        self.assertEqual(resp.status_code, 200)

    def test_settings_proposal_templates(self):
        resp = self._get_authenticated("settings_app:proposal_templates")
        self.assertEqual(resp.status_code, 200)

    def test_settings_contract_templates(self):
        resp = self._get_authenticated("settings_app:contract_templates")
        self.assertEqual(resp.status_code, 200)

    def test_settings_category_list(self):
        resp = self._get_authenticated("settings_app:category_list")
        self.assertEqual(resp.status_code, 200)

    def test_settings_bank_account_list(self):
        resp = self._get_authenticated("settings_app:bank_account_list")
        self.assertEqual(resp.status_code, 200)

    def test_settings_team_list(self):
        resp = self._get_authenticated("settings_app:team_list")
        self.assertEqual(resp.status_code, 200)

    # ---- GET detail views (expect 200) ----

    def test_lead_detail(self):
        resp = self._get_authenticated("crm:lead_detail", {"pk": self.lead.pk})
        self.assertEqual(resp.status_code, 200)

    def test_opportunity_detail(self):
        resp = self._get_authenticated(
            "crm:opportunity_detail", {"pk": self.opportunity.pk},
        )
        self.assertEqual(resp.status_code, 200)

    def test_proposal_detail(self):
        resp = self._get_authenticated("proposals:detail", {"pk": self.proposal.pk})
        self.assertEqual(resp.status_code, 200)

    def test_contract_detail(self):
        resp = self._get_authenticated("contracts:detail", {"pk": self.contract.pk})
        self.assertEqual(resp.status_code, 200)

    def test_work_order_detail(self):
        resp = self._get_authenticated(
            "operations:work_order_detail", {"pk": self.work_order.pk},
        )
        self.assertEqual(resp.status_code, 200)

    def test_chatbot_flow_detail(self):
        resp = self._get_authenticated("chatbot:flow_detail", {"pk": self.flow.pk})
        self.assertEqual(resp.status_code, 200)

    # ---- GET form views (expect 200) ----

    def test_lead_create(self):
        resp = self._get_authenticated("crm:lead_create")
        self.assertEqual(resp.status_code, 200)

    def test_lead_update(self):
        resp = self._get_authenticated("crm:lead_update", {"pk": self.lead.pk})
        self.assertEqual(resp.status_code, 200)

    def test_proposal_create(self):
        resp = self._get_authenticated("proposals:create")
        self.assertEqual(resp.status_code, 200)

    def test_proposal_edit(self):
        resp = self._get_authenticated("proposals:edit", {"pk": self.proposal.pk})
        self.assertEqual(resp.status_code, 200)

    def test_contract_create(self):
        resp = self._get_authenticated("contracts:create")
        self.assertEqual(resp.status_code, 200)

    def test_contract_edit(self):
        resp = self._get_authenticated("contracts:edit", {"pk": self.contract.pk})
        self.assertEqual(resp.status_code, 200)

    def test_work_order_create(self):
        resp = self._get_authenticated("operations:work_order_create")
        self.assertEqual(resp.status_code, 200)

    def test_work_order_update(self):
        resp = self._get_authenticated(
            "operations:work_order_update", {"pk": self.work_order.pk},
        )
        self.assertEqual(resp.status_code, 200)

    def test_entry_create(self):
        resp = self._get_authenticated("finance:entry_create")
        self.assertEqual(resp.status_code, 200)

    def test_entry_update(self):
        resp = self._get_authenticated("finance:entry_update", {"pk": self.entry.pk})
        self.assertEqual(resp.status_code, 200)

    def test_chatbot_flow_create(self):
        resp = self._get_authenticated("chatbot:flow_create")
        self.assertEqual(resp.status_code, 200)

    def test_chatbot_flow_update(self):
        resp = self._get_authenticated("chatbot:flow_update", {"pk": self.flow.pk})
        self.assertEqual(resp.status_code, 200)

    def test_opportunity_create(self):
        resp = self._get_authenticated("crm:opportunity_create")
        self.assertEqual(resp.status_code, 200)

    # ---- Unauthenticated redirects ----

    def test_unauthenticated_redirects(self):
        urls = [
            reverse("dashboard:index"),
            reverse("crm:lead_list"),
            reverse("proposals:list"),
            reverse("contracts:list"),
            reverse("operations:work_order_list"),
            reverse("finance:finance_overview"),
            reverse("chatbot:flow_list"),
            reverse("automation:pipeline_demo"),
            reverse("automation:log_list"),
            reverse("settings_app:index"),
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(
                resp.status_code, 302,
                f"{url} should redirect unauthenticated user",
            )
            self.assertIn("/accounts/login/", resp.url)

    # ---- Webhook ----

    def test_webhook_valid_token(self):
        self.flow.is_active = True
        self.flow.save(update_fields=["is_active"])
        url = reverse(
            "chatbot:webhook_receive",
            kwargs={"token": str(self.flow.webhook_token)},
        )
        resp = self.client.post(
            url, data='{"sender_id":"+5500000000","message":"test"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_webhook_invalid_token(self):
        url = reverse(
            "chatbot:webhook_receive",
            kwargs={"token": "00000000-0000-0000-0000-000000000000"},
        )
        resp = self.client.post(
            url, data='{"message":"test"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_webhook_get_405(self):
        url = reverse(
            "chatbot:webhook_receive",
            kwargs={"token": str(self.flow.webhook_token)},
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 405)

    # ---- Healthcheck ----

    def test_healthcheck(self):
        resp = self.client.get("/healthz/")
        self.assertEqual(resp.status_code, 200)

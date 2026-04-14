"""Testes do pipeline de automação ponta a ponta."""

from decimal import Decimal

from django.test import TransactionTestCase
from django.utils import timezone

from apps.automation.models import AutomationLog
from apps.automation.services import (
    create_billing_from_work_order,
    create_contract_from_proposal,
    create_lead_from_chatbot,
    create_proposal_from_lead,
    create_work_order_from_contract,
    run_full_pipeline,
)
from apps.chatbot.models import ChatbotFlow
from apps.contracts.models import Contract, ContractTemplate
from apps.crm.models import Lead
from apps.finance.models import BankAccount, FinancialEntry
from apps.operations.models import ServiceType, WorkOrder
from apps.proposals.models import Proposal, ProposalTemplate, ProposalTemplateItem

from .helpers import create_test_empresa, create_test_user


class AutomationPipelineTests(TransactionTestCase):
    """Testes dos serviços de orquestração do pipeline."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("auto@test.com", "Auto User", self.empresa)

        self.flow = ChatbotFlow.objects.create(
            empresa=self.empresa,
            name="Fluxo Teste",
            channel=ChatbotFlow.Channel.WHATSAPP,
            is_active=True,
        )

        self.proposal_tpl = ProposalTemplate.objects.create(
            empresa=self.empresa, name="Template Padrão", is_default=True,
            introduction="Intro", terms="Termos",
        )
        ProposalTemplateItem.objects.create(
            template=self.proposal_tpl,
            description="Serviço A",
            quantity=Decimal("1.00"),
            unit_price=Decimal("2000.00"),
        )

        self.contract_tpl = ContractTemplate.objects.create(
            empresa=self.empresa, name="Contrato Padrão", is_default=True,
            content="Contrato com {cliente}, proposta {proposta}, valor {valor}.",
        )

        self.service_type = ServiceType.objects.create(
            empresa=self.empresa, name="Topografia",
        )

        self.bank_account = BankAccount.objects.create(
            empresa=self.empresa, name="Conta", bank_name="Banco X",
            pix_key="12345", is_default=True,
        )

        self.session_data = {
            "session_id": "test-session-001",
            "name": "Cliente Teste",
            "email": "cliente@teste.com",
            "phone": "(11) 91234-5678",
            "company": "Empresa Cliente",
        }

    # ---- Step 1: Chatbot → Lead ----

    def test_create_lead_from_chatbot(self):
        lead = create_lead_from_chatbot(self.empresa, self.flow, self.session_data)
        self.assertEqual(lead.name, "Cliente Teste")
        self.assertEqual(lead.source, "whatsapp")
        self.assertEqual(lead.external_ref, "test-session-001")
        self.assertEqual(lead.status, Lead.Status.NOVO)

    def test_create_lead_idempotent(self):
        lead1 = create_lead_from_chatbot(self.empresa, self.flow, self.session_data)
        lead2 = create_lead_from_chatbot(self.empresa, self.flow, self.session_data)
        self.assertEqual(lead1.pk, lead2.pk)
        self.assertEqual(Lead.objects.filter(empresa=self.empresa).count(), 1)

    # ---- Step 2: Lead → Proposta ----

    def test_create_proposal_from_lead(self):
        lead = create_lead_from_chatbot(self.empresa, self.flow, self.session_data)
        proposal = create_proposal_from_lead(self.empresa, lead)
        self.assertEqual(proposal.status, Proposal.Status.DRAFT)
        self.assertTrue(proposal.number.startswith("PROP-"))
        self.assertEqual(proposal.items.count(), 1)
        self.assertEqual(proposal.total, Decimal("2000.00"))

    def test_create_proposal_idempotent(self):
        lead = create_lead_from_chatbot(self.empresa, self.flow, self.session_data)
        p1 = create_proposal_from_lead(self.empresa, lead)
        p2 = create_proposal_from_lead(self.empresa, lead)
        self.assertEqual(p1.pk, p2.pk)

    # ---- Step 3: Proposta → Contrato ----

    def test_create_contract_from_proposal(self):
        lead = create_lead_from_chatbot(self.empresa, self.flow, self.session_data)
        proposal = create_proposal_from_lead(self.empresa, lead)
        proposal.status = "accepted"
        proposal.save(update_fields=["status"])

        contract = create_contract_from_proposal(self.empresa, proposal)
        self.assertEqual(contract.status, Contract.Status.DRAFT)
        self.assertEqual(contract.value, proposal.total)
        self.assertIn("Cliente Teste", contract.content)

    # ---- Step 4: Contrato → OS ----

    def test_create_work_order_from_contract(self):
        lead = create_lead_from_chatbot(self.empresa, self.flow, self.session_data)
        proposal = create_proposal_from_lead(self.empresa, lead)
        contract = create_contract_from_proposal(self.empresa, proposal)
        contract.status = "signed"
        contract.save(update_fields=["status"])

        wo = create_work_order_from_contract(self.empresa, contract)
        self.assertEqual(wo.status, WorkOrder.Status.PENDING)
        self.assertIsNotNone(wo.scheduled_date)

    # ---- Step 5: OS → Financeiro ----

    def test_create_billing_from_work_order(self):
        lead = create_lead_from_chatbot(self.empresa, self.flow, self.session_data)
        proposal = create_proposal_from_lead(self.empresa, lead)
        contract = create_contract_from_proposal(self.empresa, proposal)
        wo = create_work_order_from_contract(self.empresa, contract)
        wo.status = "completed"
        wo.save(update_fields=["status"])

        entries = create_billing_from_work_order(self.empresa, wo)
        self.assertTrue(len(entries) >= 1)
        self.assertTrue(all(e.auto_generated for e in entries))

    def test_create_billing_idempotent(self):
        lead = create_lead_from_chatbot(self.empresa, self.flow, self.session_data)
        proposal = create_proposal_from_lead(self.empresa, lead)
        contract = create_contract_from_proposal(self.empresa, proposal)
        wo = create_work_order_from_contract(self.empresa, contract)
        wo.status = "completed"
        wo.save(update_fields=["status"])

        entries1 = create_billing_from_work_order(self.empresa, wo)
        entries2 = create_billing_from_work_order(self.empresa, wo)
        self.assertEqual(
            [e.pk for e in entries1],
            [e.pk for e in entries2],
        )

    # ---- Full pipeline ----

    def test_run_full_pipeline(self):
        result = run_full_pipeline(self.empresa, self.flow, self.session_data)
        self.assertIn("lead", result)
        self.assertIn("proposal", result)
        self.assertIn("contract", result)
        self.assertIn("work_order", result)
        self.assertIn("entries", result)
        self.assertEqual(result["errors"], [])

        self.assertEqual(result["proposal"].status, "accepted")
        self.assertEqual(result["contract"].status, "signed")
        self.assertEqual(result["work_order"].status, "completed")

    def test_automation_logs_created(self):
        run_full_pipeline(self.empresa, self.flow, self.session_data)
        logs = AutomationLog.objects.filter(empresa=self.empresa)
        actions = set(logs.values_list("action", flat=True))
        self.assertIn("chatbot_to_lead", actions)
        self.assertIn("lead_to_proposal", actions)
        self.assertIn("proposal_to_contract", actions)
        self.assertIn("contract_to_work_order", actions)
        self.assertIn("work_order_to_billing", actions)
        self.assertIn("full_pipeline", actions)

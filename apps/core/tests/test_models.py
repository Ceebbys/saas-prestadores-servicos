"""Testes de criação de todos os models do sistema."""

import uuid
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Empresa, Membership
from apps.automation.models import AutomationLog
from apps.chatbot.models import ChatbotAction, ChatbotChoice, ChatbotFlow, ChatbotStep
from apps.contracts.models import Contract, ContractTemplate
from apps.crm.models import Lead, Opportunity, Pipeline, PipelineStage
from apps.finance.models import BankAccount, FinancialCategory, FinancialEntry
from apps.operations.models import ServiceType, Team, TeamMember, WorkOrder
from apps.proposals.models import (
    Proposal,
    ProposalItem,
    ProposalTemplate,
    ProposalTemplateItem,
)

from .helpers import create_pipeline_for_empresa, create_test_empresa, create_test_user


class ModelCreationTests(TestCase):
    """Testes básicos de criação de modelos."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("test@test.com", "Test User", self.empresa)

    # ---- CRM ----

    def test_create_lead(self):
        lead = Lead.objects.create(
            empresa=self.empresa,
            name="João Silva",
            email="joao@teste.com",
            phone="(11) 99999-1234",
            source=Lead.Source.WHATSAPP,
            status=Lead.Status.NOVO,
        )
        self.assertEqual(str(lead), "João Silva")
        self.assertEqual(lead.empresa, self.empresa)
        self.assertIsNotNone(lead.created_at)

    def test_create_pipeline_and_stages(self):
        pipeline, s1, s2, s3 = create_pipeline_for_empresa(self.empresa)
        self.assertEqual(str(pipeline), "Pipeline Principal")
        self.assertEqual(pipeline.stages.count(), 3)
        self.assertTrue(s3.is_won)
        self.assertFalse(s1.is_won)

    def test_create_opportunity(self):
        pipeline, stage, _, _ = create_pipeline_for_empresa(self.empresa)
        lead = Lead.objects.create(empresa=self.empresa, name="Lead Op")
        opp = Opportunity.objects.create(
            empresa=self.empresa,
            lead=lead,
            pipeline=pipeline,
            current_stage=stage,
            title="Oportunidade Teste",
            value=Decimal("10000.00"),
            probability=75,
        )
        self.assertEqual(str(opp), "Oportunidade Teste")
        self.assertEqual(opp.value, Decimal("10000.00"))

    # ---- Proposals ----

    def test_create_proposal(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Lead Prop")
        proposal = Proposal.objects.create(
            empresa=self.empresa,
            lead=lead,
            title="Proposta Topografia",
            status=Proposal.Status.DRAFT,
        )
        self.assertTrue(proposal.number.startswith("PROP-"))
        self.assertIn(str(timezone.now().year), proposal.number)

    def test_create_proposal_item(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Lead Item")
        proposal = Proposal.objects.create(
            empresa=self.empresa, lead=lead, title="Prop Item",
        )
        item = ProposalItem.objects.create(
            proposal=proposal,
            description="Levantamento topográfico",
            quantity=Decimal("2.00"),
            unit_price=Decimal("1500.00"),
        )
        self.assertEqual(item.total, Decimal("3000.00"))

    def test_create_proposal_template(self):
        tpl1 = ProposalTemplate.objects.create(
            empresa=self.empresa, name="Template A", is_default=True,
        )
        tpl2 = ProposalTemplate.objects.create(
            empresa=self.empresa, name="Template B", is_default=True,
        )
        tpl1.refresh_from_db()
        self.assertFalse(tpl1.is_default)
        self.assertTrue(tpl2.is_default)

    def test_create_proposal_template_item(self):
        tpl = ProposalTemplate.objects.create(
            empresa=self.empresa, name="Tpl Item",
        )
        tpl_item = ProposalTemplateItem.objects.create(
            template=tpl,
            description="Serviço padrão",
            quantity=Decimal("1.00"),
            unit_price=Decimal("2000.00"),
        )
        self.assertEqual(str(tpl_item), "Serviço padrão")

    # ---- Contracts ----

    def test_create_contract(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Lead Contrato")
        contract = Contract.objects.create(
            empresa=self.empresa,
            lead=lead,
            title="Contrato Manutenção",
            content="Conteúdo do contrato...",
            value=Decimal("5000.00"),
            status=Contract.Status.DRAFT,
        )
        self.assertTrue(contract.number.startswith("CONT-"))
        self.assertEqual(str(contract), f"{contract.number} - Contrato Manutenção")

    def test_create_contract_template(self):
        tpl1 = ContractTemplate.objects.create(
            empresa=self.empresa, name="CT A", content="...", is_default=True,
        )
        tpl2 = ContractTemplate.objects.create(
            empresa=self.empresa, name="CT B", content="...", is_default=True,
        )
        tpl1.refresh_from_db()
        self.assertFalse(tpl1.is_default)
        self.assertTrue(tpl2.is_default)

    # ---- Operations ----

    def test_create_service_type(self):
        st = ServiceType.objects.create(
            empresa=self.empresa,
            name="Topografia Básica",
            estimated_duration_hours=Decimal("8.0"),
        )
        self.assertEqual(str(st), "Topografia Básica")
        self.assertTrue(st.is_active)

    def test_create_work_order(self):
        lead = Lead.objects.create(empresa=self.empresa, name="Lead OS")
        wo = WorkOrder.objects.create(
            empresa=self.empresa,
            lead=lead,
            title="OS Campo",
            status=WorkOrder.Status.PENDING,
        )
        self.assertTrue(wo.number.startswith("OS-"))

    def test_create_team_and_member(self):
        team = Team.objects.create(
            empresa=self.empresa, name="Equipe Campo", leader=self.user,
        )
        tm = TeamMember.objects.create(
            team=team, user=self.user, role=TeamMember.Role.LEADER, is_active=True,
        )
        self.assertEqual(team.member_count, 1)
        self.assertEqual(str(tm), f"{self.user.full_name} ({team.name})")

    # ---- Finance ----

    def test_create_bank_account(self):
        ba = BankAccount.objects.create(
            empresa=self.empresa,
            name="Conta Principal",
            bank_name="Banco do Brasil",
            bank_code="001",
            pix_key="12345678000199",
            is_default=True,
        )
        self.assertEqual(str(ba), "Conta Principal (Banco do Brasil)")

    def test_create_financial_category(self):
        cat = FinancialCategory.objects.create(
            empresa=self.empresa,
            name="Serviços Prestados",
            type=FinancialCategory.Type.INCOME,
        )
        self.assertIn("Receita", str(cat))

    def test_create_financial_entry(self):
        entry = FinancialEntry.objects.create(
            empresa=self.empresa,
            type=FinancialEntry.Type.INCOME,
            description="Pagamento OS-001",
            amount=Decimal("3500.00"),
            date=timezone.now().date(),
            status=FinancialEntry.Status.PENDING,
        )
        self.assertIn("R$", str(entry))

    # ---- Chatbot ----

    def test_create_chatbot_flow(self):
        flow = ChatbotFlow.objects.create(
            empresa=self.empresa,
            name="Fluxo WhatsApp",
            channel=ChatbotFlow.Channel.WHATSAPP,
            is_active=True,
        )
        self.assertIsInstance(flow.webhook_token, uuid.UUID)
        self.assertEqual(str(flow), "Fluxo WhatsApp")

    def test_create_chatbot_step_and_choice(self):
        flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Fluxo Steps",
        )
        step = ChatbotStep.objects.create(
            flow=flow,
            order=0,
            question_text="Qual seu nome?",
            step_type=ChatbotStep.StepType.NAME,
            lead_field_mapping=ChatbotStep.LeadFieldMapping.NAME,
        )
        choice = ChatbotChoice.objects.create(
            step=step, text="Opção A", order=0,
        )
        self.assertIn("Passo 0", str(step))
        self.assertEqual(str(choice), "Opção A")

    def test_create_chatbot_action(self):
        flow = ChatbotFlow.objects.create(
            empresa=self.empresa, name="Fluxo Action",
        )
        action = ChatbotAction.objects.create(
            flow=flow,
            trigger=ChatbotAction.Trigger.ON_COMPLETE,
            action_type=ChatbotAction.ActionType.CREATE_LEAD,
        )
        self.assertIn("→", str(action))

    # ---- Automation ----

    def test_create_automation_log(self):
        log = AutomationLog.objects.create(
            empresa=self.empresa,
            action=AutomationLog.Action.CHATBOT_TO_LEAD,
            entity_type=AutomationLog.EntityType.LEAD,
            entity_id=1,
            status=AutomationLog.Status.SUCCESS,
            metadata={"test": True},
        )
        self.assertIn("Chatbot", str(log))
        self.assertEqual(log.status, "success")

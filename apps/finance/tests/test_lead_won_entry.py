"""RV06 — Geração automática de FinancialEntry quando Lead vai para WON.

Cenário do cliente: 'tem trampo q c pode fechar sem proposta e sem
contrato'. Quando o Lead é movido para uma stage com is_won=True,
gera entry pendente no financeiro automaticamente.
"""
from decimal import Decimal

from django.test import TestCase

from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.finance.models import FinancialEntry
from apps.finance.services import generate_entry_from_lead_won
from apps.core.tests.helpers import create_test_empresa


def _pipeline_with_stages(empresa):
    p = Pipeline.objects.create(empresa=empresa, name="Vendas")
    s_novo = PipelineStage.objects.create(pipeline=p, name="Novo", order=0)
    s_ganho = PipelineStage.objects.create(
        pipeline=p, name="Ganho", order=10, is_won=True,
    )
    s_perdido = PipelineStage.objects.create(
        pipeline=p, name="Perdido", order=20, is_lost=True,
    )
    return p, s_novo, s_ganho, s_perdido


class GenerateEntryFromLeadWonHelperTests(TestCase):
    """Helper isolado — testa idempotência, valor, casos limite."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-lead-won")
        _, self.s_novo, self.s_ganho, _ = _pipeline_with_stages(self.empresa)

    def test_creates_entry_with_estimated_value(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente A",
            estimated_value=Decimal("2500.00"),
            pipeline_stage=self.s_novo,
        )
        # Limpa entries já criadas pelo signal (caso lead criado em novo,
        # não won, não cria. Mas garantia)
        FinancialEntry.objects.filter(related_lead=lead).delete()

        entry = generate_entry_from_lead_won(lead)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.amount, Decimal("2500.00"))
        self.assertEqual(entry.status, FinancialEntry.Status.PENDING)
        self.assertEqual(entry.type, FinancialEntry.Type.INCOME)
        self.assertEqual(entry.related_lead_id, lead.pk)
        self.assertTrue(entry.auto_generated)

    def test_idempotent_returns_existing(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente B",
            estimated_value=Decimal("1000.00"),
        )
        FinancialEntry.objects.filter(related_lead=lead).delete()

        first = generate_entry_from_lead_won(lead)
        second = generate_entry_from_lead_won(lead)
        third = generate_entry_from_lead_won(lead)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.pk, third.pk)
        self.assertEqual(
            FinancialEntry.objects.filter(related_lead=lead).count(), 1,
        )

    def test_falls_back_to_servico_default_price(self):
        from apps.operations.models import ServiceType
        svc = ServiceType.objects.create(
            empresa=self.empresa, name="Topografia",
            default_price=Decimal("5500.00"), default_prazo_dias=14,
        )
        lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente C",
            servico=svc,  # estimated_value vazio
        )
        FinancialEntry.objects.filter(related_lead=lead).delete()

        entry = generate_entry_from_lead_won(lead)
        self.assertEqual(entry.amount, Decimal("5500.00"))

    def test_zero_value_still_creates_entry_with_warning(self):
        """Lead sem estimated_value nem servico → entry com valor 0
        + nota de warning para o user editar."""
        lead = Lead.objects.create(empresa=self.empresa, name="Cliente D")
        FinancialEntry.objects.filter(related_lead=lead).delete()

        entry = generate_entry_from_lead_won(lead)
        self.assertEqual(entry.amount, Decimal("0.00"))
        self.assertIn("Valor não definido", entry.notes)

    def test_does_not_duplicate_when_proposal_already_generated_entries(self):
        """Se há Proposta com entries auto-geradas, NÃO cria entry adicional."""
        from apps.proposals.models import Proposal
        lead = Lead.objects.create(
            empresa=self.empresa, name="Cliente E",
            estimated_value=Decimal("3000.00"),
        )
        FinancialEntry.objects.filter(related_lead=lead).delete()

        prop = Proposal.objects.create(
            empresa=self.empresa, lead=lead,
            title="Proposta", total=Decimal("3000.00"),
        )
        # Simula entry auto-gerada pela proposta
        FinancialEntry.objects.create(
            empresa=self.empresa,
            type=FinancialEntry.Type.INCOME,
            description="Da proposta",
            amount=Decimal("3000.00"),
            date="2026-01-01",
            related_proposal=prop,
            auto_generated=True,
        )

        result = generate_entry_from_lead_won(lead)
        self.assertIsNone(result)
        # Nenhuma entry related_lead criada
        self.assertFalse(
            FinancialEntry.objects.filter(related_lead=lead).exists()
        )


class SignalTriggersOnStageChangeTests(TestCase):
    """E2E via signal: mover Lead para stage is_won dispara o helper."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv06-signal-won")
        _, self.s_novo, self.s_ganho, self.s_perdido = _pipeline_with_stages(self.empresa)

    def test_move_to_won_stage_creates_entry(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="João",
            estimated_value=Decimal("1500.00"),
            pipeline_stage=self.s_novo,
        )
        # Ainda em "Novo" — sem entry
        self.assertFalse(
            FinancialEntry.objects.filter(related_lead=lead).exists()
        )

        # Move para "Ganho"
        lead.pipeline_stage = self.s_ganho
        lead.save()

        # Entry criada
        entries = FinancialEntry.objects.filter(related_lead=lead)
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().amount, Decimal("1500.00"))

    def test_move_to_lost_stage_does_NOT_create_entry(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="Maria",
            estimated_value=Decimal("1500.00"),
            pipeline_stage=self.s_novo,
        )
        lead.pipeline_stage = self.s_perdido
        lead.save()
        self.assertFalse(
            FinancialEntry.objects.filter(related_lead=lead).exists()
        )

    def test_save_again_in_won_stage_no_duplicates(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="José",
            estimated_value=Decimal("500.00"),
            pipeline_stage=self.s_ganho,
        )
        # Salva 3x mais
        for _ in range(3):
            lead.save()
        self.assertEqual(
            FinancialEntry.objects.filter(related_lead=lead).count(), 1,
        )

    def test_created_in_won_stage_creates_entry(self):
        lead = Lead.objects.create(
            empresa=self.empresa, name="Direto Won",
            estimated_value=Decimal("800.00"),
            pipeline_stage=self.s_ganho,  # já criado em won
        )
        self.assertEqual(
            FinancialEntry.objects.filter(related_lead=lead).count(), 1,
        )

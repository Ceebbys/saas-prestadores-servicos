"""RV07 — Item 1.1.

Dois comportamentos:
1. Lançamento automático de lead ganho deve puxar o valor digitado na
   Pipeline (Opportunity.value) quando o Lead não tem estimated_value
   próprio — antes nascia com R$ 0,00.
2. Parcelamento de um lançamento JÁ existente na edição (split), dando aos
   lançamentos automáticos a mesma opção dos manuais.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.core.tests.helpers import create_test_empresa
from apps.crm.models import Lead, Opportunity, Pipeline, PipelineStage
from apps.finance.models import FinancialEntry
from apps.finance.services import (
    generate_entry_from_lead_won,
    split_entry_into_installments,
)


def _pipeline_with_stages(empresa):
    p = Pipeline.objects.create(empresa=empresa, name="Vendas", is_default=True)
    s_novo = PipelineStage.objects.create(pipeline=p, name="Novo", order=0)
    s_ganho = PipelineStage.objects.create(
        pipeline=p, name="Ganho", order=10, is_won=True,
    )
    return p, s_novo, s_ganho


class LeadWonValueFromOpportunityTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-value")
        self.p, self.s_novo, self.s_ganho = _pipeline_with_stages(self.empresa)

    def test_helper_falls_back_to_opportunity_value(self):
        """generate_entry_from_lead_won usa Opportunity.value quando o lead
        não tem estimated_value."""
        lead = Lead.objects.create(
            empresa=self.empresa, name="Sem valor próprio",
            pipeline_stage=self.s_novo,
        )
        # O signal auto-criou uma Opportunity (value=0). Setamos o valor da
        # pipeline via .update() para NÃO disparar o sync (testar o fallback
        # isolado no helper).
        Opportunity.objects.filter(lead=lead).update(value=Decimal("4200.00"))
        FinancialEntry.objects.filter(related_lead=lead).delete()
        self.assertIsNone(lead.estimated_value)

        entry = generate_entry_from_lead_won(lead)
        self.assertEqual(entry.amount, Decimal("4200.00"))

    def test_opportunity_save_syncs_value_to_lead(self):
        """Salvar uma Opportunity com valor propaga para Lead.estimated_value
        quando o lead ainda não tem valor próprio."""
        lead = Lead.objects.create(
            empresa=self.empresa, name="Valor na pipeline",
            pipeline_stage=self.s_novo,
        )
        opp = lead.opportunities.first()
        self.assertIsNotNone(opp)
        opp.value = Decimal("3100.00")
        opp.save()

        lead.refresh_from_db()
        self.assertEqual(lead.estimated_value, Decimal("3100.00"))

    def test_sync_does_not_overwrite_lead_own_value(self):
        """Lead com valor próprio NÃO é sobrescrito pelo valor da oportunidade."""
        lead = Lead.objects.create(
            empresa=self.empresa, name="Valor próprio",
            estimated_value=Decimal("9000.00"),
            pipeline_stage=self.s_novo,
        )
        opp = lead.opportunities.first()
        opp.value = Decimal("100.00")
        opp.save()

        lead.refresh_from_db()
        self.assertEqual(lead.estimated_value, Decimal("9000.00"))

    def test_opportunity_string_value_does_not_crash(self):
        """Pente fino: Opportunity salva com value string ('1500') não derruba
        o post_save (coerção defensiva str→Decimal antes de comparar)."""
        lead = Lead.objects.create(
            empresa=self.empresa, name="Str value", pipeline_stage=self.s_novo,
        )
        opp = lead.opportunities.first()
        opp.value = "1500.00"  # string, não Decimal
        opp.save()  # NÃO deve levantar TypeError
        lead.refresh_from_db()
        self.assertEqual(lead.estimated_value, Decimal("1500.00"))

    def test_move_opportunity_to_won_generates_entry_with_value(self):
        """Mover a oportunidade para etapa de ganho gera a entry com o valor
        correto (board de oportunidades usa .update() no lead, que não dispara
        o post_save do Lead)."""
        lead = Lead.objects.create(
            empresa=self.empresa, name="Movido pela oportunidade",
            pipeline_stage=self.s_novo,
        )
        opp = lead.opportunities.first()
        opp.value = Decimal("2750.00")
        opp.current_stage = self.s_ganho
        opp.save()

        entries = FinancialEntry.objects.filter(related_lead=lead)
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().amount, Decimal("2750.00"))


class SplitEntryIntoInstallmentsTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-split")

    def _entry(self, **kw):
        defaults = dict(
            empresa=self.empresa,
            type=FinancialEntry.Type.INCOME,
            description="Lead - Projeto X",
            amount=Decimal("900.00"),
            date=date(2026, 6, 1),
            status=FinancialEntry.Status.PENDING,
            auto_generated=True,
        )
        defaults.update(kw)
        return FinancialEntry.objects.create(**defaults)

    def test_split_creates_n_installments_summing_total(self):
        entry = self._entry(amount=Decimal("1000.00"))
        result = split_entry_into_installments(entry, count=3, interval_days=30)

        self.assertEqual(len(result), 3)
        total = sum((e.amount for e in result), Decimal("0.00"))
        self.assertEqual(total, Decimal("1000.00"))
        # Primeira parcela reaproveita a entry original (mesmo PK)
        self.assertEqual(result[0].pk, entry.pk)
        # Sufixos (i/N)
        self.assertTrue(result[0].description.endswith("(1/3)"))
        self.assertTrue(result[2].description.endswith("(3/3)"))
        # Última recebe o restante (arredondamento) — soma exata garantida acima
        self.assertEqual(result[0].amount, Decimal("333.33"))
        self.assertEqual(result[2].amount, Decimal("333.34"))

    def test_split_preserves_lead_link_and_auto_flag_on_first(self):
        from apps.crm.models import Lead
        lead = Lead.objects.create(empresa=self.empresa, name="Dono")
        entry = self._entry(related_lead=lead, auto_generated=True)
        result = split_entry_into_installments(entry, count=2, interval_days=30)

        # Vínculo com o lead preservado em todas as parcelas (continuam contando
        # no breakdown "de leads ganhos")
        for e in result:
            self.assertEqual(e.related_lead_id, lead.pk)
        # 1/N mantém auto_generated (âncora de idempotência); demais não
        self.assertTrue(result[0].auto_generated)
        self.assertFalse(result[1].auto_generated)

    def test_split_skips_paid_entry(self):
        entry = self._entry(status=FinancialEntry.Status.PAID)
        result = split_entry_into_installments(entry, count=3)
        self.assertEqual(result, [entry])
        self.assertEqual(
            FinancialEntry.objects.filter(empresa=self.empresa).count(), 1,
        )

    def test_split_count_one_is_noop(self):
        entry = self._entry()
        result = split_entry_into_installments(entry, count=1)
        self.assertEqual(result, [entry])

    def test_split_overdue_siblings_are_pending(self):
        """Pente fino: a 1ª parcela mantém o status (vencimento original); as
        seguintes têm vencimento futuro → sempre PENDENTES, nunca 'overdue'."""
        entry = self._entry(status=FinancialEntry.Status.OVERDUE)
        result = split_entry_into_installments(entry, count=3, interval_days=30)
        self.assertEqual(result[0].status, FinancialEntry.Status.OVERDUE)
        self.assertEqual(result[1].status, FinancialEntry.Status.PENDING)
        self.assertEqual(result[2].status, FinancialEntry.Status.PENDING)

    def test_resplit_strips_previous_suffix(self):
        """Pente fino: re-parcelar uma parcela não empilha '(1/3) (1/2)'."""
        entry = self._entry(description="Lead - X", amount=Decimal("900.00"))
        first = split_entry_into_installments(entry, count=3)
        original_amount = first[0].amount  # 300.00, antes de re-parcelar
        again = split_entry_into_installments(first[0], count=2)
        self.assertTrue(again[0].description.endswith("(1/2)"))
        self.assertNotIn("(1/3)", again[0].description)
        # soma das 2 sub-parcelas preserva o valor da parcela re-dividida
        total = sum((e.amount for e in again), Decimal("0.00"))
        self.assertEqual(total, original_amount)

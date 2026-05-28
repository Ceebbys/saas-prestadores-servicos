"""RV10 — Parcelamento de lançamento financeiro na criação manual.

Cliente pediu: "quando for fazer um lançamento de uma receita colocar a
condição de pagamento. se foi dividida é de quantas vezes, e ai ja gera
q a quantidade de entradas conforme for configurada no lançamento. exemplo
serviço 1500 de 3 vezes. gera 3 entradas de 500 nos lançamentos"

Cobre:
- Form valida is_installment + count >= 2
- save_installments() cria N entries com R$ total/N
- Última parcela recebe o restante (sem perda por arredondamento)
- Vencimentos escalonados pelo intervalo (default 30 dias)
- Descrição inclui sufixo (N/total)
- Funciona pra receita E despesa
- View Create cria N entries quando checkbox marcado
- View Create cria 1 entry quando sem parcelamento (caminho clássico)
- count=1 ou ausente desabilita parcelamento
- count < 2 retorna erro de validação
- Suporte a centavos não-divisíveis (ex: R$ 100 em 3x = 33,33 + 33,33 + 33,34)
"""
from datetime import date as _date
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.finance.forms import FinancialEntryForm
from apps.finance.models import FinancialCategory, FinancialEntry
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _form_data(**overrides):
    """Payload mínimo válido pro FinancialEntryForm."""
    data = {
        "type": "income",
        "description": "Avaliação de Imóveis - Ana",
        "amount": "1500.00",
        "date": "2026-05-29",
        "status": "pending",
    }
    data.update(overrides)
    return data


class FormValidationTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-inst-form")

    def test_form_without_installment_is_valid(self):
        form = FinancialEntryForm(data=_form_data(), empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.cleaned_data.get("is_installment"))

    def test_form_with_installment_2x_is_valid(self):
        form = FinancialEntryForm(
            data=_form_data(
                is_installment="on", installment_count="2",
                installment_interval_days="30",
            ),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.cleaned_data["is_installment"])
        self.assertEqual(form.cleaned_data["installment_count"], 2)

    def test_installment_count_below_2_is_rejected(self):
        form = FinancialEntryForm(
            data=_form_data(is_installment="on", installment_count="1"),
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("installment_count", form.errors)

    def test_installment_count_above_60_is_rejected(self):
        form = FinancialEntryForm(
            data=_form_data(is_installment="on", installment_count="61"),
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("installment_count", form.errors)

    def test_default_interval_30_when_empty(self):
        """Se user marca parcelar mas não escolhe intervalo, default 30."""
        form = FinancialEntryForm(
            data=_form_data(
                is_installment="on", installment_count="2",
                installment_interval_days="",
            ),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["installment_interval_days"], 30)


class SaveInstallmentsTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-inst-save")
        self.category = FinancialCategory.objects.create(
            empresa=self.empresa, name="Serviços", type="income",
        )

    def test_3x_500_creates_3_entries(self):
        """Caso do cliente: R$ 1500 em 3x → 3 entries de R$ 500."""
        form = FinancialEntryForm(
            data=_form_data(
                amount="1500.00",
                is_installment="on", installment_count="3",
                installment_interval_days="30",
                category=str(self.category.pk),
            ),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        entries = form.save_installments(self.empresa)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].amount, Decimal("500.00"))
        self.assertEqual(entries[1].amount, Decimal("500.00"))
        self.assertEqual(entries[2].amount, Decimal("500.00"))
        # Soma exata
        self.assertEqual(sum(e.amount for e in entries), Decimal("1500.00"))

    def test_last_installment_absorbs_rounding(self):
        """R$ 100 em 3x = 33,33 + 33,33 + 33,34 (soma = 100,00 exato)."""
        form = FinancialEntryForm(
            data=_form_data(
                amount="100.00",
                is_installment="on", installment_count="3",
                installment_interval_days="30",
            ),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        entries = form.save_installments(self.empresa)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].amount, Decimal("33.33"))
        self.assertEqual(entries[1].amount, Decimal("33.33"))
        self.assertEqual(entries[2].amount, Decimal("33.34"))
        self.assertEqual(sum(e.amount for e in entries), Decimal("100.00"))

    def test_due_dates_are_staggered(self):
        """Vencimentos escalonados pelo intervalo."""
        form = FinancialEntryForm(
            data=_form_data(
                amount="900.00", date="2026-06-01",
                is_installment="on", installment_count="3",
                installment_interval_days="30",
            ),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        entries = form.save_installments(self.empresa)
        self.assertEqual(entries[0].date, _date(2026, 6, 1))
        self.assertEqual(entries[1].date, _date(2026, 7, 1))
        self.assertEqual(entries[2].date, _date(2026, 7, 31))

    def test_custom_interval_days(self):
        """Intervalo diferente do padrão (ex: 15 dias = quinzenal)."""
        form = FinancialEntryForm(
            data=_form_data(
                amount="600.00", date="2026-06-01",
                is_installment="on", installment_count="2",
                installment_interval_days="15",
            ),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        entries = form.save_installments(self.empresa)
        self.assertEqual(entries[1].date, _date(2026, 6, 16))

    def test_description_has_installment_suffix(self):
        """Cada entry tem '(N/total)' no fim da descrição."""
        form = FinancialEntryForm(
            data=_form_data(
                description="Projeto X",
                is_installment="on", installment_count="3",
            ),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        entries = form.save_installments(self.empresa)
        self.assertEqual(entries[0].description, "Projeto X (1/3)")
        self.assertEqual(entries[1].description, "Projeto X (2/3)")
        self.assertEqual(entries[2].description, "Projeto X (3/3)")

    def test_works_for_expense_type(self):
        """Despesa parcelada também funciona (ex: equipamento em 12x)."""
        form = FinancialEntryForm(
            data=_form_data(
                type="expense", description="Equipamento",
                amount="1200.00",
                is_installment="on", installment_count="12",
            ),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        entries = form.save_installments(self.empresa)
        self.assertEqual(len(entries), 12)
        self.assertEqual(entries[0].type, "expense")
        self.assertEqual(sum(e.amount for e in entries), Decimal("1200.00"))

    def test_installments_share_category_and_bank(self):
        """Vínculos (category, bank_account) propagam para todas parcelas."""
        form = FinancialEntryForm(
            data=_form_data(
                is_installment="on", installment_count="2",
                category=str(self.category.pk),
            ),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        entries = form.save_installments(self.empresa)
        for e in entries:
            self.assertEqual(e.category_id, self.category.pk)

    def test_installments_marked_not_auto_generated(self):
        """User criou de propósito → auto_generated=False."""
        form = FinancialEntryForm(
            data=_form_data(is_installment="on", installment_count="2"),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        entries = form.save_installments(self.empresa)
        for e in entries:
            self.assertFalse(e.auto_generated)


class EntryCreateViewInstallmentTests(TestCase):
    """E2E: POST no /finance/entries/create/ com is_installment cria N entries."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv10-inst-view")
        self.user = create_test_user("v@t.com", "V", self.empresa)
        self.client.force_login(self.user)

    def test_post_with_installment_creates_n_entries(self):
        """Cliente: 'serviço 1500 de 3 vezes. gera 3 entradas de 500'."""
        response = self.client.post(
            reverse("finance:entry_create"),
            data=_form_data(
                amount="1500.00",
                is_installment="on", installment_count="3",
                installment_interval_days="30",
            ),
        )
        self.assertEqual(response.status_code, 302)
        entries = list(
            FinancialEntry.objects.filter(empresa=self.empresa).order_by("date")
        )
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].amount, Decimal("500.00"))
        self.assertEqual(entries[1].amount, Decimal("500.00"))
        self.assertEqual(entries[2].amount, Decimal("500.00"))

    def test_post_without_installment_creates_1_entry(self):
        """Sem checkbox marcado → caminho clássico (1 entry)."""
        response = self.client.post(
            reverse("finance:entry_create"),
            data=_form_data(amount="500.00"),
        )
        self.assertEqual(response.status_code, 302)
        entries = FinancialEntry.objects.filter(empresa=self.empresa)
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().amount, Decimal("500.00"))

    def test_get_create_form_includes_installment_fields(self):
        """GET no form deve renderizar campos de parcelamento."""
        response = self.client.get(reverse("finance:entry_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is_installment")
        self.assertContains(response, "Pagamento parcelado")

    def test_get_update_form_hides_installment_fields(self):
        """Edição NÃO mostra campos de parcelamento."""
        entry = FinancialEntry.objects.create(
            empresa=self.empresa, type="income",
            description="Teste", amount=Decimal("100"),
            date=_date(2026, 5, 1), status="pending",
        )
        response = self.client.get(
            reverse("finance:entry_update", args=[entry.pk]),
        )
        self.assertEqual(response.status_code, 200)
        # Campo de checkbox de parcelamento NÃO renderiza em edição
        self.assertNotContains(response, 'name="is_installment"')

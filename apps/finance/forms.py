from django import forms

from apps.core.forms import TailwindFormMixin
from apps.proposals.models import Proposal

from .models import BankAccount, FinancialCategory, FinancialEntry


class BankAccountForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = [
            "name",
            "bank_name",
            "bank_code",
            "agency",
            "account_number",
            "account_type",
            "person_type",
            "holder_name",
            "holder_document",
            "pix_key",
            "is_default",
            "is_active",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class FinancialEntryForm(TailwindFormMixin, forms.ModelForm):
    # RV10 — Cliente pediu: "quando for fazer um lançamento de uma receita
    # colocar a condição de pagamento. se foi dividida é de quantas vezes,
    # e ai ja gera q a quantidade de entradas conforme for configurada no
    # lançamento. exemplo serviço 1500 de 3 vezes. gera 3 entradas de 500
    # nos lançamentos"
    #
    # Campos extras não-model que controlam o parcelamento. Na criação geram
    # N entries (save_installments). Na edição de um lançamento pendente,
    # dividem o registro existente em N parcelas (split_entry_into_installments,
    # RV07 — dá aos lançamentos automáticos a mesma opção dos manuais).
    is_installment = forms.BooleanField(
        label="Pagamento parcelado?",
        required=False,
        help_text=(
            "Marque para dividir o valor em várias entradas. "
            "Exemplo: R$ 1.500 em 3x gera 3 lançamentos de R$ 500."
        ),
    )
    installment_count = forms.IntegerField(
        label="Quantidade de parcelas",
        required=False,
        min_value=2,
        max_value=60,
        initial=2,
        help_text="Entre 2 e 60 parcelas.",
    )
    installment_interval_days = forms.IntegerField(
        label="Intervalo entre parcelas (dias)",
        required=False,
        min_value=1,
        max_value=365,
        initial=30,
        help_text="Dias entre cada vencimento. Padrão: 30 (mensal).",
    )

    class Meta:
        model = FinancialEntry
        fields = [
            "type",
            "description",
            "amount",
            "category",
            "date",
            "paid_date",
            "status",
            "bank_account",
            "related_proposal",
            "related_contract",
            "related_work_order",
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
            "paid_date": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields["category"].queryset = FinancialCategory.objects.filter(
                empresa=empresa, is_active=True
            )
            self.fields["bank_account"].queryset = BankAccount.objects.filter(
                empresa=empresa, is_active=True
            )
            self.fields["related_proposal"].queryset = Proposal.objects.filter(
                empresa=empresa
            )
            # Contract FK
            try:
                from apps.contracts.models import Contract

                self.fields["related_contract"].queryset = Contract.objects.filter(
                    empresa=empresa
                )
            except (ImportError, LookupError):
                pass
            # WorkOrder FK
            from apps.operations.models import WorkOrder

            self.fields["related_work_order"].queryset = WorkOrder.objects.filter(
                empresa=empresa
            )

    def clean(self):
        cleaned = super().clean()
        is_installment = cleaned.get("is_installment", False)
        if is_installment:
            count = cleaned.get("installment_count") or 0
            if count < 2:
                self.add_error(
                    "installment_count",
                    "Para parcelar, escolha pelo menos 2 parcelas.",
                )
            # Default seguro para o intervalo se vazio
            if not cleaned.get("installment_interval_days"):
                cleaned["installment_interval_days"] = 30
        return cleaned

    def save_installments(self, empresa):
        """RV10 — Cria N entries parceladas (substitui o save() padrão quando
        is_installment=True).

        Estratégia:
        - Cada parcela = total / N (Decimal, 2 casas)
        - Última parcela recebe o restante (evita perda por arredondamento)
        - Vencimentos: date + i * interval_days
        - Descrição: "{descrição original} (1/N)", "(2/N)", etc.
        - Retorna lista de FinancialEntry criadas

        IMPORTANTE: roda dentro de `transaction.atomic` — se qualquer parcela
        falhar (constraint, signal exception, deadlock), o lote inteiro faz
        rollback. Sem isso, podiam ficar parcelas órfãs como "3 de 10 criadas"
        — inconsistência grave em módulo financeiro.

        Não toca em `auto_generated` (essas são MANUAIS — user criou de propósito).
        """
        from datetime import timedelta
        from decimal import Decimal
        from django.db import transaction
        cleaned = self.cleaned_data
        total = Decimal(str(cleaned["amount"]))
        count = int(cleaned["installment_count"])
        interval = int(cleaned.get("installment_interval_days") or 30)
        base_date = cleaned["date"]
        base_description = cleaned["description"]

        per_installment = (total / count).quantize(Decimal("0.01"))
        entries: list[FinancialEntry] = []
        accumulated = Decimal("0.00")
        with transaction.atomic():
            for i in range(count):
                is_last = i == count - 1
                amount = (total - accumulated) if is_last else per_installment
                accumulated += amount
                due_date = base_date + timedelta(days=interval * i)
                # Pente fino: apenas a 1ª parcela pode herdar o status escolhido
                # (ex.: Pago). As demais são PENDENTES — senão um lançamento
                # parcelado marcado como Pago contaria TODAS as parcelas (futuras
                # inclusive) como já recebidas, inflando a receita.
                if i == 0:
                    parcela_status = cleaned.get("status") or FinancialEntry.Status.PENDING
                    parcela_paid_date = cleaned.get("paid_date")
                else:
                    parcela_status = FinancialEntry.Status.PENDING
                    parcela_paid_date = None
                entry = FinancialEntry(
                    empresa=empresa,
                    type=cleaned["type"],
                    description=f"{base_description} ({i + 1}/{count})",
                    amount=amount,
                    category=cleaned.get("category"),
                    date=due_date,
                    paid_date=parcela_paid_date,
                    status=parcela_status,
                    bank_account=cleaned.get("bank_account"),
                    related_proposal=cleaned.get("related_proposal"),
                    related_contract=cleaned.get("related_contract"),
                    related_work_order=cleaned.get("related_work_order"),
                    notes=cleaned.get("notes", ""),
                    auto_generated=False,
                )
                entry.save()
                entries.append(entry)
        return entries


class FinancialCategoryForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = FinancialCategory
        fields = ["name", "type"]

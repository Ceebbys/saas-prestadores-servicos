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


class FinancialCategoryForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = FinancialCategory
        fields = ["name", "type"]

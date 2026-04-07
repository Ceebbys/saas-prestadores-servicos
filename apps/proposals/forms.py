from django import forms

from apps.core.forms import TailwindFormMixin
from apps.proposals.models import (
    Proposal,
    ProposalItem,
    ProposalTemplate,
    ProposalTemplateItem,
)


class ProposalForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Proposal
        fields = [
            "title",
            "lead",
            "opportunity",
            "template",
            "introduction",
            "terms",
            "discount_percent",
            "valid_until",
            "payment_method",
            "is_installment",
            "installment_count",
        ]
        widgets = {
            "valid_until": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields["lead"].queryset = self.fields["lead"].queryset.filter(
                empresa=empresa
            )
            self.fields["opportunity"].queryset = self.fields[
                "opportunity"
            ].queryset.filter(empresa=empresa)
            self.fields["template"].queryset = self.fields[
                "template"
            ].queryset.filter(empresa=empresa)


class ProposalItemForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ProposalItem
        fields = [
            "description",
            "details",
            "quantity",
            "unit",
            "unit_price",
        ]


class ProposalTemplateForm(TailwindFormMixin, forms.ModelForm):
    default_payment_method = forms.ChoiceField(
        label="Forma de pagamento padrão",
        required=False,
        choices=[("", "---------")] + list(Proposal.PaymentMethod.choices),
    )

    class Meta:
        model = ProposalTemplate
        fields = [
            "name",
            "is_default",
            "introduction",
            "terms",
            "default_payment_method",
            "default_is_installment",
            "default_installment_count",
        ]
        widgets = {
            "introduction": forms.Textarea(attrs={"rows": 4}),
            "terms": forms.Textarea(attrs={"rows": 5}),
        }


class ProposalTemplateItemForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ProposalTemplateItem
        fields = [
            "description",
            "details",
            "quantity",
            "unit",
            "unit_price",
        ]

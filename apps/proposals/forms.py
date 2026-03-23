from django import forms

from apps.core.forms import TailwindFormMixin
from apps.proposals.models import Proposal, ProposalItem


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

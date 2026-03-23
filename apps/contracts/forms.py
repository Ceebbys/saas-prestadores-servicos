from django import forms

from apps.core.forms import TailwindFormMixin
from apps.contracts.models import Contract


class ContractForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Contract
        fields = [
            "title",
            "lead",
            "proposal",
            "template",
            "content",
            "value",
            "start_date",
            "end_date",
            "notes",
        ]
        widgets = {
            "start_date": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
            "end_date": forms.DateInput(
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
            self.fields["proposal"].queryset = self.fields[
                "proposal"
            ].queryset.filter(empresa=empresa)
            self.fields["template"].queryset = self.fields[
                "template"
            ].queryset.filter(empresa=empresa)

from django import forms

from apps.core.forms import TailwindFormMixin
from apps.crm.models import PipelineStage
from apps.proposals.models import ProposalTemplate
from apps.contracts.models import ContractTemplate


class PipelineStageForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = PipelineStage
        fields = ["pipeline", "name", "order", "color", "is_won", "is_lost"]
        widgets = {
            "color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            from apps.crm.models import Pipeline

            self.fields["pipeline"].queryset = Pipeline.objects.filter(
                empresa=empresa
            )


class ProposalTemplateForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ProposalTemplate
        fields = ["name", "content", "header_content", "footer_content", "is_default"]
        widgets = {
            "content": forms.Textarea(attrs={"rows": 8}),
            "header_content": forms.Textarea(attrs={"rows": 4}),
            "footer_content": forms.Textarea(attrs={"rows": 4}),
        }


class ContractTemplateForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ContractTemplate
        fields = ["name", "content", "is_default"]
        widgets = {
            "content": forms.Textarea(attrs={"rows": 10}),
        }

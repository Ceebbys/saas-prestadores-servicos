from django import forms

from apps.automation.models import PipelineAutomationRule
from apps.core.forms import TailwindFormMixin
from apps.crm.models import PipelineStage
from apps.proposals.models import Proposal, ProposalTemplate
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
            "content",
            "header_content",
            "footer_content",
            "default_payment_method",
            "default_is_installment",
            "default_installment_count",
        ]
        widgets = {
            "introduction": forms.Textarea(attrs={"rows": 4}),
            "terms": forms.Textarea(attrs={"rows": 5}),
            "content": forms.Textarea(attrs={"rows": 6}),
            "header_content": forms.Textarea(attrs={"rows": 3}),
            "footer_content": forms.Textarea(attrs={"rows": 3}),
        }


class ContractTemplateForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ContractTemplate
        fields = ["name", "content", "is_default"]
        widgets = {
            "content": forms.Textarea(attrs={"rows": 10}),
        }


class PipelineAutomationRuleForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = PipelineAutomationRule
        fields = [
            "name", "event",
            "target_pipeline", "target_stage",
            "is_active", "priority", "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.crm.models import Pipeline, PipelineStage

        if empresa:
            self.fields["target_pipeline"].queryset = Pipeline.objects.filter(
                empresa=empresa,
            )
            self.fields["target_stage"].queryset = PipelineStage.objects.filter(
                pipeline__empresa=empresa,
            ).select_related("pipeline")
            # Render legível: "Pipeline X — Etapa Y"
            self.fields["target_stage"].label_from_instance = (
                lambda s: f"{s.pipeline.name} — {s.name}"
            )

    def clean(self):
        cleaned = super().clean()
        stage = cleaned.get("target_stage")
        pipeline = cleaned.get("target_pipeline")
        if stage and pipeline and stage.pipeline_id != pipeline.pk:
            self.add_error(
                "target_stage",
                "A etapa selecionada não pertence ao pipeline escolhido.",
            )
        return cleaned

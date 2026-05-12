from django import forms

from apps.accounts.models import EmpresaEmailConfig
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
            # RV05-F — paridade total com Proposal (header + footer image)
            "header_image",
            "header_content",
            "footer_image",
            "footer_content",
            "default_payment_method",
            "default_is_installment",
            "default_installment_count",
        ]
        widgets = {
            "introduction": forms.Textarea(attrs={"rows": 4, "data-rich-text": "true"}),
            "terms": forms.Textarea(attrs={"rows": 5, "data-rich-text": "true"}),
            "content": forms.Textarea(attrs={"rows": 6}),
            "header_content": forms.Textarea(attrs={"rows": 3, "data-rich-text": "true"}),
            "footer_content": forms.Textarea(attrs={"rows": 3, "data-rich-text": "true"}),
        }

    # RV05-F — Validação e sanitização via core (mesmo padrão de ContractTemplateForm)
    def clean_header_image(self):
        from apps.core.document_render.image_validation import validate_document_image
        return validate_document_image(self.cleaned_data.get("header_image"))

    def clean_footer_image(self):
        from apps.core.document_render.image_validation import validate_document_image
        return validate_document_image(self.cleaned_data.get("footer_image"))

    def _sanitize(self, field):
        from apps.core.document_render.sanitizer import sanitize_rich_html
        return sanitize_rich_html(self.cleaned_data.get(field, "") or "")

    def clean_introduction(self):
        return self._sanitize("introduction")

    def clean_terms(self):
        return self._sanitize("terms")

    def clean_header_content(self):
        return self._sanitize("header_content")

    def clean_footer_content(self):
        return self._sanitize("footer_content")


class ContractTemplateForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ContractTemplate
        fields = ["name", "content", "is_default"]
        widgets = {
            "content": forms.Textarea(attrs={"rows": 10}),
        }


class EmpresaEmailConfigForm(TailwindFormMixin, forms.ModelForm):
    """Form de SMTP por tenant. Senha é write-only (nunca exibe a atual)."""

    password = forms.CharField(
        label="Senha SMTP",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Deixe em branco para manter a senha atual.",
    )

    class Meta:
        model = EmpresaEmailConfig
        fields = [
            "host", "port", "username", "use_tls", "use_ssl",
            "timeout_seconds", "from_email", "from_name", "is_active",
        ]
        widgets = {
            "host": forms.TextInput(attrs={"placeholder": "smtp.gmail.com"}),
            "port": forms.NumberInput(attrs={"placeholder": "587"}),
            "username": forms.TextInput(attrs={"placeholder": "exemplo@suaempresa.com.br"}),
            "from_email": forms.EmailInput(attrs={"placeholder": "exemplo@suaempresa.com.br"}),
            "from_name": forms.TextInput(attrs={"placeholder": "Sua Empresa"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        new_password = self.cleaned_data.get("password") or ""
        if new_password:
            instance.set_password(new_password)
        if commit:
            instance.save()
        return instance


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

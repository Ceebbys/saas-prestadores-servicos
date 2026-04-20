from django import forms

from apps.accounts.models import Membership
from apps.core.forms import TailwindFormMixin

from .models import Lead, LeadContact, Opportunity, Pipeline, PipelineStage


class LeadForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Lead
        exclude = ["empresa", "created_at", "updated_at", "external_ref"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "cpf": forms.TextInput(attrs={"placeholder": "000.000.000-00"}),
            "cnpj": forms.TextInput(attrs={"placeholder": "00.000.000/0000-00"}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            user_ids = Membership.objects.filter(
                empresa=empresa, is_active=True
            ).values_list("user_id", flat=True)
            self.fields["assigned_to"].queryset = (
                self.fields["assigned_to"]
                .queryset.filter(id__in=user_ids)
            )
            pipeline = Pipeline.objects.filter(
                empresa=empresa, is_default=True
            ).first()
            if pipeline is None:
                pipeline = Pipeline.objects.filter(empresa=empresa).first()
            if pipeline is not None:
                self.fields["pipeline_stage"].queryset = (
                    pipeline.stages.order_by("order")
                )
                self.fields["pipeline_stage"].empty_label = None
                if not self.instance.pk and not self.initial.get("pipeline_stage"):
                    first_stage = pipeline.stages.order_by("order").first()
                    if first_stage:
                        self.initial["pipeline_stage"] = first_stage.pk
            else:
                self.fields["pipeline_stage"].queryset = PipelineStage.objects.none()


class LeadContactForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = LeadContact
        fields = ["channel", "note", "contacted_at"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2}),
            "contacted_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }


class OpportunityForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Opportunity
        exclude = ["empresa", "won_at", "lost_at", "lost_reason"]
        widgets = {
            "expected_close_date": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields["lead"].queryset = Lead.objects.filter(empresa=empresa)
            self.fields["pipeline"].queryset = Pipeline.objects.filter(
                empresa=empresa
            )
            self.fields["current_stage"].queryset = PipelineStage.objects.filter(
                pipeline__empresa=empresa
            )
            user_ids = Membership.objects.filter(
                empresa=empresa, is_active=True
            ).values_list("user_id", flat=True)
            self.fields["assigned_to"].queryset = (
                self.fields["assigned_to"]
                .queryset.filter(id__in=user_ids)
            )

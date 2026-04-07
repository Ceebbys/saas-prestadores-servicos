from django import forms

from apps.accounts.models import Membership
from apps.core.forms import TailwindFormMixin

from .models import Lead, Opportunity, Pipeline, PipelineStage


class LeadForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Lead
        exclude = ["empresa", "created_at", "updated_at", "external_ref"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
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

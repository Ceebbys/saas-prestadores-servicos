from django import forms

from apps.accounts.models import Membership
from apps.core.forms import TailwindFormMixin
from apps.crm.models import Lead
from apps.proposals.models import Proposal

from .models import ServiceType, WorkOrder


class WorkOrderForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = [
            "title",
            "lead",
            "proposal",
            "contract",
            "service_type",
            "priority",
            "description",
            "scheduled_date",
            "scheduled_time",
            "assigned_to",
            "location",
            "notes",
        ]
        widgets = {
            "scheduled_date": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
            "scheduled_time": forms.TimeInput(
                attrs={"type": "time"},
                format="%H:%M",
            ),
            "description": forms.Textarea(attrs={"rows": 3}),
            "location": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields["lead"].queryset = Lead.objects.filter(empresa=empresa)
            self.fields["proposal"].queryset = Proposal.objects.filter(
                empresa=empresa
            )
            self.fields["service_type"].queryset = ServiceType.objects.filter(
                empresa=empresa, is_active=True
            )
            user_ids = Membership.objects.filter(
                empresa=empresa, is_active=True
            ).values_list("user_id", flat=True)
            self.fields["assigned_to"].queryset = (
                self.fields["assigned_to"].queryset.filter(id__in=user_ids)
            )
            # Contract FK — imported lazily to avoid circular imports
            try:
                from apps.contracts.models import Contract

                self.fields["contract"].queryset = Contract.objects.filter(
                    empresa=empresa
                )
            except (ImportError, LookupError):
                pass


class ServiceTypeForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ServiceType
        fields = ["name", "description", "estimated_duration_hours", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

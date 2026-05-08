import json

from django import forms

from apps.accounts.models import Membership
from apps.core.forms import TailwindFormMixin
from apps.crm.models import Lead
from apps.proposals.models import Proposal

from .models import ServiceType, Team, TeamMember, WorkOrder


class WorkOrderForm(TailwindFormMixin, forms.ModelForm):
    cloud_storage_links_json = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )

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
            "assigned_team",
            "location",
            "google_maps_url",  # hint: auto-gerado se vazio
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
        # Pre-populate cloud_storage_links_json from instance
        if self.instance and self.instance.pk and self.instance.cloud_storage_links:
            self.initial["cloud_storage_links_json"] = json.dumps(
                self.instance.cloud_storage_links
            )
        self.fields["google_maps_url"].help_text = (
            "Deixe em branco para gerar automaticamente a partir do endereço."
        )
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
            self.fields["assigned_team"].queryset = Team.objects.filter(
                empresa=empresa, is_active=True
            )
            # Contract FK — imported lazily to avoid circular imports
            try:
                from apps.contracts.models import Contract

                self.fields["contract"].queryset = Contract.objects.filter(
                    empresa=empresa
                )
            except (ImportError, LookupError):
                pass

    def clean_cloud_storage_links_json(self):
        raw = self.cleaned_data.get("cloud_storage_links_json", "")
        if not raw:
            return []
        try:
            links = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise forms.ValidationError("Formato inválido para links.")
        if not isinstance(links, list):
            raise forms.ValidationError("Links devem ser uma lista.")
        cleaned = []
        for item in links:
            url = (item.get("url") or "").strip() if isinstance(item, dict) else ""
            if url:
                label = (item.get("label") or "").strip()
                cleaned.append({"url": url, "label": label})
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.cloud_storage_links = self.cleaned_data.get(
            "cloud_storage_links_json", []
        )
        if commit:
            instance.save()
        return instance


class TeamForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "description", "leader", "color", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "color": forms.Select(
                choices=[
                    ("indigo", "Indigo"),
                    ("violet", "Violeta"),
                    ("emerald", "Verde"),
                    ("amber", "Amarelo"),
                    ("rose", "Vermelho"),
                    ("sky", "Azul"),
                    ("slate", "Cinza"),
                    ("orange", "Laranja"),
                    ("teal", "Teal"),
                ],
            ),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            user_ids = Membership.objects.filter(
                empresa=empresa, is_active=True
            ).values_list("user_id", flat=True)
            self.fields["leader"].queryset = (
                self.fields["leader"].queryset.filter(id__in=user_ids)
            )
            self.fields["leader"].required = False


class ServiceTypeForm(TailwindFormMixin, forms.ModelForm):
    """Form completo de Serviço Pré-Fixado.

    Sanitiza `default_description` (rich) via apps.proposals.sanitizer.
    """

    class Meta:
        model = ServiceType
        fields = [
            "name", "code", "category",
            "description",
            "default_description",
            "default_price", "default_prazo_dias",
            "estimated_duration_hours",
            "default_proposal_template", "default_contract_template",
            "default_pipeline", "default_stage",
            "tags", "internal_notes",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "default_description": forms.Textarea(attrs={"rows": 5, "data-rich-text": "true"}),
            "internal_notes": forms.Textarea(attrs={"rows": 2}),
            "tags": forms.TextInput(attrs={"placeholder": "topografia, regularização"}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            from apps.contracts.models import ContractTemplate
            from apps.crm.models import Pipeline, PipelineStage
            from apps.proposals.models import ProposalTemplate

            self.fields["default_proposal_template"].queryset = (
                ProposalTemplate.objects.filter(empresa=empresa)
            )
            self.fields["default_contract_template"].queryset = (
                ContractTemplate.objects.filter(empresa=empresa)
            )
            self.fields["default_pipeline"].queryset = (
                Pipeline.objects.filter(empresa=empresa)
            )
            self.fields["default_stage"].queryset = (
                PipelineStage.objects.filter(pipeline__empresa=empresa)
                .select_related("pipeline")
            )
            self.fields["default_stage"].label_from_instance = (
                lambda s: f"{s.pipeline.name} — {s.name}"
            )
            for f in [
                "default_proposal_template", "default_contract_template",
                "default_pipeline", "default_stage",
            ]:
                self.fields[f].required = False
                self.fields[f].empty_label = "—"

    def clean_default_description(self):
        from apps.proposals.sanitizer import sanitize_proposal_html
        return sanitize_proposal_html(
            self.cleaned_data.get("default_description") or ""
        )

    def clean(self):
        cleaned = super().clean()
        stage = cleaned.get("default_stage")
        pipeline = cleaned.get("default_pipeline")
        if stage and pipeline and stage.pipeline_id != pipeline.pk:
            self.add_error(
                "default_stage",
                "A etapa precisa pertencer ao pipeline selecionado.",
            )
        return cleaned

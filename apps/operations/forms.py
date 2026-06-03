import json

from django import forms

from apps.accounts.models import Membership
from apps.core.forms import TailwindFormMixin
from apps.crm.models import Lead
from apps.proposals.models import Proposal

from .models import (
    ServiceType,
    Team,
    TeamMember,
    WorkOrder,
    WorkOrderChecklist,
    WorkOrderTimeLog,
)


class WorkOrderForm(TailwindFormMixin, forms.ModelForm):
    cloud_storage_links_json = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )
    # RV09 — Checklist editável inline (cliente reportou: detail mostra
    # 'Nenhum item no checklist' mas form não tinha como adicionar).
    # JSON serializado no hidden field; Alpine.js no template controla o CRUD.
    # Formato: [{"id": opcional, "description": str, "is_completed": bool}]
    checklist_json = forms.CharField(
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
            "expected_end_date",  # RV10 — previsão de término
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
            "expected_end_date": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
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
        # RV09 — Pre-popula checklist_json com itens existentes para o Alpine
        # renderizar no form de edição. `order` mantém a sequência mostrada.
        if self.instance and self.instance.pk:
            existing_items = list(
                self.instance.checklist_items
                .order_by("order", "id")
                .values("id", "description", "is_completed")
            )
            if existing_items:
                self.initial["checklist_json"] = json.dumps(existing_items)
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

    def clean(self):
        """RV10 — Auto-calcula `expected_end_date` quando vazia, a partir de
        `scheduled_date + service_type.default_prazo_dias`.

        Cliente pediu: "A previsão se for de serviço cadastrado puxa de lá
        mas pode ficar editavel para o cara ajustar". User pode sobrescrever
        no form — só preenchemos se vazio.

        Pente fino: também valida que end_date >= scheduled_date pra evitar
        que a OS suma do calendário silenciosamente (loop while não roda
        quando end < start).
        """
        from datetime import timedelta
        cleaned = super().clean()
        end_date = cleaned.get("expected_end_date")
        scheduled = cleaned.get("scheduled_date")
        service_type = cleaned.get("service_type")
        if not end_date and scheduled and service_type:
            prazo = getattr(service_type, "default_prazo_dias", None) or 0
            if prazo > 0:
                cleaned["expected_end_date"] = scheduled + timedelta(days=int(prazo))
                end_date = cleaned["expected_end_date"]
        # Validação de coerência (depois do auto-calc)
        if end_date and scheduled and end_date < scheduled:
            self.add_error(
                "expected_end_date",
                "A previsão de término não pode ser anterior à data agendada.",
            )
        return cleaned

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

    def clean_checklist_json(self):
        """RV09 — Valida estrutura do JSON do checklist editado no form."""
        raw = self.cleaned_data.get("checklist_json", "")
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise forms.ValidationError("Formato inválido para o checklist.")
        if not isinstance(items, list):
            raise forms.ValidationError("Checklist deve ser uma lista.")
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            desc = (item.get("description") or "").strip()
            if not desc:
                # Item sem descrição é ignorado silenciosamente (input vazio)
                continue
            entry = {
                "description": desc[:500],
                "is_completed": bool(item.get("is_completed", False)),
            }
            # Preserva ID quando vier do form (item já existente que está
            # sendo editado/mantido). ID inválido é ignorado.
            raw_id = item.get("id")
            if raw_id not in (None, "", 0):
                try:
                    entry["id"] = int(raw_id)
                except (TypeError, ValueError):
                    pass
            cleaned.append(entry)
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.cloud_storage_links = self.cleaned_data.get(
            "cloud_storage_links_json", []
        )
        if commit:
            instance.save()
            # RV09 — Sincroniza checklist DEPOIS do save (precisa de instance.pk)
            self._sync_checklist(instance)
        return instance

    def _sync_checklist(self, instance):
        """RV09 — Reconcilia WorkOrderChecklist com o JSON enviado.

        Estratégia:
        - Items com `id` válido e presente no JSON → atualiza description + order
        - Items com `id` que NÃO estão no JSON → deleta
        - Items sem `id` → cria
        - `is_completed` só é tocado se o form enviar explicitamente; já que a
          toggle do detail é HTMX direto, mantemos o estado atual ao editar.
        """
        items = self.cleaned_data.get("checklist_json", [])
        # IDs que o user manteve no form
        kept_ids = {it["id"] for it in items if "id" in it}
        # Deleta os que foram removidos no form
        instance.checklist_items.exclude(id__in=kept_ids).delete()
        # Reconcilia o resto
        existing = {
            obj.id: obj
            for obj in instance.checklist_items.filter(id__in=kept_ids)
        }
        for idx, it in enumerate(items):
            obj_id = it.get("id")
            if obj_id and obj_id in existing:
                obj = existing[obj_id]
                changed = False
                if obj.description != it["description"]:
                    obj.description = it["description"]
                    changed = True
                if obj.order != idx:
                    obj.order = idx
                    changed = True
                if changed:
                    obj.save(update_fields=["description", "order", "updated_at"])
            else:
                WorkOrderChecklist.objects.create(
                    work_order=instance,
                    description=it["description"],
                    is_completed=it.get("is_completed", False),
                    order=idx,
                )


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
        # RV05-H — usa o core diretamente; antes importava via shim
        # `apps.proposals.sanitizer` (que será deprecated em RV06).
        from apps.core.document_render.sanitizer import sanitize_rich_html
        return sanitize_rich_html(
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


class WorkOrderTimeLogForm(TailwindFormMixin, forms.ModelForm):
    """RV07 (3.1) — Lançamento manual de horas: início + fim OU duração."""

    duration_minutes = forms.IntegerField(
        label="Duração (minutos)", required=False, min_value=1,
        help_text="Preencha início e fim OU a duração em minutos.",
    )

    class Meta:
        model = WorkOrderTimeLog
        fields = ["started_at", "ended_at", "is_billable", "notes"]
        widgets = {
            "started_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M",
            ),
            "ended_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M",
            ),
            "notes": forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # datetime-local envia "2026-06-01T14:30" — garante o parse.
        for field_name in ("started_at", "ended_at"):
            self.fields[field_name].input_formats = [
                "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
            ]

    def clean(self):
        from datetime import timedelta

        cleaned = super().clean()
        start = cleaned.get("started_at")
        end = cleaned.get("ended_at")
        mins = cleaned.get("duration_minutes")
        if not start:
            self.add_error("started_at", "Informe o início.")
            return cleaned
        if end and end < start:
            self.add_error("ended_at", "O fim não pode ser anterior ao início.")
        if not end and not mins:
            raise forms.ValidationError("Informe o fim OU a duração em minutos.")
        if not end and mins:
            cleaned["ended_at"] = start + timedelta(minutes=mins)
            self.instance.ended_at = cleaned["ended_at"]
        return cleaned

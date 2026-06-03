import json

from django import forms

from apps.accounts.models import Membership
from apps.contacts.models import Contato
from apps.contacts.services import (
    find_contato_by_document,
    get_or_create_contato_by_document,
    resolve_contato_from_mode,
)
from apps.core.forms import TailwindFormMixin
from apps.core.validators import (
    normalize_document,
    validate_cpf_or_cnpj,
)

from .models import (
    Lead,
    LeadChecklist,
    LeadContact,
    Opportunity,
    Pipeline,
    PipelineStage,
)


class LeadForm(TailwindFormMixin, forms.ModelForm):
    """Form de criação/edição de Lead com modo dual (search/new contato)."""

    CONTACT_MODE_CHOICES = (
        ("search", "Buscar contato existente"),
        ("new", "Criar novo contato"),
    )

    contact_mode = forms.ChoiceField(
        choices=CONTACT_MODE_CHOICES,
        widget=forms.RadioSelect,
        initial="search",
        required=False,
        label="Contato",
    )
    contato = forms.ModelChoiceField(
        queryset=Contato.objects.none(),
        required=False,
        widget=forms.HiddenInput,
        label="Contato selecionado",
    )
    new_contato_name = forms.CharField(
        max_length=255, required=False, label="Nome do Contato",
        widget=forms.TextInput(attrs={"placeholder": "ex.: João Silva"}),
    )
    new_contato_document = forms.CharField(
        max_length=18, required=False, label="CPF/CNPJ do Contato",
        validators=[validate_cpf_or_cnpj],
        widget=forms.TextInput(attrs={"placeholder": "000.000.000-00 ou 00.000.000/0000-00"}),
    )
    new_contato_phone = forms.CharField(
        max_length=20, required=False, label="Telefone/WhatsApp",
        widget=forms.TextInput(attrs={"placeholder": "(00) 00000-0000"}),
    )
    new_contato_email = forms.EmailField(
        required=False, label="E-mail do Contato",
    )
    # RV07 (4.1) — Checklist do Lead (pós-venda/execução). Mesmo padrão do
    # checklist da OS: JSON serializado + Alpine.js controla o CRUD no template.
    checklist_json = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Lead
        # Não inclui campos legados (cpf/cnpj/email/phone/company) — vêm do Contato
        fields = [
            "name", "source", "pipeline_stage", "assigned_to",
            "estimated_value",  # RV06 — para fechamento sem proposta
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "name": forms.TextInput(attrs={
                "placeholder": "ex.: Regularização Lote Bairro X",
            }),
            "estimated_value": forms.NumberInput(attrs={
                "step": "0.01", "min": "0",
                "placeholder": "ex.: 2500.00",
            }),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._empresa = empresa
        # RV07 — Pré-popula o checklist_json com itens existentes (edição).
        if self.instance and self.instance.pk:
            existing_items = list(
                self.instance.checklist_items
                .order_by("order", "id")
                .values("id", "description", "is_completed")
            )
            if existing_items:
                self.initial["checklist_json"] = json.dumps(existing_items)
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

            # Restrict contato queryset to this empresa.
            self.fields["contato"].queryset = Contato.objects.filter(
                empresa=empresa, is_active=True
            )
            # Pré-preenche se URL passou ?contato=ID
            if self.instance and self.instance.contato_id:
                self.initial["contato"] = self.instance.contato_id
                self.initial["contact_mode"] = "search"

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("contact_mode") or "search"
        contato = cleaned.get("contato")
        new_name = (cleaned.get("new_contato_name") or "").strip()
        new_doc = (cleaned.get("new_contato_document") or "").strip()

        if self.instance and self.instance.pk and contato is None and not new_name:
            # Permite edição de Lead que ainda não tem contato vinculado
            return cleaned

        if mode == "search":
            if not contato:
                self.add_error(
                    "contato",
                    "Selecione um contato existente ou alterne para 'Criar novo contato'.",
                )
        else:  # new
            if not new_name:
                self.add_error("new_contato_name", "Informe o nome do contato.")
            # Document is optional for new contact, but if provided check duplicates
            if new_doc and self._empresa:
                existing = find_contato_by_document(self._empresa, new_doc)
                if existing:
                    self.add_error(
                        "new_contato_document",
                        f"Já existe um contato com este documento: {existing.name}. "
                        f"Alterne para 'Buscar contato existente' e selecione-o.",
                    )
        return cleaned

    def clean_checklist_json(self):
        """RV07 — Valida a estrutura do JSON do checklist do Lead."""
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
                continue  # item sem descrição é ignorado
            entry = {
                "description": desc[:500],
                "is_completed": bool(item.get("is_completed", False)),
            }
            raw_id = item.get("id")
            if raw_id not in (None, "", 0):
                try:
                    entry["id"] = int(raw_id)
                except (TypeError, ValueError):
                    pass
            cleaned.append(entry)
        return cleaned

    def save(self, commit=True):
        """Cria/vincula Contato conforme contact_mode antes de salvar o Lead e
        reconcilia o checklist."""
        mode = self.cleaned_data.get("contact_mode") or "search"
        contato = self.cleaned_data.get("contato")

        lead = super().save(commit=False)
        if self._empresa:
            lead.empresa = self._empresa
            if mode == "new":
                # RV07 — helper compartilhado (mesma regra da OpportunityForm)
                contato = resolve_contato_from_mode(
                    self._empresa,
                    mode="new",
                    new_name=self.cleaned_data.get("new_contato_name") or "",
                    new_document=self.cleaned_data.get("new_contato_document") or "",
                    new_phone=self.cleaned_data.get("new_contato_phone") or "",
                    new_email=self.cleaned_data.get("new_contato_email") or "",
                    source=self.cleaned_data.get("source") or "",
                )
            if contato:
                lead.contato = contato

        if commit:
            lead.save()
            self.save_m2m()
            self._sync_checklist(lead)
        return lead

    def _sync_checklist(self, lead):
        """RV07 — Reconcilia LeadChecklist com o JSON enviado (mesma estratégia
        do checklist da OS): mantém IDs presentes, deleta removidos, cria novos.
        ``is_completed`` é preservado para itens existentes (a marcação é feita
        via toggle HTMX na página do lead)."""
        items = self.cleaned_data.get("checklist_json", [])
        kept_ids = {it["id"] for it in items if "id" in it}
        lead.checklist_items.exclude(id__in=kept_ids).delete()
        existing = {
            obj.id: obj
            for obj in lead.checklist_items.filter(id__in=kept_ids)
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
                LeadChecklist.objects.create(
                    lead=lead,
                    description=it["description"],
                    is_completed=it.get("is_completed", False),
                    order=idx,
                )


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
    """Form de oportunidade.

    RV07 (item 5.1) — Na CRIAÇÃO, replica a tela de Leads: permite escolher um
    Lead existente OU criar um novo Lead inline, com a opção de buscar um
    contato existente ou criar um novo contato (modo dual). Antes só dava para
    escolher um lead já existente num dropdown.
    """

    LEAD_MODE_CHOICES = (
        ("existing", "Lead existente"),
        ("new", "Criar novo lead"),
    )
    CONTACT_MODE_CHOICES = (
        ("search", "Buscar contato existente"),
        ("new", "Criar novo contato"),
    )

    lead_mode = forms.ChoiceField(
        choices=LEAD_MODE_CHOICES, widget=forms.RadioSelect,
        initial="existing", required=False, label="Lead",
    )
    contact_mode = forms.ChoiceField(
        choices=CONTACT_MODE_CHOICES, widget=forms.RadioSelect,
        initial="search", required=False, label="Contato",
    )
    contato = forms.ModelChoiceField(
        queryset=Contato.objects.none(), required=False,
        widget=forms.HiddenInput, label="Contato selecionado",
    )
    new_contato_name = forms.CharField(
        max_length=255, required=False, label="Nome do Contato",
        widget=forms.TextInput(attrs={"placeholder": "ex.: João Silva"}),
    )
    new_contato_document = forms.CharField(
        max_length=18, required=False, label="CPF/CNPJ do Contato",
        validators=[validate_cpf_or_cnpj],
        widget=forms.TextInput(attrs={"placeholder": "000.000.000-00 ou 00.000.000/0000-00"}),
    )
    new_contato_phone = forms.CharField(
        max_length=20, required=False, label="Telefone/WhatsApp",
        widget=forms.TextInput(attrs={"placeholder": "(00) 00000-0000"}),
    )
    new_contato_email = forms.EmailField(
        required=False, label="E-mail do Contato",
    )

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
        self._empresa = empresa
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
            self.fields["contato"].queryset = Contato.objects.filter(
                empresa=empresa, is_active=True
            )
        # Na criação o lead pode ser criado inline → não é obrigatório no form
        if not self.instance.pk:
            self.fields["lead"].required = False

    def clean(self):
        cleaned = super().clean()
        # A escolha de modo de lead só existe na criação.
        if self.instance.pk:
            return cleaned
        lead_mode = cleaned.get("lead_mode") or "existing"
        if lead_mode == "existing":
            if not cleaned.get("lead"):
                self.add_error(
                    "lead",
                    "Selecione um lead existente ou alterne para 'Criar novo lead'.",
                )
        else:  # new
            contact_mode = cleaned.get("contact_mode") or "search"
            if contact_mode == "search":
                if not cleaned.get("contato"):
                    self.add_error(
                        "contato",
                        "Selecione um contato existente ou alterne para 'Criar novo contato'.",
                    )
            else:
                if not (cleaned.get("new_contato_name") or "").strip():
                    self.add_error("new_contato_name", "Informe o nome do contato.")
                new_doc = (cleaned.get("new_contato_document") or "").strip()
                if new_doc and self._empresa:
                    existing = find_contato_by_document(self._empresa, new_doc)
                    if existing:
                        self.add_error(
                            "new_contato_document",
                            f"Já existe um contato com este documento: {existing.name}. "
                            f"Alterne para 'Buscar contato existente' e selecione-o.",
                        )
        return cleaned

    def _get_validation_exclusions(self):
        # Criando lead inline: o FK `lead` é preenchido no save(); exclui da
        # validação do model para não falhar com "este campo não pode ser nulo".
        exclude = super()._get_validation_exclusions()
        if not self.instance.pk and (self.cleaned_data.get("lead_mode") == "new"):
            exclude.add("lead")
        return exclude

    def save(self, commit=True):
        # RV07 — Cria o Lead inline (com contato) quando lead_mode == 'new'.
        # O lead nasce com _suppress_auto_opportunity para que a própria
        # oportunidade (esta form) seja a única criada — sem duplicar.
        if (
            not self.instance.pk
            and self.cleaned_data.get("lead_mode") == "new"
            and self._empresa
        ):
            contato = resolve_contato_from_mode(
                self._empresa,
                mode=self.cleaned_data.get("contact_mode") or "search",
                contato=self.cleaned_data.get("contato"),
                new_name=self.cleaned_data.get("new_contato_name") or "",
                new_document=self.cleaned_data.get("new_contato_document") or "",
                new_phone=self.cleaned_data.get("new_contato_phone") or "",
                new_email=self.cleaned_data.get("new_contato_email") or "",
            )
            value = self.cleaned_data.get("value") or 0
            lead = Lead(
                empresa=self._empresa,
                name=(
                    self.cleaned_data.get("title")
                    or (contato.name if contato else "Nova oportunidade")
                ),
                contato=contato,
                pipeline_stage=self.cleaned_data.get("current_stage"),
                assigned_to=self.cleaned_data.get("assigned_to"),
                estimated_value=value if value and value > 0 else None,
            )
            lead._suppress_auto_opportunity = True
            lead.save()
            self.instance.lead = lead
        return super().save(commit=commit)

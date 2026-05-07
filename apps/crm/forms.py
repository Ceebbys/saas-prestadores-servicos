from django import forms

from apps.accounts.models import Membership
from apps.contacts.models import Contato
from apps.contacts.services import (
    find_contato_by_document,
    get_or_create_contato_by_document,
)
from apps.core.forms import TailwindFormMixin
from apps.core.validators import (
    normalize_document,
    validate_cpf_or_cnpj,
)

from .models import Lead, LeadContact, Opportunity, Pipeline, PipelineStage


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

    class Meta:
        model = Lead
        # Não inclui campos legados (cpf/cnpj/email/phone/company) — vêm do Contato
        fields = ["name", "source", "pipeline_stage", "assigned_to", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "name": forms.TextInput(attrs={
                "placeholder": "ex.: Regularização Lote Bairro X",
            }),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._empresa = empresa
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

    def save(self, commit=True):
        """Cria/vincula Contato conforme contact_mode antes de salvar o Lead."""
        mode = self.cleaned_data.get("contact_mode") or "search"
        contato = self.cleaned_data.get("contato")
        if not self._empresa:
            return super().save(commit=commit)

        lead = super().save(commit=False)
        lead.empresa = self._empresa

        if mode == "new":
            new_doc = (self.cleaned_data.get("new_contato_document") or "").strip()
            defaults = {
                "name": (self.cleaned_data.get("new_contato_name") or "").strip(),
                "phone": (self.cleaned_data.get("new_contato_phone") or "").strip(),
                "whatsapp": (self.cleaned_data.get("new_contato_phone") or "").strip(),
                "email": (self.cleaned_data.get("new_contato_email") or "").strip(),
                "source": (self.cleaned_data.get("source") or ""),
            }
            if new_doc:
                contato, _ = get_or_create_contato_by_document(
                    self._empresa, new_doc, defaults=defaults,
                )
            else:
                contato = Contato.objects.create(
                    empresa=self._empresa, **defaults,
                )

        if contato:
            lead.contato = contato

        if commit:
            lead.save()
            self.save_m2m()
        return lead


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

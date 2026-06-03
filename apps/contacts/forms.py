import json

from django import forms

from apps.core.forms import TailwindFormMixin

from .models import Contato


class ContatoForm(TailwindFormMixin, forms.ModelForm):
    # RV07 (4.2) — Múltiplos telefones por contato. Mesmo padrão do checklist
    # da OS: JSON serializado num hidden field + Alpine.js no template controla
    # o CRUD. Formato: [{"id"?, "tipo", "numero", "is_principal"}].
    # Os campos phone/whatsapp do model continuam existindo (sincronizados a
    # partir daqui) para compatibilidade com busca/autocomplete/whatsapp_or_phone.
    telefones_json = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Contato
        # phone/whatsapp saem do form direto — agora geridos via `telefones`.
        exclude = [
            "empresa", "cpf_cnpj_normalized", "phone", "whatsapp",
            "created_at", "updated_at",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "cpf_cnpj": forms.TextInput(attrs={"placeholder": "CPF ou CNPJ"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pré-popula o editor de telefones a partir do banco; para contatos
        # antigos (sem ContatoTelefone) usa os campos legados phone/whatsapp.
        if self.instance and self.instance.pk:
            tels = list(
                self.instance.telefones.order_by("order", "id")
                .values("id", "tipo", "numero", "is_principal")
            )
            if not tels:
                if self.instance.whatsapp:
                    tels.append({
                        "tipo": "whatsapp", "numero": self.instance.whatsapp,
                        "is_principal": not self.instance.phone,
                    })
                if self.instance.phone:
                    tels.append({
                        "tipo": "celular", "numero": self.instance.phone,
                        "is_principal": True,
                    })
            if tels:
                self.initial["telefones_json"] = json.dumps(tels)

    def clean_cpf_cnpj(self):
        # Validação real é feita por validate_cpf_or_cnpj no field; aqui só trim.
        return (self.cleaned_data.get("cpf_cnpj") or "").strip()

    def clean_telefones_json(self):
        # RV07 (4.2) — usa o parser compartilhado (mesma regra do inline).
        from .services import parse_telefones_json
        return parse_telefones_json(self.cleaned_data.get("telefones_json", ""))

    def save(self, commit=True):
        from .services import derive_primary_phones, sync_contato_telefones

        instance = super().save(commit=False)
        tels = self.cleaned_data.get("telefones_json", [])
        instance.phone, instance.whatsapp = derive_primary_phones(tels)
        if commit:
            instance.save()
            # phone/whatsapp já setados acima → não precisa re-sincronizar.
            sync_contato_telefones(instance, tels, update_primary=False)
        return instance

    def validate_unique_for_empresa(self, empresa):
        """Custom uniqueness check used by views (since Form has no `empresa`)."""
        from apps.core.validators import normalize_document

        digits = normalize_document(self.cleaned_data.get("cpf_cnpj") or "")
        if not digits:
            return
        qs = Contato.objects.filter(empresa=empresa, cpf_cnpj_normalized=digits)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            self.add_error(
                "cpf_cnpj",
                "Já existe um contato com este CPF/CNPJ nesta empresa.",
            )

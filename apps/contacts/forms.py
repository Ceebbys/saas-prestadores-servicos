from django import forms

from apps.core.forms import TailwindFormMixin

from .models import Contato


class ContatoForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Contato
        exclude = [
            "empresa", "cpf_cnpj_normalized", "created_at", "updated_at",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "cpf_cnpj": forms.TextInput(attrs={"placeholder": "CPF ou CNPJ"}),
            "phone": forms.TextInput(attrs={"placeholder": "(00) 00000-0000"}),
            "whatsapp": forms.TextInput(attrs={"placeholder": "(00) 00000-0000"}),
        }

    def clean_cpf_cnpj(self):
        # Validation is done by validate_cpf_or_cnpj on the field; here we
        # just trim whitespace.
        return (self.cleaned_data.get("cpf_cnpj") or "").strip()

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

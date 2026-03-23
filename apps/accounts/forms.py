from django import forms
from django.contrib.auth.forms import AuthenticationForm

from apps.core.forms import TailwindFormMixin

from .models import Empresa, User


class LoginForm(TailwindFormMixin, AuthenticationForm):
    username = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={"placeholder": "seu@email.com", "autofocus": True}),
    )
    password = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(attrs={"placeholder": "Sua senha"}),
    )


class RegisterForm(TailwindFormMixin, forms.Form):
    full_name = forms.CharField(
        label="Nome completo",
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "João Silva"}),
    )
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={"placeholder": "joao@empresa.com"}),
    )
    password = forms.CharField(
        label="Senha",
        min_length=8,
        widget=forms.PasswordInput(attrs={"placeholder": "Mínimo 8 caracteres"}),
    )
    password_confirm = forms.CharField(
        label="Confirmar senha",
        widget=forms.PasswordInput(attrs={"placeholder": "Repita a senha"}),
    )
    empresa_name = forms.CharField(
        label="Nome da empresa",
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "Minha Empresa"}),
    )
    segment = forms.ChoiceField(
        label="Segmento",
        choices=Empresa.Segment.choices,
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Este e-mail já está cadastrado.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "As senhas não coincidem.")
        return cleaned_data


class UserProfileForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "email", "phone", "avatar"]
        widgets = {
            "full_name": forms.TextInput(attrs={"placeholder": "Nome completo"}),
            "email": forms.EmailInput(attrs={"placeholder": "E-mail"}),
            "phone": forms.TextInput(attrs={"placeholder": "(00) 00000-0000"}),
        }


class EmpresaForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ["name", "segment", "document", "email", "phone", "address", "logo"]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3, "placeholder": "Endereço completo"}),
            "document": forms.TextInput(attrs={"placeholder": "00.000.000/0000-00"}),
        }

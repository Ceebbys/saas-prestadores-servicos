import json

from django import forms

from apps.core.forms import TailwindFormMixin

from .models import Contato, ContatoTelefone


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
        raw = self.cleaned_data.get("telefones_json", "")
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise forms.ValidationError("Formato inválido para os telefones.")
        if not isinstance(items, list):
            raise forms.ValidationError("Telefones devem ser uma lista.")

        valid_tipos = {c[0] for c in ContatoTelefone.Tipo.choices}
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            numero = (item.get("numero") or "").strip()
            if not numero:
                continue  # linha vazia — ignorada
            tipo = item.get("tipo")
            if tipo not in valid_tipos:
                tipo = ContatoTelefone.Tipo.CELULAR
            entry = {
                "tipo": tipo,
                "numero": numero[:20],
                "is_principal": bool(item.get("is_principal", False)),
            }
            raw_id = item.get("id")
            if raw_id not in (None, "", 0):
                try:
                    entry["id"] = int(raw_id)
                except (TypeError, ValueError):
                    pass
            cleaned.append(entry)

        # Garante no máximo 1 principal; se nenhum, o primeiro vira principal.
        principal_seen = False
        for entry in cleaned:
            if entry["is_principal"] and not principal_seen:
                principal_seen = True
            elif entry["is_principal"]:
                entry["is_principal"] = False
        if cleaned and not principal_seen:
            cleaned[0]["is_principal"] = True
        return cleaned

    @staticmethod
    def _derive_primary(tels):
        """Deriva (phone, whatsapp) principais a partir da lista de telefones,
        para manter os campos legados sincronizados (compatibilidade)."""
        phone = ""
        whatsapp = ""
        principal = next((t for t in tels if t.get("is_principal")), None)
        whats = next(
            (t for t in tels if t.get("tipo") == "whatsapp" and t.get("numero")),
            None,
        )
        if principal and principal.get("numero"):
            phone = principal["numero"]
        elif tels:
            phone = tels[0].get("numero", "")
        if whats:
            whatsapp = whats["numero"]
        return phone[:20], whatsapp[:20]

    def save(self, commit=True):
        instance = super().save(commit=False)
        tels = self.cleaned_data.get("telefones_json", [])
        instance.phone, instance.whatsapp = self._derive_primary(tels)
        if commit:
            instance.save()
            self._sync_telefones(instance, tels)
        return instance

    def _sync_telefones(self, instance, tels):
        """Reconcilia ContatoTelefone com o JSON enviado (mesma estratégia do
        checklist da OS): mantém IDs presentes, deleta removidos, cria novos."""
        kept_ids = {t["id"] for t in tels if "id" in t}
        instance.telefones.exclude(id__in=kept_ids).delete()
        existing = {
            obj.id: obj for obj in instance.telefones.filter(id__in=kept_ids)
        }
        for idx, t in enumerate(tels):
            tid = t.get("id")
            if tid and tid in existing:
                obj = existing[tid]
                obj.tipo = t["tipo"]
                obj.numero = t["numero"]
                obj.is_principal = t["is_principal"]
                obj.order = idx
                obj.save(update_fields=[
                    "tipo", "numero", "is_principal", "order", "updated_at",
                ])
            else:
                ContatoTelefone.objects.create(
                    contato=instance,
                    tipo=t["tipo"],
                    numero=t["numero"],
                    is_principal=t["is_principal"],
                    order=idx,
                )

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

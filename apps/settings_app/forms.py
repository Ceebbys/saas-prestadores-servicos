from django import forms

from apps.accounts.models import EmpresaEmailConfig
from apps.automation.models import PipelineAutomationRule
from apps.core.forms import TailwindFormMixin
from apps.crm.models import PipelineStage
from apps.proposals.models import Proposal, ProposalTemplate
from apps.contracts.models import ContractTemplate


class PipelineStageForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = PipelineStage
        fields = ["pipeline", "name", "order", "color", "is_won", "is_lost"]
        widgets = {
            "color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            from apps.crm.models import Pipeline

            self.fields["pipeline"].queryset = Pipeline.objects.filter(
                empresa=empresa
            )


class ProposalTemplateForm(TailwindFormMixin, forms.ModelForm):
    default_payment_method = forms.ChoiceField(
        label="Forma de pagamento padrão",
        required=False,
        choices=[("", "---------")] + list(Proposal.PaymentMethod.choices),
    )

    class Meta:
        model = ProposalTemplate
        fields = [
            "name",
            "is_default",
            "introduction",
            "terms",
            "content",
            # RV05-F — paridade total com Proposal (header + footer image)
            "header_image",
            "header_content",
            "footer_image",
            "footer_content",
            "default_payment_method",
            "default_is_installment",
            "default_installment_count",
        ]
        widgets = {
            "introduction": forms.Textarea(attrs={"rows": 4, "data-rich-text": "true"}),
            "terms": forms.Textarea(attrs={"rows": 5, "data-rich-text": "true"}),
            "content": forms.Textarea(attrs={"rows": 6}),
            "header_content": forms.Textarea(attrs={"rows": 3, "data-rich-text": "true"}),
            "footer_content": forms.Textarea(attrs={"rows": 3, "data-rich-text": "true"}),
        }

    # RV05-F — Validação e sanitização via core (mesmo padrão de ContractTemplateForm)
    def clean_header_image(self):
        from apps.core.document_render.image_validation import validate_document_image
        return validate_document_image(self.cleaned_data.get("header_image"))

    def clean_footer_image(self):
        from apps.core.document_render.image_validation import validate_document_image
        return validate_document_image(self.cleaned_data.get("footer_image"))

    def _sanitize(self, field):
        from apps.core.document_render.sanitizer import sanitize_rich_html
        return sanitize_rich_html(self.cleaned_data.get(field, "") or "")

    def clean_introduction(self):
        return self._sanitize("introduction")

    def clean_terms(self):
        return self._sanitize("terms")

    def clean_header_content(self):
        return self._sanitize("header_content")

    def clean_footer_content(self):
        return self._sanitize("footer_content")


class ContractTemplateForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ContractTemplate
        fields = ["name", "content", "is_default"]
        widgets = {
            "content": forms.Textarea(attrs={"rows": 10}),
        }


class EmpresaEmailConfigForm(TailwindFormMixin, forms.ModelForm):
    """Form de SMTP por tenant. Senha é write-only (nunca exibe a atual)."""

    password = forms.CharField(
        label="Senha SMTP",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Deixe em branco para manter a senha atual.",
    )

    class Meta:
        model = EmpresaEmailConfig
        fields = [
            "host", "port", "username", "use_tls", "use_ssl",
            "timeout_seconds", "from_email", "from_name", "is_active",
            # IMAP (recepção) — reusa username + password do SMTP.
            "imap_host", "imap_port", "imap_use_ssl", "imap_folder",
            "imap_active",
        ]
        widgets = {
            "host": forms.TextInput(attrs={"placeholder": "smtp.gmail.com"}),
            "port": forms.NumberInput(attrs={"placeholder": "587"}),
            "username": forms.TextInput(attrs={"placeholder": "exemplo@suaempresa.com.br"}),
            "from_email": forms.EmailInput(attrs={"placeholder": "exemplo@suaempresa.com.br"}),
            "from_name": forms.TextInput(attrs={"placeholder": "Sua Empresa"}),
            "imap_host": forms.TextInput(attrs={"placeholder": "imap.gmail.com"}),
            "imap_port": forms.NumberInput(attrs={"placeholder": "993"}),
            "imap_folder": forms.TextInput(attrs={"placeholder": "INBOX"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("imap_active"):
            if not (cleaned.get("imap_host") or "").strip():
                self.add_error(
                    "imap_host",
                    "Servidor IMAP obrigatório quando recepção está ativa.",
                )
            if not cleaned.get("imap_port"):
                self.add_error(
                    "imap_port",
                    "Porta IMAP obrigatória quando recepção está ativa.",
                )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        new_password = self.cleaned_data.get("password") or ""
        if new_password:
            instance.set_password(new_password)
        if commit:
            instance.save()
        return instance


# V2A — ChatbotSecret CRUD form
class ChatbotSecretForm(TailwindFormMixin, forms.ModelForm):
    """Form do cofre de segredos do chatbot.

    O campo `value` é write-only: nunca renderiza o valor existente. Ao editar
    sem preencher, mantém o valor atual. Ao criar, é obrigatório.
    """

    value = forms.CharField(
        label="Valor (segredo)",
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        required=False,
        help_text=(
            "Cole aqui a API key / token. Será encriptado com Fernet. "
            "Deixe em branco ao editar para manter o valor atual."
        ),
    )

    class Meta:
        from apps.chatbot.models import ChatbotSecret
        model = ChatbotSecret
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "ex.: crm_api_key, webhook_zapier, hubspot_token",
                "autocomplete": "off",
            }),
            "description": forms.Textarea(attrs={
                "rows": 2,
                "placeholder": "Para que serve este segredo? (opcional)",
            }),
        }

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip().lower()
        if not name:
            raise forms.ValidationError("Nome obrigatório.")
        if not all(c.isalnum() or c in "_-" for c in name):
            raise forms.ValidationError(
                "Apenas letras, números, '_' e '-' são permitidos."
            )
        return name

    def clean(self):
        cleaned = super().clean()
        # Em criação (sem pk), valor é obrigatório
        if not self.instance.pk and not (cleaned.get("value") or "").strip():
            self.add_error("value", "Valor obrigatório ao criar um segredo novo.")
        return cleaned


class PipelineAutomationRuleForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = PipelineAutomationRule
        fields = [
            "name", "event",
            "target_pipeline", "target_stage",
            "is_active", "priority", "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.crm.models import Pipeline, PipelineStage

        # RV10 — Agrupa os ~21 eventos disponíveis por categoria de origem
        # (Proposta, Contrato, OS, Lead). Sem isso a select fica enorme e
        # confunde — com optgroup o usuário escaneia rapidamente.
        EV = PipelineAutomationRule.Event
        grouped_choices = [
            ("", "---------"),
            ("Proposta", [
                (EV.PROPOSTA_CRIADA.value, EV.PROPOSTA_CRIADA.label),
                (EV.PROPOSTA_ENVIADA.value, EV.PROPOSTA_ENVIADA.label),
                (EV.PROPOSTA_ACEITA.value, EV.PROPOSTA_ACEITA.label),
                (EV.PROPOSTA_REJEITADA.value, EV.PROPOSTA_REJEITADA.label),
                (EV.PROPOSTA_CANCELADA.value, EV.PROPOSTA_CANCELADA.label),
                (EV.PROPOSTA_EXPIRADA.value, EV.PROPOSTA_EXPIRADA.label),
            ]),
            ("Contrato", [
                (EV.CONTRATO_CRIADO.value, EV.CONTRATO_CRIADO.label),
                (EV.CONTRATO_ENVIADO.value, EV.CONTRATO_ENVIADO.label),
                (EV.CONTRATO_ASSINADO.value, EV.CONTRATO_ASSINADO.label),
                (EV.CONTRATO_ATIVO.value, EV.CONTRATO_ATIVO.label),
                (EV.CONTRATO_CONCLUIDO.value, EV.CONTRATO_CONCLUIDO.label),
                (EV.CONTRATO_CANCELADO.value, EV.CONTRATO_CANCELADO.label),
            ]),
            ("Ordem de Serviço", [
                (EV.OS_CRIADA.value, EV.OS_CRIADA.label),
                (EV.OS_AGENDADA.value, EV.OS_AGENDADA.label),
                (EV.OS_INICIADA.value, EV.OS_INICIADA.label),
                (EV.OS_PAUSADA.value, EV.OS_PAUSADA.label),
                (EV.OS_CONCLUIDA.value, EV.OS_CONCLUIDA.label),
                (EV.OS_CANCELADA.value, EV.OS_CANCELADA.label),
            ]),
            ("Lead", [
                (EV.LEAD_CRIADO.value, EV.LEAD_CRIADO.label),
                (EV.LEAD_GANHO.value, EV.LEAD_GANHO.label),
                (EV.LEAD_PERDIDO.value, EV.LEAD_PERDIDO.label),
            ]),
        ]
        self.fields["event"].choices = grouped_choices

        if empresa:
            self.fields["target_pipeline"].queryset = Pipeline.objects.filter(
                empresa=empresa,
            )
            self.fields["target_stage"].queryset = PipelineStage.objects.filter(
                pipeline__empresa=empresa,
            ).select_related("pipeline")
            # Render legível: "Pipeline X — Etapa Y"
            self.fields["target_stage"].label_from_instance = (
                lambda s: f"{s.pipeline.name} — {s.name}"
            )

    def clean(self):
        cleaned = super().clean()
        stage = cleaned.get("target_stage")
        pipeline = cleaned.get("target_pipeline")
        if stage and pipeline and stage.pipeline_id != pipeline.pk:
            self.add_error(
                "target_stage",
                "A etapa selecionada não pertence ao pipeline escolhido.",
            )
        return cleaned


# RV07 (3.1) — Funções/Cargos e Valores Hora (configuração de horas da OS).
from django.contrib.auth import get_user_model  # noqa: E402

from apps.accounts.models import Membership  # noqa: E402
from apps.operations.models import HourRate, JobRole  # noqa: E402


class JobRoleForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = JobRole
        fields = ["name", "is_active"]


class HourRateForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = HourRate
        fields = ["scope", "user", "job_role", "hourly_value", "is_active"]

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._empresa = empresa
        if empresa:
            user_model = get_user_model()
            user_ids = Membership.objects.filter(
                empresa=empresa, is_active=True,
            ).values_list("user_id", flat=True)
            self.fields["user"].queryset = user_model.objects.filter(id__in=user_ids)
            self.fields["job_role"].queryset = JobRole.objects.filter(
                empresa=empresa, is_active=True,
            )
        self.fields["user"].required = False
        self.fields["job_role"].required = False

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get("scope")
        if scope == HourRate.Scope.USER and not cleaned.get("user"):
            self.add_error("user", "Selecione o responsável.")
        if scope == HourRate.Scope.JOB_ROLE and not cleaned.get("job_role"):
            self.add_error("job_role", "Selecione a função/cargo.")
        if scope == HourRate.Scope.TEAM:
            cleaned["user"] = None
            cleaned["job_role"] = None
        return cleaned


# RV07 (6.2) — Follow-up automático de leads.
from apps.crm.models import FollowUpSettings  # noqa: E402


class FollowUpSettingsForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = FollowUpSettings
        fields = [
            "enabled",
            "threshold_1_days",
            "threshold_2_days",
            "threshold_3_days",
            "threshold_4_days",
        ]

    def clean(self):
        cleaned = super().clean()
        # Limiares devem ser não-negativos e, quando preenchidos, crescentes.
        prev = 0
        for i in range(1, 5):
            value = cleaned.get(f"threshold_{i}_days")
            if value in (None, 0):
                continue
            if value <= prev:
                self.add_error(
                    f"threshold_{i}_days",
                    "Os limiares devem ser crescentes (1º < 2º < 3º < 4º).",
                )
                break
            prev = value
        return cleaned


# ---------------------------------------------------------------------------
# RV07 (6.2) — Preferências de notificação por usuário
# ---------------------------------------------------------------------------

_NOTIF_CHECKBOX_ATTRS = {
    "class": "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500",
}


class NotificationPreferenceForm(forms.Form):
    """Preferências de notificação do usuário (canais + por tipo de evento).

    Não é ModelForm porque os checkboxes por evento são convertidos em
    ``muted_types`` (opt-out) na view. Os campos ``evt_<tipo>`` são criados
    dinamicamente a partir de ``Notification.Type``.
    """

    email_digest = forms.BooleanField(
        required=False, label="Resumo diário por e-mail",
        widget=forms.CheckboxInput(attrs=_NOTIF_CHECKBOX_ATTRS),
        help_text="Um e-mail por dia com as notificações não lidas.",
    )
    web_push = forms.BooleanField(
        required=False, label="Notificações no navegador (push)",
        widget=forms.CheckboxInput(attrs=_NOTIF_CHECKBOX_ATTRS),
        help_text="Receba avisos mesmo com a aba fechada, se o navegador permitir.",
    )

    @staticmethod
    def _event_groups():
        """(rótulo do grupo, [Notification.Type, ...]) — ordem/agrupamento na UI."""
        from apps.communications.models import Notification

        T = Notification.Type
        return [
            ("Comercial", [
                T.PROPOSAL_SENT, T.PROPOSAL_ACCEPTED,
                T.CONTRACT_SENT, T.CONTRACT_SIGNED,
                T.LEAD_NEW, T.LEAD_MOVED, T.LEAD_WON, T.LEAD_FOLLOWUP,
            ]),
            ("Operacional", [
                T.SERVICE_STARTED, T.SERVICE_COMPLETED,
            ]),
            ("Atendimento", [
                T.MESSAGE_INBOUND, T.CONVERSATION_ASSIGNED,
            ]),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _, types in self._event_groups():
            for t in types:
                self.fields[f"evt_{t}"] = forms.BooleanField(
                    required=False, label=t.label,
                    widget=forms.CheckboxInput(attrs=_NOTIF_CHECKBOX_ATTRS),
                )

    @classmethod
    def all_event_values(cls):
        """Lista plana dos valores de tipo (str) cobertos pelo formulário."""
        return [str(t) for _, types in cls._event_groups() for t in types]

    def grouped_event_fields(self):
        """Para o template: [(rótulo, [BoundField, ...]), ...]."""
        return [
            (label, [self[f"evt_{t}"] for t in types])
            for label, types in self._event_groups()
        ]

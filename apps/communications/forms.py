"""Forms da inbox de comunicações."""
from django import forms

from apps.communications.models import Conversation, ConversationMessage


class SendMessageForm(forms.Form):
    """Composer de mensagem outbound. O canal vem do submit (botão clicado)."""

    channel = forms.ChoiceField(
        choices=[
            (ConversationMessage.Channel.WHATSAPP, "WhatsApp"),
            (ConversationMessage.Channel.EMAIL, "E-mail"),
            (ConversationMessage.Channel.INTERNAL_NOTE, "Nota interna"),
        ],
    )
    content = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Escreva sua mensagem…",
            "class": "w-full rounded-lg border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500 resize-none",
        }),
    )
    subject = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            "placeholder": "Assunto (apenas para e-mail)",
            "class": "w-full rounded-lg border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500",
        }),
    )

    def clean(self):
        cleaned = super().clean()
        channel = cleaned.get("channel")
        if channel == ConversationMessage.Channel.EMAIL and not cleaned.get("subject"):
            self.add_error("subject", "Assunto é obrigatório para envio por e-mail.")
        return cleaned


class ConversationStatusForm(forms.Form):
    status = forms.ChoiceField(choices=Conversation.Status.choices)


class AssignConversationForm(forms.Form):
    user_id = forms.IntegerField(required=False)  # 0 ou vazio = desatribuir


class QuickActionForm(forms.Form):
    """Ações rápidas no painel direito."""

    ACTION_CHOICES = [
        ("move_pipeline", "Mover de etapa"),
        ("create_opportunity", "Criar oportunidade"),
        ("create_proposal", "Criar proposta"),
        ("create_contract", "Criar contrato"),
    ]
    action = forms.ChoiceField(choices=ACTION_CHOICES)
    # Para move_pipeline
    pipeline_stage_id = forms.IntegerField(required=False)
    # Para create_opportunity / proposal / contract — campos opcionais
    title = forms.CharField(required=False, max_length=200)
    value = forms.DecimalField(required=False, decimal_places=2, max_digits=12)

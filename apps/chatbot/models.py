import uuid

from django.db import models

from apps.core.models import TenantOwnedModel, TimestampedModel


class ChatbotFlow(TenantOwnedModel):
    """Fluxo de chatbot configurável (no-code)."""

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        WEBCHAT = "webchat", "WebChat"
        TELEGRAM = "telegram", "Telegram"

    name = models.CharField("Nome", max_length=100)
    description = models.TextField("Descrição", blank=True)
    is_active = models.BooleanField("Ativo", default=False)
    webhook_token = models.UUIDField(
        "Token do Webhook",
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    channel = models.CharField(
        "Canal",
        max_length=20,
        choices=Channel.choices,
        default=Channel.WHATSAPP,
    )
    welcome_message = models.TextField(
        "Mensagem de boas-vindas",
        default="Olá! Seja bem-vindo(a). Vou ajudá-lo(a) com algumas perguntas rápidas.",
    )
    fallback_message = models.TextField(
        "Mensagem de fallback",
        default="Desculpe, não entendi. Pode repetir?",
    )

    class Meta:
        verbose_name = "Fluxo de Chatbot"
        verbose_name_plural = "Fluxos de Chatbot"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ChatbotStep(TimestampedModel):
    """Passo/pergunta de um fluxo de chatbot."""

    class StepType(models.TextChoices):
        TEXT = "text", "Texto livre"
        CHOICE = "choice", "Escolha"
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Telefone"
        NAME = "name", "Nome"
        COMPANY = "company", "Empresa"

    class LeadFieldMapping(models.TextChoices):
        NAME = "name", "Nome"
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Telefone"
        COMPANY = "company", "Empresa"
        NOTES = "notes", "Observações"

    flow = models.ForeignKey(
        ChatbotFlow,
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name="Fluxo",
    )
    order = models.PositiveIntegerField("Ordem", default=0)
    question_text = models.TextField("Pergunta")
    step_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=StepType.choices,
        default=StepType.TEXT,
    )
    lead_field_mapping = models.CharField(
        "Campo do Lead",
        max_length=50,
        blank=True,
        choices=LeadFieldMapping.choices,
        help_text="Campo do lead que receberá a resposta.",
    )
    is_required = models.BooleanField("Obrigatório", default=True)

    class Meta:
        verbose_name = "Passo do Chatbot"
        verbose_name_plural = "Passos do Chatbot"
        ordering = ["order"]

    def __str__(self):
        return f"Passo {self.order}: {self.question_text[:50]}"


class ChatbotChoice(TimestampedModel):
    """Opção de resposta para um passo do tipo 'choice'."""

    step = models.ForeignKey(
        ChatbotStep,
        on_delete=models.CASCADE,
        related_name="choices",
        verbose_name="Passo",
    )
    text = models.CharField("Texto da opção", max_length=200)
    order = models.PositiveIntegerField("Ordem", default=0)
    next_step = models.ForeignKey(
        ChatbotStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incoming_choices",
        verbose_name="Próximo passo",
        help_text="Se vazio, avança para o próximo passo na ordem.",
    )

    class Meta:
        verbose_name = "Opção do Chatbot"
        verbose_name_plural = "Opções do Chatbot"
        ordering = ["order"]

    def __str__(self):
        return self.text


class ChatbotAction(TimestampedModel):
    """Ação executada pelo chatbot em determinado gatilho."""

    class Trigger(models.TextChoices):
        ON_COMPLETE = "on_complete", "Ao completar"
        ON_TIMEOUT = "on_timeout", "Timeout"
        ON_KEYWORD = "on_keyword", "Palavra-chave"

    class ActionType(models.TextChoices):
        CREATE_LEAD = "create_lead", "Criar lead"
        NOTIFY_USER = "notify_user", "Notificar usuário"
        SEND_MESSAGE = "send_message", "Enviar mensagem"

    flow = models.ForeignKey(
        ChatbotFlow,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name="Fluxo",
    )
    trigger = models.CharField(
        "Gatilho",
        max_length=20,
        choices=Trigger.choices,
        default=Trigger.ON_COMPLETE,
    )
    action_type = models.CharField(
        "Tipo de ação",
        max_length=20,
        choices=ActionType.choices,
        default=ActionType.CREATE_LEAD,
    )
    config = models.JSONField(
        "Configuração",
        default=dict,
        blank=True,
        help_text="Parâmetros da ação em JSON.",
    )

    class Meta:
        verbose_name = "Ação do Chatbot"
        verbose_name_plural = "Ações do Chatbot"
        ordering = ["trigger"]

    def __str__(self):
        return f"{self.get_trigger_display()} → {self.get_action_type_display()}"


class ChatbotSession(TimestampedModel):
    """Sessão de conversa de um visitante com o chatbot."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        COMPLETED = "completed", "Concluída"
        EXPIRED = "expired", "Expirada"

    flow = models.ForeignKey(
        ChatbotFlow,
        on_delete=models.CASCADE,
        related_name="sessions",
        verbose_name="Fluxo",
    )
    session_key = models.UUIDField(
        "Chave da sessão",
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    current_step = models.ForeignKey(
        ChatbotStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Passo atual",
    )
    lead_data = models.JSONField("Dados coletados", default=dict, blank=True)
    channel = models.CharField("Canal", max_length=20, default="webchat")
    sender_id = models.CharField("ID do remetente", max_length=255, blank=True)
    status = models.CharField(
        "Status",
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chatbot_sessions",
        verbose_name="Lead criado",
    )

    class Meta:
        verbose_name = "Sessão do Chatbot"
        verbose_name_plural = "Sessões do Chatbot"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["flow", "status"]),
            models.Index(fields=["session_key"]),
        ]

    def __str__(self):
        return f"Session {self.session_key} ({self.status})"

import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TenantOwnedModel, TimestampedModel


class ChatbotFlow(TenantOwnedModel):
    """Fluxo de chatbot configurável (no-code)."""

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        WEBCHAT = "webchat", "WebChat"
        TELEGRAM = "telegram", "Telegram"

    class TriggerType(models.TextChoices):
        FIRST_MESSAGE = "first_message", "Primeira mensagem do cliente"
        KEYWORD = "keyword", "Palavra-chave"
        INACTIVITY = "inactivity", "Inatividade"
        MANUAL = "manual", "Manual / API"

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
        "Mensagem",
        default="Olá! Seja bem-vindo(a). Vou ajudá-lo(a) com algumas perguntas rápidas.",
        help_text="Texto enviado ao iniciar o fluxo (antes do primeiro passo).",
    )
    fallback_message = models.TextField(
        "Mensagem de fallback",
        default="Desculpe, não entendi. Pode repetir?",
    )

    # --- Disparo / gatilhos ---
    trigger_type = models.CharField(
        "Tipo de gatilho",
        max_length=20,
        choices=TriggerType.choices,
        default=TriggerType.FIRST_MESSAGE,
    )
    trigger_keywords = models.CharField(
        "Palavras-chave",
        max_length=500,
        blank=True,
        help_text="Separadas por vírgula. Aplica-se quando 'Tipo de gatilho' = palavra-chave.",
    )
    inactivity_minutes = models.PositiveIntegerField(
        "Inatividade (minutos)",
        null=True,
        blank=True,
        help_text="Disparar após X minutos sem resposta do cliente.",
    )
    priority = models.PositiveIntegerField(
        "Prioridade",
        default=100,
        help_text="Menor valor = maior prioridade. Empate vai por mais recente.",
    )
    cooldown_minutes = models.PositiveIntegerField(
        "Cooldown (minutos)",
        default=60,
        help_text="Tempo mínimo entre dois disparos do mesmo fluxo para a mesma sessão.",
    )
    exclusive = models.BooleanField(
        "Exclusivo",
        default=True,
        help_text="Quando ativo, bloqueia outros fluxos enquanto este estiver em andamento.",
    )

    class Meta:
        verbose_name = "Fluxo de Chatbot"
        verbose_name_plural = "Fluxos de Chatbot"
        ordering = ["priority", "name"]

    def __str__(self):
        return self.name

    @property
    def keyword_list(self) -> list[str]:
        return [
            kw.strip().lower()
            for kw in (self.trigger_keywords or "").split(",")
            if kw.strip()
        ]


class ChatbotStep(TimestampedModel):
    """Passo/pergunta de um fluxo de chatbot."""

    class StepType(models.TextChoices):
        TEXT = "text", "Texto livre"
        CHOICE = "choice", "Escolha"
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Telefone"
        NAME = "name", "Nome"
        COMPANY = "company", "Empresa"
        DOCUMENT = "document", "CPF/CNPJ"

    class LeadFieldMapping(models.TextChoices):
        NAME = "name", "Nome"
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Telefone"
        COMPANY = "company", "Empresa"
        DOCUMENT = "cpf_cnpj", "CPF/CNPJ"
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
    is_final = models.BooleanField(
        "Passo terminal",
        default=False,
        help_text="Se marcado, encerra o fluxo ao responder este passo (útil para branching).",
    )

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


class WhatsAppConfig(TimestampedModel):
    """Configuração de WhatsApp por empresa (OneToOne)."""

    empresa = models.OneToOneField(
        "accounts.Empresa",
        on_delete=models.CASCADE,
        related_name="whatsapp_config",
        verbose_name="Empresa",
    )
    instance_name = models.CharField(
        "Nome da instância",
        max_length=100,
        unique=True,
        help_text="Identificador único desta instância na Evolution API (ex: empresa-a-whatsapp).",
    )
    phone_number = models.CharField("Número conectado", max_length=20, blank=True)
    api_url = models.URLField(
        "URL da Evolution API",
        blank=True,
        help_text="Deixe em branco para usar a URL global configurada no servidor.",
    )
    api_key = models.CharField(
        "API Key",
        max_length=200,
        blank=True,
        help_text="Deixe em branco para usar a chave global configurada no servidor.",
    )
    instance_token = models.CharField(
        "Token da Instância",
        max_length=200,
        blank=True,
        help_text="Gerado automaticamente pela Evolution API ao criar a instância.",
    )
    is_connected = models.BooleanField("Conectado", default=False)
    connected_at = models.DateTimeField("Conectado em", null=True, blank=True)

    class Meta:
        verbose_name = "Configuracao WhatsApp"
        verbose_name_plural = "Configuracoes WhatsApp"

    def __str__(self):
        return f"{self.empresa.name} — {self.instance_name}"

    @property
    def effective_api_url(self):
        return self.api_url or getattr(settings, "EVOLUTION_API_URL", "")

    @property
    def effective_api_key(self):
        """Chave para operações administrativas (criar instâncias, listar, etc.)."""
        return self.api_key or getattr(settings, "EVOLUTION_API_KEY", "")

    @property
    def effective_instance_key(self):
        """Chave para operações desta instância (enviar, QR code, status, etc.).

        Prioridade: token gerado pela Evolution → api_key override → chave global.
        O instance_token é a chave mais específica e segura para operações por instância.
        """
        return self.instance_token or self.api_key or getattr(settings, "EVOLUTION_API_KEY", "")


class ChatbotFlowDispatch(TenantOwnedModel):
    """Log auditável de quando/por que cada fluxo foi disparado ou bloqueado."""

    flow = models.ForeignKey(
        ChatbotFlow,
        on_delete=models.CASCADE,
        related_name="dispatches",
        verbose_name="Fluxo",
    )
    sender_id = models.CharField("Sender ID", max_length=255)
    triggered_at = models.DateTimeField("Disparado em", auto_now_add=True)
    reason = models.CharField(
        "Motivo",
        max_length=200,
        help_text="Ex.: 'first_message', 'inactivity 180min', 'blocked_by:flow_X'.",
    )
    blocked = models.BooleanField("Bloqueado", default=False)
    metadata = models.JSONField("Metadados", default=dict, blank=True)

    class Meta:
        verbose_name = "Disparo de Fluxo"
        verbose_name_plural = "Disparos de Fluxo"
        ordering = ["-triggered_at"]
        indexes = [
            models.Index(fields=["empresa", "flow", "-triggered_at"]),
            models.Index(fields=["sender_id", "-triggered_at"]),
        ]

    def __str__(self):
        prefix = "BLOCKED" if self.blocked else "DISPATCHED"
        return f"{prefix} {self.flow.name} → {self.sender_id} ({self.reason})"

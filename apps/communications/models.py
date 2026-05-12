"""Inbox unificada de comunicações multi-canal.

Conceito:
- `Conversation` agrupa todas as mensagens trocadas com um único `Lead`,
  independente do canal (WhatsApp, e-mail, webchat, SMS).
- `ConversationMessage` é uma entrada individual, com `channel`,
  `direction` (inbound/outbound/system) e `content`.

Único por (empresa, lead). Quando o mesmo lead manda WhatsApp e responde
e-mail mais tarde, tudo entra no mesmo thread.

Side-effects do webhook do chatbot (Evolution API) populam aqui também,
para que o atendente humano veja todo o histórico — bot + humano — num
único lugar.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TenantOwnedModel, TimestampedModel


class Conversation(TenantOwnedModel):
    """Conversa unificada com um lead.

    Multi-canal: pode receber WhatsApp + Email + WebChat etc. no mesmo
    thread. Status do atendimento (open/in_progress/waiting/closed) controla
    a inbox.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        IN_PROGRESS = "in_progress", "Em atendimento"
        WAITING = "waiting", "Aguardando cliente"
        CLOSED = "closed", "Encerrada"

    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name="Lead",
    )
    contato = models.ForeignKey(
        "contacts.Contato",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
        verbose_name="Contato",
    )
    status = models.CharField(
        "Status",
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_conversations",
        verbose_name="Atribuída para",
    )
    last_message_at = models.DateTimeField(
        "Última mensagem em",
        null=True,
        blank=True,
        db_index=True,
    )
    last_message_preview = models.CharField(
        "Prévia",
        max_length=200,
        blank=True,
        help_text="Texto da última mensagem (truncado).",
    )
    last_message_direction = models.CharField(
        "Direção da última",
        max_length=10,
        blank=True,
    )
    last_message_channel = models.CharField(
        "Canal da última",
        max_length=20,
        blank=True,
    )
    unread_count = models.PositiveIntegerField(
        "Mensagens não lidas",
        default=0,
        help_text="Inbounds desde o último readall.",
    )

    class Meta:
        verbose_name = "Conversa"
        verbose_name_plural = "Conversas"
        ordering = ["-last_message_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "lead"],
                name="communications_conversation_unique_empresa_lead",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "status", "-last_message_at"]),
            models.Index(fields=["assigned_to", "-last_message_at"]),
        ]

    def __str__(self):
        return f"Conversa com {self.lead.name} ({self.status})"

    def touch(
        self,
        *,
        direction: str,
        channel: str,
        content: str,
        save: bool = True,
    ) -> None:
        """Atualiza última-mensagem snapshot quando uma ConversationMessage
        é adicionada. `direction` inbound também incrementa unread_count.

        Race-safe: usa F('unread_count') + 1 via .update() para que dois
        inbounds concorrentes (ex.: webhook + IMAP poll) não percam
        incrementos (ambos lendo count=0 e ambos salvando count=1).
        """
        from django.db.models import F

        now = timezone.now()
        preview = (content or "")[:200]
        if save:
            update_kwargs = {
                "last_message_at": now,
                "last_message_preview": preview,
                "last_message_direction": direction,
                "last_message_channel": channel,
                "updated_at": now,
            }
            if direction == ConversationMessage.Direction.INBOUND:
                update_kwargs["unread_count"] = F("unread_count") + 1
            type(self).objects.filter(pk=self.pk).update(**update_kwargs)
            # Refresh para resolver F() em memória + manter consistência
            self.refresh_from_db(fields=[
                "last_message_at", "last_message_preview",
                "last_message_direction", "last_message_channel",
                "unread_count", "updated_at",
            ])
        else:
            self.last_message_at = now
            self.last_message_preview = preview
            self.last_message_direction = direction
            self.last_message_channel = channel
            if direction == ConversationMessage.Direction.INBOUND:
                self.unread_count = (self.unread_count or 0) + 1

    def mark_read(self) -> None:
        """Zera contagem de não-lidas."""
        if self.unread_count:
            self.unread_count = 0
            self.save(update_fields=["unread_count", "updated_at"])


class ConversationMessage(TimestampedModel):
    """Mensagem individual numa conversa multi-canal."""

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Recebida"
        OUTBOUND = "outbound", "Enviada"
        SYSTEM = "system", "Sistema"

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "E-mail"
        WEBCHAT = "webchat", "WebChat"
        SMS = "sms", "SMS"
        INTERNAL_NOTE = "internal_note", "Nota interna"

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        SENT = "sent", "Enviada"
        DELIVERED = "delivered", "Entregue"
        READ = "read", "Lida"
        FAILED = "failed", "Falhou"
        NA = "na", "—"  # para inbound/system

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Conversa",
    )
    direction = models.CharField(
        "Direção", max_length=10, choices=Direction.choices,
    )
    channel = models.CharField(
        "Canal", max_length=20, choices=Channel.choices,
    )
    content = models.TextField("Conteúdo")
    payload = models.JSONField(
        "Payload", default=dict, blank=True,
        help_text="Anexos, botões, raw provider data, metadados.",
    )
    # Quem enviou (humano interno) — preenchido em outbound
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_conversation_messages",
        verbose_name="Enviada por (atendente)",
    )
    # Identidade externa (inbound)
    sender_external_id = models.CharField(
        "ID externo", max_length=120, blank=True,
        help_text="Telefone, e-mail ou JID de origem (inbound).",
    )
    sender_name = models.CharField(
        "Nome externo", max_length=120, blank=True,
    )
    # Entrega
    delivery_status = models.CharField(
        "Status de entrega", max_length=12,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.NA,
    )
    delivered_at = models.DateTimeField("Entregue em", null=True, blank=True)
    read_at = models.DateTimeField("Lida em", null=True, blank=True)
    error_message = models.CharField(
        "Erro de entrega", max_length=500, blank=True,
    )
    # Rastreamento (opcional)
    triggered_by_chatbot_session = models.ForeignKey(
        "chatbot.ChatbotSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversation_messages",
        verbose_name="Disparada por sessão do bot",
    )

    class Meta:
        verbose_name = "Mensagem"
        verbose_name_plural = "Mensagens"
        ordering = ["conversation", "created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["direction", "channel", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.channel}/{self.direction}] {self.content[:60]}"


def get_or_create_conversation(empresa, lead, contato=None) -> Conversation:
    """Helper para obter/criar a conversa única por (empresa, lead)."""
    conv, _ = Conversation.objects.get_or_create(
        empresa=empresa,
        lead=lead,
        defaults={
            "contato": contato,
            "status": Conversation.Status.OPEN,
        },
    )
    # Atualiza contato vazio se vier resolvido depois
    if contato and not conv.contato_id:
        conv.contato = contato
        conv.save(update_fields=["contato", "updated_at"])
    return conv


# ============================================================================
# Notifications (Fase 4)
# ============================================================================


class Notification(TimestampedModel):
    """Notificação in-app, dirigida a um usuário específico.

    Pode estar atrelada a uma empresa (multi-tenant) e a uma URL de ação
    (para o usuário clicar e ir direto ao recurso). O cliente conecta via
    `/ws/notifications/` para receber em realtime, e a sininha no topbar
    consulta `/notifications/` para listar.
    """

    class Type(models.TextChoices):
        MESSAGE_INBOUND = "message_inbound", "Nova mensagem recebida"
        CONVERSATION_ASSIGNED = "conversation_assigned", "Conversa atribuída a você"
        LEAD_NEW = "lead_new", "Novo lead"
        PROPOSAL_ACCEPTED = "proposal_accepted", "Proposta aceita"
        CONTRACT_SIGNED = "contract_signed", "Contrato assinado"
        SYSTEM = "system", "Sistema"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Destinatário",
    )
    empresa = models.ForeignKey(
        "accounts.Empresa",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="notifications",
        help_text="Tenant; null para notificações pessoais (sistema).",
    )
    type = models.CharField(
        "Tipo", max_length=40, choices=Type.choices, default=Type.SYSTEM,
    )
    title = models.CharField("Título", max_length=200)
    body = models.TextField("Corpo", blank=True)
    url = models.CharField(
        "URL de ação", max_length=500, blank=True,
        help_text="Caminho relativo (ex.: /communications/inbox/42/).",
    )
    icon = models.CharField(
        "Ícone", max_length=40, blank=True,
        help_text="Nome do heroicon (ex.: 'envelope', 'user-plus').",
    )
    payload = models.JSONField(
        "Payload", default=dict, blank=True,
        help_text="Dados adicionais para deep-link, contadores, etc.",
    )
    read_at = models.DateTimeField("Lida em", null=True, blank=True)

    class Meta:
        verbose_name = "Notificação"
        verbose_name_plural = "Notificações"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "read_at", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.type}] {self.title} → {self.user_id}"

    def mark_read(self):
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at", "updated_at"])


class MessageTemplate(TenantOwnedModel):
    """Template de mensagem reutilizável (resposta rápida) por tenant.

    O atendente digita `/` no composer e abre dropdown com seus templates.
    Conteúdo passa por Jinja2 sandboxed antes de inserir — variáveis
    suportadas:
        {{ lead.name }}, {{ lead.email }}, {{ lead.phone }},
        {{ contato.name }}, {{ empresa.name }},
        {{ user.first_name }}, {{ user.email }},
        {{ now.date }}, {{ now.time }}
    """

    class Channel(models.TextChoices):
        ANY = "any", "Qualquer canal"
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "E-mail"
        INTERNAL_NOTE = "internal_note", "Nota interna"

    class Category(models.TextChoices):
        GREETING = "greeting", "Saudação"
        FOLLOWUP = "followup", "Follow-up"
        PROPOSAL = "proposal", "Proposta"
        CLOSING = "closing", "Encerramento"
        OBJECTION = "objection", "Objeção"
        OTHER = "other", "Outro"

    name = models.CharField("Nome", max_length=120)
    shortcut = models.CharField(
        "Atalho", max_length=40, blank=True,
        help_text="Atalho digitável (ex.: 'ola', 'preco'). Sem espaços.",
    )
    category = models.CharField(
        "Categoria", max_length=20,
        choices=Category.choices, default=Category.OTHER,
    )
    channel = models.CharField(
        "Canal", max_length=20,
        choices=Channel.choices, default=Channel.ANY,
    )
    content = models.TextField(
        "Conteúdo",
        help_text="Suporta {{ lead.name }}, {{ contato.name }}, "
                  "{{ empresa.name }}, {{ user.first_name }}, {{ now.date }}.",
    )
    is_active = models.BooleanField("Ativo", default=True)
    usage_count = models.PositiveIntegerField(
        "Uso", default=0, editable=False,
        help_text="Contador de quantas vezes foi inserido em conversas.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="message_templates_created",
    )

    class Meta:
        verbose_name = "Template de mensagem"
        verbose_name_plural = "Templates de mensagem"
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "shortcut"],
                condition=~models.Q(shortcut=""),
                name="msg_template_unique_shortcut_per_empresa",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "is_active", "category"]),
            models.Index(fields=["empresa", "shortcut"]),
        ]

    def __str__(self):
        return f"{self.name} [{self.category}]"

    def save(self, *args, **kwargs):
        # Normaliza shortcut: lowercase, sem espaços, sem '/' inicial
        if self.shortcut:
            self.shortcut = (
                self.shortcut.strip().lower()
                .lstrip("/").replace(" ", "_")
            )
        super().save(*args, **kwargs)


class PushSubscription(TimestampedModel):
    """Subscription Web Push (VAPID) — usado para enviar notificações
    push mesmo quando o navegador está fechado.

    Criada pelo browser ao chamar `PushManager.subscribe()` no service worker.
    Cada usuário pode ter múltiplas (laptop, mobile, etc.).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.URLField("Endpoint", max_length=500, unique=True)
    p256dh = models.CharField("Chave P256DH", max_length=200)
    auth = models.CharField("Auth", max_length=80)
    user_agent = models.CharField("User-Agent", max_length=300, blank=True)
    last_used_at = models.DateTimeField("Último uso", null=True, blank=True)

    class Meta:
        verbose_name = "Subscription Push"
        verbose_name_plural = "Subscriptions Push"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return f"Push subscription #{self.pk} → user {self.user_id}"

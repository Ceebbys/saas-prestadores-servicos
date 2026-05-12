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
        """
        self.last_message_at = timezone.now()
        self.last_message_preview = (content or "")[:200]
        self.last_message_direction = direction
        self.last_message_channel = channel
        if direction == ConversationMessage.Direction.INBOUND:
            self.unread_count = (self.unread_count or 0) + 1
        if save:
            self.save(update_fields=[
                "last_message_at", "last_message_preview",
                "last_message_direction", "last_message_channel",
                "unread_count", "updated_at",
            ])

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

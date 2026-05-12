"""Sinais do app communications.

Conectados em `apps.py::ready()`.

Disparam `channel_layer.group_send` quando uma nova `ConversationMessage`
é criada (inbound, outbound humano, bot, nota interna). Consumidor da
inbox atualiza a UI em tempo real.

Tolerância a falha: se o channel layer não estiver disponível (ex.: durante
migrations, ou se Redis cair), o sinal loga e segue — nunca derruba o save.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.communications.models import Conversation, ConversationMessage

logger = logging.getLogger(__name__)


def _get_channel_layer():
    """Lazy import + tolerância — devolve None se channels não inicializou."""
    try:
        from channels.layers import get_channel_layer
        return get_channel_layer()
    except Exception:  # noqa: BLE001
        return None


@receiver(post_save, sender=ConversationMessage)
def broadcast_message_created(sender, instance: ConversationMessage, created: bool, **kwargs):
    if not created:
        return
    layer = _get_channel_layer()
    if layer is None:
        return

    try:
        conv = instance.conversation
        payload = {
            "type": "message.new",
            "conversation_id": conv.pk,
            "empresa_id": conv.empresa_id,
            "message_id": instance.pk,
            "direction": instance.direction,
            "channel": instance.channel,
            "preview": (instance.content or "")[:160],
            "created_at": instance.created_at.isoformat() if instance.created_at else None,
            "delivery_status": instance.delivery_status,
        }
        # Broadcast: inbox da empresa (atualiza lista) + thread da conversa
        empresa_group = f"inbox-empresa-{conv.empresa_id}"
        conv_group = f"inbox-conv-{conv.pk}"
        async_to_sync(layer.group_send)(empresa_group, payload)
        async_to_sync(layer.group_send)(conv_group, payload)
    except Exception:  # noqa: BLE001
        logger.exception(
            "broadcast_message_created failed message_id=%s",
            getattr(instance, "pk", None),
        )

    # Notificação in-app para o atendente atribuído (somente inbound).
    if instance.direction == ConversationMessage.Direction.INBOUND:
        try:
            from apps.communications.notifications import notify_new_message
            notify_new_message(instance.conversation, instance)
        except Exception:  # noqa: BLE001
            logger.exception(
                "auto_notify_failed message_id=%s",
                getattr(instance, "pk", None),
            )


@receiver(post_save, sender=Conversation)
def broadcast_conversation_updated(sender, instance: Conversation, created: bool, **kwargs):
    """Notifica mudanças de status/assigned_to (não dispara em criação para
    evitar duplicação com a primeira mensagem)."""
    if created:
        return
    update_fields = kwargs.get("update_fields") or set()
    # Só broadcasta se houver mudança "interessante" (filtro grosseiro;
    # frontend decide se re-renderiza). Sem update_fields, broadcasta.
    interesting = {
        "status", "assigned_to", "assigned_to_id",
        "last_message_at", "last_message_preview",
        "last_message_direction", "last_message_channel",
        "unread_count",
    }
    if update_fields and not (interesting & set(update_fields)):
        return

    layer = _get_channel_layer()
    if layer is None:
        return

    try:
        payload = {
            "type": "conversation.updated",
            "conversation_id": instance.pk,
            "empresa_id": instance.empresa_id,
            "status": instance.status,
            "assigned_to_id": instance.assigned_to_id,
            "unread_count": instance.unread_count,
            "last_message_at": (
                instance.last_message_at.isoformat()
                if instance.last_message_at else None
            ),
            "last_message_preview": instance.last_message_preview,
            "last_message_channel": instance.last_message_channel,
            "last_message_direction": instance.last_message_direction,
        }
        empresa_group = f"inbox-empresa-{instance.empresa_id}"
        conv_group = f"inbox-conv-{instance.pk}"
        async_to_sync(layer.group_send)(empresa_group, payload)
        async_to_sync(layer.group_send)(conv_group, payload)
    except Exception:  # noqa: BLE001
        logger.exception(
            "broadcast_conversation_updated failed conv_id=%s",
            getattr(instance, "pk", None),
        )

"""Serviço de notificações in-app + Web Push.

API principal: `notify()` cria uma `Notification` na DB e dispara broadcast
WS para o grupo `notif-user-<user_id>`. Adicionalmente, se o usuário tiver
`PushSubscription` ativa e `pywebpush` estiver disponível, envia push.

Helpers de alto nível:
    notify_new_message(conversation, message)
    notify_conversation_assigned(conversation, assigned_user, assigned_by)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync

from apps.communications.models import Notification

if TYPE_CHECKING:
    from apps.accounts.models import Empresa, User
    from apps.communications.models import Conversation, ConversationMessage

logger = logging.getLogger(__name__)


def notify(
    user,
    *,
    type: str,
    title: str,
    body: str = "",
    url: str = "",
    icon: str = "",
    empresa=None,
    payload: dict | None = None,
    push: bool = True,
) -> Notification:
    """Cria notificação na DB + broadcast WS + Web Push (best-effort).

    Args:
        user: instância do User destinatário
        type: valor da enum `Notification.Type`
        title: título curto (<=200 chars)
        body: corpo opcional (texto)
        url: deep-link relativo (ex.: '/inbox/42/')
        icon: nome do heroicon
        empresa: Empresa (opcional, default = active_empresa do user)
        payload: dados extras (JSONField)
        push: se True, tenta Web Push para subscriptions ativas

    Returns:
        Notification persistida
    """
    if empresa is None:
        empresa = getattr(user, "active_empresa", None)

    notif = Notification.objects.create(
        user=user,
        empresa=empresa,
        type=type,
        title=title[:200],
        body=body or "",
        url=url or "",
        icon=icon or "",
        payload=payload or {},
    )

    # Broadcast WS
    _broadcast_ws(notif)

    # Web Push (best-effort, não bloqueia o fluxo se falhar)
    if push:
        try:
            _send_web_push(notif)
        except Exception:  # noqa: BLE001
            logger.exception(
                "web_push_send_failed user_id=%s notif_id=%s",
                user.pk, notif.pk,
            )

    return notif


def _broadcast_ws(notif: Notification) -> None:
    """Envia evento para grupo `notif-user-<user_id>`."""
    try:
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if layer is None:
            return
        payload = {
            "type": "notification.new",
            "id": notif.pk,
            "notification_type": notif.type,
            "title": notif.title,
            "body": notif.body,
            "url": notif.url,
            "icon": notif.icon,
            "created_at": notif.created_at.isoformat() if notif.created_at else None,
        }
        async_to_sync(layer.group_send)(
            f"notif-user-{notif.user_id}", payload,
        )
    except Exception:  # noqa: BLE001
        logger.exception("notification_ws_broadcast_failed notif_id=%s", notif.pk)


def _send_web_push(notif: Notification) -> None:
    """Envia Web Push via pywebpush para todas as subscriptions ativas do usuário.

    Falha silenciosa por subscription — se uma subscription estiver expirada,
    `pywebpush` levanta WebPushException com response.status_code==410,
    e nós removemos a row. Outras falhas só logam.
    """
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.debug("pywebpush não instalado; pulando Web Push.")
        return

    from django.conf import settings
    from django.utils import timezone
    from apps.communications.models import PushSubscription

    vapid_private = getattr(settings, "VAPID_PRIVATE_KEY", "")
    vapid_claims = {
        "sub": f"mailto:{getattr(settings, 'VAPID_CONTACT_EMAIL', 'admin@servicopro.app')}",
    }
    if not vapid_private:
        logger.debug("VAPID_PRIVATE_KEY ausente; Web Push desabilitado.")
        return

    import json
    data = json.dumps({
        "title": notif.title,
        "body": notif.body or notif.title,
        "url": notif.url,
        "tag": f"notif-{notif.pk}",
        "icon": notif.icon or "",
    })

    subs = PushSubscription.objects.filter(user_id=notif.user_id)
    expired_pks = []
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=data,
                vapid_private_key=vapid_private,
                vapid_claims=dict(vapid_claims),
                ttl=86400,  # 24h
            )
            sub.last_used_at = timezone.now()
            sub.save(update_fields=["last_used_at", "updated_at"])
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None) if response else None
            if status in (404, 410):
                expired_pks.append(sub.pk)
            else:
                logger.warning(
                    "web_push_failed sub_pk=%s status=%s detail=%s",
                    sub.pk, status, str(exc)[:200],
                )
        except Exception:  # noqa: BLE001
            logger.exception("web_push_unexpected sub_pk=%s", sub.pk)

    if expired_pks:
        PushSubscription.objects.filter(pk__in=expired_pks).delete()
        logger.info("expired_push_subscriptions_pruned count=%s", len(expired_pks))


# ----------------------------------------------------------------------------
# Helpers de alto nível por tipo de evento
# ----------------------------------------------------------------------------


def notify_new_message(conversation, message) -> list:
    """Notifica atendentes sobre nova mensagem inbound.

    Estratégia:
        - Se a conversa TEM `assigned_to`: notifica apenas o atribuído.
        - Se NÃO tem assigned_to (conversa nova / não-atribuída): notifica
          OWNER + ADMIN + MANAGER da empresa para garantir que ninguém perca
          msg de cliente novo. MEMBERs comuns não são notificados (evita
          spam em equipes grandes).

    Retorna lista de `Notification` criadas (vazia se ninguém para notificar).
    """
    lead_name = conversation.lead.name if conversation.lead else "?"
    common_kwargs = {
        "type": Notification.Type.MESSAGE_INBOUND,
        "title": f"Nova mensagem de {lead_name}",
        "body": (message.content or "")[:200],
        "url": f"/inbox/{conversation.pk}/",
        "icon": "chat-bubble-left-right",
        "empresa": conversation.empresa,
        "payload": {
            "conversation_id": conversation.pk,
            "channel": message.channel,
        },
    }

    created = []
    assigned = conversation.assigned_to
    if assigned is not None:
        # Caminho 1: notifica apenas o atribuído
        created.append(notify(assigned, **common_kwargs))
    else:
        # Caminho 2: broadcast aos decisores da empresa
        from apps.accounts.models import Membership
        from django.db.models import Q
        memberships = (
            Membership.objects
            .filter(
                empresa=conversation.empresa,
                is_active=True,
                user__is_active=True,
            )
            .filter(
                Q(role=Membership.Role.OWNER)
                | Q(role=Membership.Role.ADMIN)
                | Q(role=Membership.Role.MANAGER)
            )
            .select_related("user")
            .distinct()
        )
        for m in memberships:
            try:
                created.append(notify(m.user, **common_kwargs))
            except Exception:  # noqa: BLE001
                logger.exception(
                    "notify_new_message failed user=%s conv=%s",
                    m.user_id, conversation.pk,
                )
    return created


def notify_conversation_assigned(conversation, assigned_user, assigned_by) -> Notification | None:
    """Notifica usuário quando uma conversa é atribuída a ele.

    Não notifica auto-atribuição (assigned_user == assigned_by).
    """
    if assigned_user is None or assigned_user == assigned_by:
        return None
    lead_name = conversation.lead.name if conversation.lead else "?"
    by_name = (
        getattr(assigned_by, "first_name_display", None)
        or getattr(assigned_by, "email", "Sistema")
        if assigned_by else "Sistema"
    )
    return notify(
        assigned_user,
        type=Notification.Type.CONVERSATION_ASSIGNED,
        title=f"Conversa com {lead_name} atribuída a você",
        body=f"Atribuída por {by_name}." if assigned_by else "",
        url=f"/inbox/{conversation.pk}/",
        icon="user-plus",
        empresa=conversation.empresa,
        payload={"conversation_id": conversation.pk},
    )

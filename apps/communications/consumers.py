"""WebSocket consumers — entrega realtime de inbox + notificações.

Cada consumer adiciona o canal a 2 grupos:
    inbox-empresa-<empresa_id>           — broadcast geral da inbox do tenant
    inbox-conv-<conversation_id>         — assinatura específica (PropostalDetailView)

E para notificações:
    notif-user-<user_id>                 — notificações pessoais

Sinais em `apps/communications/signals.py` disparam group_send com payload
JSON. O frontend (Alpine.js + HTMX) consome via `event.data` e atualiza
DOM sem reload — opcionalmente hx-get para revalidar parciais.

Segurança:
- Anonymous é rejeitado no connect
- Tenant isolation: o usuário só recebe broadcast da sua empresa ativa
- Cross-tenant é impossível pois o group é nomeado pelo empresa_id do user
"""
from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


class _BaseAuthConsumer(AsyncJsonWebsocketConsumer):
    """Mixin que recusa connect anônimo e resolve a empresa ativa."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)  # 4401 = unauthenticated
            return False
        empresa_id = await self._resolve_empresa_id(user)
        if not empresa_id:
            await self.close(code=4403)  # 4403 = forbidden / sem empresa
            return False
        self.user = user
        self.empresa_id = empresa_id
        await self.accept()
        return True

    @database_sync_to_async
    def _resolve_empresa_id(self, user) -> int | None:
        """Espelha `EmpresaMiddleware` — busca a empresa ativa do user."""
        active = getattr(user, "active_empresa_id", None)
        if active:
            return active
        # Fallback: primeira membership ativa
        from apps.accounts.models import Membership
        m = (
            Membership.objects
            .filter(user=user, is_active=True, empresa__is_active=True)
            .order_by("created_at")
            .first()
        )
        return m.empresa_id if m else None


class InboxConsumer(_BaseAuthConsumer):
    """Recebe broadcasts de novas mensagens e mudanças de conversa.

    Mensagens enviadas pelo servidor têm shape:
        {"type": "message.new", "conversation_id": int, "preview": str, ...}
        {"type": "conversation.updated", "conversation_id": int, "status": str, ...}

    Cliente pode subscrever a uma conversa específica enviando:
        {"action": "subscribe", "conversation_id": 42}
        {"action": "unsubscribe", "conversation_id": 42}
    """

    GROUP_EMPRESA_FMT = "inbox-empresa-{empresa_id}"
    GROUP_CONV_FMT = "inbox-conv-{conv_id}"

    async def connect(self):
        ok = await super().connect()
        if not ok:
            return
        self._conv_subscriptions: set[int] = set()
        await self.channel_layer.group_add(
            self.GROUP_EMPRESA_FMT.format(empresa_id=self.empresa_id),
            self.channel_name,
        )

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(
                self.GROUP_EMPRESA_FMT.format(empresa_id=self.empresa_id),
                self.channel_name,
            )
        except Exception:  # noqa: BLE001
            pass
        for conv_id in list(getattr(self, "_conv_subscriptions", ())):
            try:
                await self.channel_layer.group_discard(
                    self.GROUP_CONV_FMT.format(conv_id=conv_id),
                    self.channel_name,
                )
            except Exception:  # noqa: BLE001
                pass

    async def receive_json(self, content, **kwargs):
        action = (content or {}).get("action")
        conv_id = (content or {}).get("conversation_id")
        if action == "subscribe" and isinstance(conv_id, int):
            ok = await self._check_conv_access(conv_id)
            if not ok:
                await self.send_json({
                    "type": "error",
                    "message": "forbidden_conversation",
                    "conversation_id": conv_id,
                })
                return
            self._conv_subscriptions.add(conv_id)
            await self.channel_layer.group_add(
                self.GROUP_CONV_FMT.format(conv_id=conv_id),
                self.channel_name,
            )
            await self.send_json({"type": "subscribed", "conversation_id": conv_id})
        elif action == "unsubscribe" and isinstance(conv_id, int):
            self._conv_subscriptions.discard(conv_id)
            await self.channel_layer.group_discard(
                self.GROUP_CONV_FMT.format(conv_id=conv_id),
                self.channel_name,
            )
            await self.send_json({"type": "unsubscribed", "conversation_id": conv_id})
        elif action == "ping":
            await self.send_json({"type": "pong"})

    @database_sync_to_async
    def _check_conv_access(self, conv_id: int) -> bool:
        """Garante que a conversa pertence à empresa ativa do user (isolation)."""
        from apps.communications.models import Conversation
        return Conversation.objects.filter(
            pk=conv_id, empresa_id=self.empresa_id,
        ).exists()

    # ------------------------------------------------------------------
    # Handlers de group_send (nome do método = "type" no payload, com '.' → '_')
    # ------------------------------------------------------------------

    async def message_new(self, event):
        """Disparo: post_save de ConversationMessage."""
        await self.send_json(event)

    async def conversation_updated(self, event):
        """Disparo: post_save de Conversation (status, assigned_to, etc.)."""
        await self.send_json(event)


class NotificationsConsumer(_BaseAuthConsumer):
    """Notificações pessoais — bell + toasts.

    Grupo: notif-user-<user_id>. Cada user recebe só as suas.
    """

    GROUP_FMT = "notif-user-{user_id}"

    async def connect(self):
        ok = await super().connect()
        if not ok:
            return
        await self.channel_layer.group_add(
            self.GROUP_FMT.format(user_id=self.user.pk),
            self.channel_name,
        )

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(
                self.GROUP_FMT.format(user_id=self.user.pk),
                self.channel_name,
            )
        except Exception:  # noqa: BLE001
            pass

    async def notification_new(self, event):
        await self.send_json(event)

"""Serviços de envio multi-canal para a inbox de comunicações.

- `send_whatsapp`: usa EvolutionAPIClient (apps.chatbot.whatsapp) que
  resolve credenciais por empresa (WhatsAppConfig)
- `send_email`: usa EmpresaEmailConfig (SMTP por tenant, RV04) com fallback
  para SMTP global
- `record_inbound`: helper chamado pelo webhook quando uma mensagem
  externa chega (cria/atualiza Conversation + grava ConversationMessage)
- `record_outbound`: helper interno após envio bem-sucedido

Multi-tenant é responsabilidade do CHAMADOR: passe sempre a empresa
correta.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.communications.models import (
    Conversation,
    ConversationMessage,
    get_or_create_conversation,
)

if TYPE_CHECKING:
    from apps.accounts.models import Empresa, User
    from apps.crm.models import Lead

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------


def send_whatsapp(
    conversation: Conversation,
    content: str,
    *,
    sender_user=None,
    phone: str | None = None,
) -> ConversationMessage:
    """Envia mensagem WhatsApp via Evolution API + grava ConversationMessage.

    Retorna a mensagem gravada (com status=sent ou failed).
    """
    from apps.chatbot.models import WhatsAppConfig
    from apps.chatbot.whatsapp import EvolutionAPIClient

    # ATENÇÃO: criamos a mensagem DEFAULT FAILED (não PENDING). Se a request
    # crashar entre create e save de SENT, fica como FAILED — atendente sabe
    # que precisa reenviar. Evita "msg PENDING órfã" silenciosa.
    msg = ConversationMessage.objects.create(
        conversation=conversation,
        direction=ConversationMessage.Direction.OUTBOUND,
        channel=ConversationMessage.Channel.WHATSAPP,
        content=content,
        sender_user=sender_user,
        delivery_status=ConversationMessage.DeliveryStatus.FAILED,
        error_message="Envio interrompido — verifique o status do canal.",
    )

    # Resolve número de telefone
    phone = phone or _resolve_phone(conversation)
    if not phone:
        msg.error_message = "Lead sem telefone cadastrado."
        msg.save(update_fields=["error_message", "updated_at"])
        return msg

    # Resolve config WhatsApp do tenant
    config = WhatsAppConfig.objects.filter(empresa=conversation.empresa).first()
    if config:
        client = EvolutionAPIClient(
            api_url=config.effective_api_url,
            api_key=config.effective_instance_key,
            instance=config.instance_name,
        )
    else:
        client = EvolutionAPIClient()  # fallback settings globais

    if not client.configured:
        msg.error_message = "Evolution API não configurada para esta empresa."
        msg.save(update_fields=["error_message", "updated_at"])
        return msg

    try:
        ok = client.send_text(phone, content)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Exceção ao enviar WhatsApp para %s", phone)
        msg.error_message = f"Exceção: {str(exc)[:400]}"
        msg.save(update_fields=["error_message", "updated_at"])
        return msg

    if ok:
        msg.delivery_status = ConversationMessage.DeliveryStatus.SENT
        msg.delivered_at = timezone.now()
        msg.error_message = ""
        msg.save(update_fields=[
            "delivery_status", "delivered_at", "error_message", "updated_at",
        ])
    else:
        msg.error_message = "Falha ao enviar via Evolution API."
        msg.save(update_fields=["error_message", "updated_at"])

    conversation.touch(
        direction=ConversationMessage.Direction.OUTBOUND,
        channel=ConversationMessage.Channel.WHATSAPP,
        content=content,
    )
    return msg


def send_email(
    conversation: Conversation,
    subject: str,
    content: str,
    *,
    sender_user=None,
    to_email: str | None = None,
) -> ConversationMessage:
    """Envia e-mail via SMTP do tenant (EmpresaEmailConfig) + grava."""
    from django.core.mail import EmailMessage
    from apps.proposals.services.email import _resolve_smtp_for

    # Default FAILED — atualiza para SENT só após confirm de envio
    msg = ConversationMessage.objects.create(
        conversation=conversation,
        direction=ConversationMessage.Direction.OUTBOUND,
        channel=ConversationMessage.Channel.EMAIL,
        content=content,
        payload={"subject": subject},
        sender_user=sender_user,
        delivery_status=ConversationMessage.DeliveryStatus.FAILED,
        error_message="Envio interrompido — verifique o status SMTP.",
    )

    to_email = to_email or _resolve_email(conversation)
    if not to_email:
        msg.error_message = "Lead sem e-mail cadastrado."
        msg.save(update_fields=["error_message", "updated_at"])
        return msg

    # Email threading: cria Message-Id próprio + In-Reply-To se houver
    # mensagem anterior nessa conversa (Gmail/Outlook agrupam thread).
    import uuid as _uuid
    site_domain = "servicopro.app"
    message_id = f"<conv-{conversation.pk}-msg-{_uuid.uuid4()}@{site_domain}>"
    last_email = (
        conversation.messages
        .filter(channel=ConversationMessage.Channel.EMAIL)
        .exclude(pk=msg.pk)
        .order_by("-created_at")
        .first()
    )
    in_reply_to = (last_email.payload or {}).get("message_id") if last_email else None
    extra_headers = {"Message-ID": message_id}
    if in_reply_to:
        extra_headers["In-Reply-To"] = in_reply_to
        extra_headers["References"] = in_reply_to

    try:
        connection, from_address = _resolve_smtp_for(conversation.empresa)
        email = EmailMessage(
            subject=subject,
            body=content,
            from_email=from_address,
            to=[to_email],
            connection=connection,
            headers=extra_headers,
        )
        email.send(fail_silently=False)
        msg.payload = {**(msg.payload or {}), "message_id": message_id, "in_reply_to": in_reply_to}
        msg.delivery_status = ConversationMessage.DeliveryStatus.SENT
        msg.delivered_at = timezone.now()
        msg.error_message = ""
        msg.save(update_fields=[
            "delivery_status", "delivered_at", "error_message", "payload", "updated_at",
        ])
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Falha ao enviar e-mail conv=%s (empresa=%s)",
            conversation.pk, conversation.empresa_id,
        )
        msg.error_message = str(exc)[:500]
        msg.save(update_fields=["error_message", "updated_at"])

    conversation.touch(
        direction=ConversationMessage.Direction.OUTBOUND,
        channel=ConversationMessage.Channel.EMAIL,
        content=content,
    )
    return msg


def add_internal_note(
    conversation: Conversation,
    content: str,
    *,
    sender_user=None,
) -> ConversationMessage:
    """Adiciona nota interna (não envia nada externamente, só registra)."""
    msg = ConversationMessage.objects.create(
        conversation=conversation,
        direction=ConversationMessage.Direction.SYSTEM,
        channel=ConversationMessage.Channel.INTERNAL_NOTE,
        content=content,
        sender_user=sender_user,
        delivery_status=ConversationMessage.DeliveryStatus.NA,
    )
    # Nota não conta como "mensagem do canal" → não atualiza unread_count
    # mas atualizamos last_message_at para reordenar a lista
    conversation.last_message_at = timezone.now()
    conversation.last_message_preview = f"📝 {content[:180]}"
    conversation.last_message_direction = ConversationMessage.Direction.SYSTEM
    conversation.last_message_channel = ConversationMessage.Channel.INTERNAL_NOTE
    conversation.save(update_fields=[
        "last_message_at", "last_message_preview",
        "last_message_direction", "last_message_channel", "updated_at",
    ])
    return msg


# ---------------------------------------------------------------------------
# Recepção (chamada pelos webhooks)
# ---------------------------------------------------------------------------


def record_inbound(
    *,
    empresa,
    lead,
    channel: str,
    content: str,
    sender_external_id: str = "",
    sender_name: str = "",
    payload: dict | None = None,
    chatbot_session=None,
    contato=None,
) -> tuple[Conversation, ConversationMessage]:
    """Helper único para chamadas vindas de webhooks (WhatsApp Evolution,
    futuramente e-mail IMAP, webchat público).

    Cria ou reusa a Conversation do (empresa, lead) e adiciona uma
    ConversationMessage inbound. Atualiza last_message snapshot.
    """
    conversation = get_or_create_conversation(empresa, lead, contato=contato)
    msg = ConversationMessage.objects.create(
        conversation=conversation,
        direction=ConversationMessage.Direction.INBOUND,
        channel=channel,
        content=content,
        payload=payload or {},
        sender_external_id=sender_external_id,
        sender_name=sender_name,
        triggered_by_chatbot_session=chatbot_session,
        delivery_status=ConversationMessage.DeliveryStatus.NA,
    )
    conversation.touch(
        direction=ConversationMessage.Direction.INBOUND,
        channel=channel,
        content=content,
    )
    # Se a conversa estava encerrada, reabre + registra nota interna
    # explícita (atendente vê na thread que cliente voltou).
    if conversation.status == Conversation.Status.CLOSED:
        conversation.status = Conversation.Status.OPEN
        conversation.save(update_fields=["status", "updated_at"])
        ConversationMessage.objects.create(
            conversation=conversation,
            direction=ConversationMessage.Direction.SYSTEM,
            channel=ConversationMessage.Channel.INTERNAL_NOTE,
            content="🔔 Conversa reaberta automaticamente — cliente enviou nova mensagem.",
            delivery_status=ConversationMessage.DeliveryStatus.NA,
            payload={"auto_reopen": True},
        )
    return conversation, msg


def record_bot_outbound(
    *,
    empresa,
    lead,
    channel: str,
    content: str,
    chatbot_session=None,
) -> ConversationMessage | None:
    """Registra mensagem que o BOT enviou (não foi o atendente humano).

    Aparece na thread como bolha de bot. Não usa SMTP nem Evolution: a
    mensagem já foi enviada pelo motor de execução do chatbot; aqui só
    persistimos o eco para o histórico unificado.
    """
    if not lead:
        return None
    conversation = get_or_create_conversation(empresa, lead)
    msg = ConversationMessage.objects.create(
        conversation=conversation,
        direction=ConversationMessage.Direction.OUTBOUND,
        channel=channel,
        content=content,
        triggered_by_chatbot_session=chatbot_session,
        delivery_status=ConversationMessage.DeliveryStatus.SENT,
        payload={"sent_by_bot": True},
    )
    conversation.touch(
        direction=ConversationMessage.Direction.OUTBOUND,
        channel=channel,
        content=f"🤖 {content}",
    )
    return msg


# ---------------------------------------------------------------------------
# Resolvedores de endereço por canal
# ---------------------------------------------------------------------------


def _resolve_phone(conversation: Conversation) -> str | None:
    """Procura telefone (E.164 sem +) do lead/contato da conversa."""
    if conversation.contato_id:
        return _normalize_phone(conversation.contato.whatsapp_or_phone or "")
    lead = conversation.lead
    if not lead:
        return None
    # Lead.contato é o caminho preferido
    contato = getattr(lead, "contato", None)
    if contato:
        return _normalize_phone(contato.whatsapp_or_phone or "")
    return _normalize_phone(getattr(lead, "phone", "") or "")


def _resolve_email(conversation: Conversation) -> str | None:
    if conversation.contato_id and conversation.contato.email:
        return conversation.contato.email
    lead = conversation.lead
    if not lead:
        return None
    contato = getattr(lead, "contato", None)
    if contato and contato.email:
        return contato.email
    return getattr(lead, "email", "") or None


def _normalize_phone(raw: str) -> str | None:
    """Remove tudo que não é dígito; retorna apenas o número (até 15 dígitos)."""
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if not digits or len(digits) > 15:
        return None
    return digits

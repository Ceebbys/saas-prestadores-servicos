"""
Adaptador para integração com Evolution API (WhatsApp gratuito).

Componentes:
- parse_evolution_webhook(): Parser do payload da Evolution API v2
- EvolutionAPIClient: Cliente HTTP para enviar mensagens de volta
- evolution_webhook_receive(): View que recebe webhooks por flow token
- evolution_webhook_auto(): View convenience para single-tenant
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ChatbotFlow, ChatbotSession, WhatsAppConfig
from .services import process_response, start_session

logger = logging.getLogger(__name__)

NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


# ---------------------------------------------------------------------------
# Parser do payload Evolution API v2
# ---------------------------------------------------------------------------

def parse_evolution_webhook(body: dict) -> tuple[str, str, str] | None:
    """Extrai sender_id, message_text e instance_name do payload da Evolution API.

    SÓ retorna para mensagens INBOUND (cliente → nós). Mensagens fromMe=true
    (operador responde direto pelo celular) são tratadas por
    `parse_evolution_webhook_outbound`.

    Returns:
        (sender_id, message_text, instance_name) ou None se não é mensagem
        processável (com log de motivo em DEBUG).
    """
    event = body.get("event", "")
    if event != "messages.upsert":
        logger.debug("evolution_webhook ignored: event=%r (esperado messages.upsert)", event)
        return None

    data = body.get("data", {})
    key = data.get("key", {})

    # Mensagens fromMe=true são tratadas por parse_evolution_webhook_outbound
    if key.get("fromMe", False):
        logger.debug("evolution_webhook ignored inbound: fromMe=True (usa parser outbound)")
        return None

    remote_jid = key.get("remoteJid", "") or ""
    if not remote_jid:
        logger.debug("evolution_webhook ignored: remoteJid vazio")
        return None

    _UNSUPPORTED_SUFFIXES = (
        "@g.us", "@broadcast", "@newsletter",
    )
    if any(remote_jid.endswith(sfx) for sfx in _UNSUPPORTED_SUFFIXES):
        logger.debug("evolution_webhook ignored: jid=%s (grupo/broadcast/channel)", remote_jid)
        return None

    sender_pn = (
        key.get("senderPn") or key.get("sender_pn")
        or data.get("senderPn") or data.get("sender_pn")
        or key.get("participantPn") or data.get("participantPn") or ""
    )

    if remote_jid.endswith("@lid"):
        if sender_pn and sender_pn.endswith("@s.whatsapp.net"):
            sender_id = sender_pn.replace("@s.whatsapp.net", "")
        else:
            logger.debug("evolution_webhook ignored: @lid sem senderPn (anônimo)")
            return None
    else:
        sender_id = remote_jid.replace("@s.whatsapp.net", "")

    if not sender_id or not sender_id.isdigit() or len(sender_id) > 15:
        logger.debug("evolution_webhook ignored: sender_id=%r inválido", sender_id)
        return None

    message = data.get("message", {})
    text = (
        message.get("conversation")
        or (message.get("extendedTextMessage", {}) or {}).get("text")
        or (message.get("buttonsResponseMessage", {}) or {}).get("selectedDisplayText")
        or (message.get("listResponseMessage", {}) or {})
        .get("singleSelectReply", {}).get("selectedRowId")
    )

    if not text:
        msg_types = list((message or {}).keys())
        logger.info(
            "evolution_webhook ignored: mensagem sem texto (tipos=%s, sender=%s)",
            msg_types[:5], sender_id,
        )
        return None

    instance_name = body.get("instance", "")
    logger.info(
        "evolution_webhook inbound: sender=%s text=%r instance=%s",
        sender_id, text[:60], instance_name,
    )
    return (sender_id, text.strip(), instance_name)


def parse_evolution_webhook_outbound(body: dict) -> tuple[str, str, str] | None:
    """Extrai dados de uma mensagem OUTBOUND (operador respondeu pelo celular).

    Estes eventos têm `fromMe=true` e devem ser registrados na inbox como
    `direction=outbound` SEM chamar o bot (evitar loop de envio).

    Returns:
        (recipient_id, message_text, instance_name) ou None.
    """
    event = body.get("event", "")
    if event != "messages.upsert":
        return None
    data = body.get("data", {})
    key = data.get("key", {})
    if not key.get("fromMe", False):
        return None

    remote_jid = key.get("remoteJid", "") or ""
    if not remote_jid:
        return None
    _UNSUPPORTED_SUFFIXES = ("@g.us", "@broadcast", "@newsletter")
    if any(remote_jid.endswith(sfx) for sfx in _UNSUPPORTED_SUFFIXES):
        return None

    # Quem é o destinatário (cliente)? Em fromMe=true, o remoteJid É o destinatário
    sender_pn = (
        key.get("senderPn") or key.get("sender_pn")
        or data.get("senderPn") or data.get("sender_pn") or ""
    )
    if remote_jid.endswith("@lid"):
        if sender_pn and sender_pn.endswith("@s.whatsapp.net"):
            recipient_id = sender_pn.replace("@s.whatsapp.net", "")
        else:
            return None
    else:
        recipient_id = remote_jid.replace("@s.whatsapp.net", "")
    if not recipient_id or not recipient_id.isdigit() or len(recipient_id) > 15:
        return None

    # Filtra mensagens que NÓS mesmos mandamos via Evolution API
    # (já registradas pelo `send_whatsapp` — evita duplicar).
    # Heurística: mensagens que vêm com `source="api"` na Evolution são nossas.
    source = (data.get("source") or "").lower()
    if source == "api":
        return None  # já registramos via send_whatsapp

    message = data.get("message", {})
    text = (
        message.get("conversation")
        or (message.get("extendedTextMessage", {}) or {}).get("text")
    )
    if not text:
        return None
    instance_name = body.get("instance", "")
    logger.info(
        "evolution_webhook outbound (mobile): recipient=%s text=%r",
        recipient_id, text[:60],
    )
    return (recipient_id, text.strip(), instance_name)


# ---------------------------------------------------------------------------
# Cliente HTTP para enviar mensagens via Evolution API
# ---------------------------------------------------------------------------

class EvolutionAPIClient:
    """Envia mensagens de volta ao WhatsApp via Evolution API REST."""

    def __init__(self, api_url=None, api_key=None, instance=None):
        self.api_url = (api_url or getattr(settings, "EVOLUTION_API_URL", "")).rstrip("/")
        self.api_key = api_key or getattr(settings, "EVOLUTION_API_KEY", "")
        self.instance = instance or getattr(settings, "EVOLUTION_INSTANCE_NAME", "")

    @property
    def configured(self) -> bool:
        return bool(self.api_url and self.api_key and self.instance)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "apikey": self.api_key,
        }

    def send_text(self, phone: str, text: str) -> bool:
        """Envia mensagem de texto simples."""
        if not self.configured:
            logger.debug("Evolution API not configured, skipping send_text")
            return False

        try:
            import httpx

            url = f"{self.api_url}/message/sendText/{self.instance}"
            resp = httpx.post(
                url,
                headers=self._headers(),
                json={"number": phone, "text": text},
                timeout=10.0,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Evolution API send_text failed: %s %s",
                    resp.status_code, resp.text[:200],
                )
                return False
            return True
        except Exception:
            logger.exception("Error sending text via Evolution API")
            return False

    def send_buttons(self, phone: str, text: str, buttons: list[str]) -> bool:
        """Envia mensagem com botões interativos (máximo 3 botões no WhatsApp)."""
        if not self.configured:
            return False

        # WhatsApp limita a 3 botões — fallback para texto numerado
        if len(buttons) > 3:
            formatted = self._format_choices_as_text(text, buttons)
            return self.send_text(phone, formatted)

        try:
            import httpx

            url = f"{self.api_url}/message/sendButtons/{self.instance}"
            payload = {
                "number": phone,
                "title": "",
                "description": text,
                "buttons": [
                    {"buttonId": str(i), "buttonText": {"displayText": btn}}
                    for i, btn in enumerate(buttons)
                ],
            }
            resp = httpx.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=10.0,
            )
            if resp.status_code >= 400:
                # Fallback para texto se botões não são suportados
                logger.info("Buttons not supported, falling back to text")
                formatted = self._format_choices_as_text(text, buttons)
                return self.send_text(phone, formatted)
            return True
        except Exception:
            logger.exception("Error sending buttons via Evolution API")
            # Fallback para texto
            formatted = self._format_choices_as_text(text, buttons)
            return self.send_text(phone, formatted)

    def _format_choices_as_text(self, text: str, choices: list[str]) -> str:
        """Formata choices como texto numerado (fallback quando botões não funcionam)."""
        lines = [text, ""]
        for i, choice in enumerate(choices):
            emoji = NUMBER_EMOJIS[i] if i < len(NUMBER_EMOJIS) else f"{i + 1}."
            lines.append(f"{emoji} {choice}")
        lines.append("")
        lines.append("_Responda com o número da opção (1, 2, 3…) ou o texto._")
        return "\n".join(lines)

    def send_media(
        self,
        phone: str,
        base64_content: str,
        filename: str,
        caption: str = "",
        mime_type: str = "application/pdf",
    ) -> tuple[bool, str]:
        """Envia mídia (PDF, imagem, etc.) via Evolution API.

        Returns:
            (success, error_message). error_message é "" em caso de sucesso.
        """
        if not self.configured:
            return False, "Evolution API não configurada para esta empresa."

        try:
            import httpx

            url = f"{self.api_url}/message/sendMedia/{self.instance}"
            payload = {
                "number": phone,
                "mediatype": "document",
                "mimetype": mime_type,
                "media": base64_content,
                "fileName": filename,
            }
            if caption:
                payload["caption"] = caption
            resp = httpx.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=30.0,
            )
            if resp.status_code >= 400:
                msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning("Evolution API send_media failed: %s", msg)
                return False, msg
            return True, ""
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error sending media via Evolution API")
            return False, str(exc)


# ---------------------------------------------------------------------------
# Views do webhook Evolution API
# ---------------------------------------------------------------------------

def _process_evolution_message(flow, sender_id, message_text):
    """Lógica compartilhada: processa mensagem e retorna (reply_text, choices, is_complete, lead_id).

    Side-effect: registra inbound + outbound em `apps.communications`
    quando há lead associado (humano vê na inbox unificada).
    """
    # Buscar sessão ativa para este sender
    session = ChatbotSession.objects.filter(
        flow=flow, sender_id=sender_id, status=ChatbotSession.Status.ACTIVE,
    ).first()

    if not session:
        # Iniciar nova sessão
        result = start_session(flow, channel="whatsapp", sender_id=sender_id)
        reply = result["welcome_message"]
        choices = []
        if result.get("step"):
            reply += "\n\n" + result["step"]["question"]
            choices = result["step"].get("choices", [])
        # Busca a sessão recém-criada para passar ao mirror (permite criar
        # Lead lazy vinculado à session — primeira msg do cliente NÃO some).
        new_session = ChatbotSession.objects.filter(
            flow=flow, sender_id=sender_id, status=ChatbotSession.Status.ACTIVE,
        ).order_by("-created_at").first()
        _mirror_to_inbox(flow, sender_id, message_text, reply, session=new_session)
        return reply, choices, False, None

    # Processar resposta na sessão existente
    if not message_text:
        reply = session.current_step.question_text if session.current_step else ""
        return reply, [], False, None

    result = process_response(str(session.session_key), message_text)

    if result.get("error"):
        choices = result["step"]["choices"] if result.get("step") else []
        _mirror_to_inbox(flow, sender_id, message_text, result["message"], session=session)
        return result["message"], choices, False, None

    if result.get("is_complete"):
        _mirror_to_inbox(
            flow, sender_id, message_text, result["message"], session=session,
            lead_id=result.get("lead_id"),
        )
        return result["message"], [], True, result.get("lead_id")

    if result.get("step"):
        reply = result["step"]["question"]
        _mirror_to_inbox(flow, sender_id, message_text, reply, session=session)
        return reply, result["step"].get("choices", []), False, None

    return "", [], False, None


def _resolve_or_create_lead_lazy(flow, sender_id, session=None, lead_id=None):
    """Resolve o Lead da conversa WhatsApp, criando lazily se necessário.

    Ordem de resolução:
        1. `session.lead` se já existe
        2. `lead_id` explícito (vem ao final do fluxo)
        3. Lead existente com `phone=sender_id` no mesmo tenant (re-engajamento)
        4. Cria novo Lead "shell" com phone + source=WHATSAPP
           - `external_ref=session.session_key` para idempotência com
             `_create_lead_action` quando o fluxo terminar
           - `name="WhatsApp <phone>"` placeholder (atualizado quando bot
             coletar o nome via `create_lead_from_chatbot`)

    Retorna o `Lead` (nunca None) ou None se algum guard falhar (cross-tenant,
    flow sem empresa, etc.).
    """
    from apps.crm.models import Lead

    # (1) Lead vinculado à session
    if session is not None and session.lead_id:
        lead = session.lead
        if lead.empresa_id != flow.empresa_id:
            logger.error(
                "_mirror_to_inbox: cross-tenant block (lead.empresa=%s, flow.empresa=%s)",
                lead.empresa_id, flow.empresa_id,
            )
            return None
        return lead

    # (2) Lead explícito (ao final do fluxo)
    if lead_id:
        try:
            lead = Lead.objects.get(pk=lead_id, empresa=flow.empresa)
            return lead
        except Lead.DoesNotExist:
            logger.warning(
                "_mirror_to_inbox: lead_id=%s não encontrado em empresa=%s",
                lead_id, flow.empresa_id,
            )

    # (3) Lead pré-existente pelo telefone (mesmo cliente voltando)
    phone_digits = "".join(c for c in (sender_id or "") if c.isdigit())
    if phone_digits:
        existing = (
            Lead.objects
            .filter(empresa=flow.empresa, phone__contains=phone_digits)
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            # Vincula à session (próximo turno reusa)
            if session is not None and not session.lead_id:
                session.lead = existing
                try:
                    session.save(update_fields=["lead", "updated_at"])
                except Exception:  # noqa: BLE001
                    logger.exception("falha ao vincular session.lead reused")
            return existing

    # (4) Cria Lead lazy — placeholder até o bot coletar nome/email
    if not phone_digits:
        logger.warning(
            "_mirror_to_inbox: sender_id sem dígitos — não cria lead "
            "(sender=%r flow=%s)",
            sender_id, flow.pk,
        )
        return None

    try:
        # IMPORTANTE: external_ref deve casar com o que _create_lead_action
        # usará no FIM do fluxo (apps/chatbot/services.py::_create_lead_action
        # passa session_data["session_id"] = str(session.session_key) e
        # create_lead_from_chatbot usa esse session_id como external_ref).
        # Assim o lead criado aqui é o MESMO que será hidratado depois.
        external_ref = (
            str(session.session_key)
            if session is not None and session.session_key
            else f"whatsapp:{flow.pk}:{phone_digits}"
        )
        # Idempotência se já existe via session
        existing_by_ref = Lead.objects.filter(
            empresa=flow.empresa, external_ref=external_ref,
        ).first()
        if existing_by_ref:
            new_lead = existing_by_ref
        else:
            new_lead = Lead.objects.create(
                empresa=flow.empresa,
                name=f"WhatsApp {phone_digits}",
                phone=phone_digits,
                source=Lead.Source.WHATSAPP,
                external_ref=external_ref,
                notes="Lead criado automaticamente ao receber primeira mensagem.",
            )
            logger.info(
                "_mirror_to_inbox: lead lazy criado pk=%s sender=%s",
                new_lead.pk, phone_digits,
            )
        # Vincula à session
        if session is not None and not session.lead_id:
            session.lead = new_lead
            try:
                session.save(update_fields=["lead", "updated_at"])
            except Exception:  # noqa: BLE001
                logger.exception("falha ao vincular session.lead após criar lazy")
        return new_lead
    except Exception:  # noqa: BLE001
        logger.exception(
            "_mirror_to_inbox: falha criando lead lazy (sender=%s, flow=%s)",
            sender_id, flow.pk,
        )
        return None


def _mirror_to_inbox(flow, sender_id, inbound_text, outbound_text, *, session=None, lead_id=None):
    """Replica inbound + outbound do bot na inbox unificada de Communications.

    Cria Lead lazily se necessário — assim mensagens NÃO são perdidas nos
    primeiros turnos antes do bot coletar nome/email. O `_create_lead_action`
    no fim do fluxo reusa o Lead lazy via `external_ref` e hidrata os campos.

    Best-effort: erros aqui NÃO derrubam o fluxo principal (apenas log).
    """
    from apps.communications.services import record_bot_outbound, record_inbound

    lead = _resolve_or_create_lead_lazy(
        flow, sender_id, session=session, lead_id=lead_id,
    )
    if lead is None:
        # Já foi logado em _resolve_or_create_lead_lazy
        return

    try:
        # Inbound do cliente
        record_inbound(
            empresa=flow.empresa,
            lead=lead,
            channel="whatsapp",
            content=inbound_text,
            sender_external_id=sender_id,
            chatbot_session=session,
        )
        # Outbound do bot
        if outbound_text:
            record_bot_outbound(
                empresa=flow.empresa,
                lead=lead,
                channel="whatsapp",
                content=outbound_text,
                chatbot_session=session,
            )
    except Exception:
        logger.exception("Erro ao replicar mensagem WhatsApp na inbox de comunicações")


def _mirror_outbound_from_mobile(empresa, recipient_id, text):
    """Espelha mensagem outbound enviada pelo OPERADOR direto do celular.

    Quando o atendente responde diretamente pelo app WhatsApp do celular
    (fromMe=true, source != 'api'), queremos registrar na inbox como
    `direction=outbound` para o histórico ficar completo. NÃO chama o
    bot (evita loop) e NÃO usa o flow — só registra na conversação do
    lead correspondente.

    Resolve o Lead por phone match. Se não encontrar, cria Lead lazy
    (cliente novo a quem o operador escreveu primeiro).
    """
    from apps.communications.models import (
        Conversation, ConversationMessage, get_or_create_conversation,
    )
    from apps.crm.models import Lead

    phone_digits = "".join(c for c in (recipient_id or "") if c.isdigit())
    if not phone_digits:
        logger.warning("_mirror_outbound_from_mobile: recipient sem dígitos %r", recipient_id)
        return

    # Procura Lead existente por phone no mesmo tenant
    lead = (
        Lead.objects
        .filter(empresa=empresa, phone__contains=phone_digits)
        .order_by("-created_at")
        .first()
    )
    if lead is None:
        # Operador iniciou conversa nova → cria Lead lazy
        try:
            lead = Lead.objects.create(
                empresa=empresa,
                name=f"WhatsApp {phone_digits}",
                phone=phone_digits,
                source=Lead.Source.WHATSAPP,
                external_ref=f"mobile:{empresa.pk}:{phone_digits}",
                notes="Lead criado quando operador iniciou conversa via celular.",
            )
            logger.info(
                "_mirror_outbound_from_mobile: lead lazy criado pk=%s recipient=%s",
                lead.pk, phone_digits,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "_mirror_outbound_from_mobile: falha criando lead lazy"
            )
            return

    try:
        conv = get_or_create_conversation(empresa, lead)
        ConversationMessage.objects.create(
            conversation=conv,
            direction=ConversationMessage.Direction.OUTBOUND,
            channel=ConversationMessage.Channel.WHATSAPP,
            content=text,
            sender_external_id="",
            sender_name="",
            payload={"source": "mobile_app"},  # marca origem
            delivery_status=ConversationMessage.DeliveryStatus.SENT,
        )
        # Atualiza last_message snapshot
        conv.touch(
            direction=ConversationMessage.Direction.OUTBOUND,
            channel=ConversationMessage.Channel.WHATSAPP,
            content=text,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "_mirror_outbound_from_mobile: falha ao gravar mensagem"
        )


def _send_reply(client, phone, reply_text, choices):
    """Envia resposta via Evolution API com botões ou texto."""
    if not reply_text:
        return

    if choices and len(choices) <= 3:
        client.send_buttons(phone, reply_text, choices)
    elif choices:
        formatted = client._format_choices_as_text(reply_text, choices)
        client.send_text(phone, formatted)
    else:
        client.send_text(phone, reply_text)


@csrf_exempt
@require_POST
def evolution_webhook_receive(request, token):
    """Webhook da Evolution API para um fluxo específico (por token UUID)."""
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Validar token de segurança (opcional)
    webhook_token = getattr(settings, "EVOLUTION_WEBHOOK_TOKEN", "")
    if webhook_token:
        header_token = request.headers.get("X-Webhook-Token", "")
        if header_token and header_token != webhook_token:
            return JsonResponse({"error": "Invalid webhook token"}, status=403)

    # 1) Tenta como mensagem INBOUND (cliente → nós)
    parsed = parse_evolution_webhook(body)

    # 2) Se não é inbound, tenta como OUTBOUND (operador respondeu pelo celular)
    if not parsed:
        outbound = parse_evolution_webhook_outbound(body)
        if outbound:
            recipient_id, message_text, _ = outbound
            flow = ChatbotFlow.objects.filter(
                webhook_token=token, is_active=True,
            ).select_related("empresa").first()
            if flow:
                _mirror_outbound_from_mobile(flow.empresa, recipient_id, message_text)
            return JsonResponse({"status": "ok", "mirror": "outbound_mobile"})
        return JsonResponse({"status": "ignored"})

    sender_id, message_text, instance_name = parsed

    # Buscar flow por token
    flow = ChatbotFlow.objects.filter(
        webhook_token=token, is_active=True,
    ).first()
    if not flow:
        return JsonResponse({"error": "Flow not found or inactive"}, status=404)

    try:
        reply_text, choices, is_complete, lead_id = _process_evolution_message(
            flow, sender_id, message_text,
        )
    except ValueError as e:
        logger.warning("Evolution webhook error: %s", e)
        return JsonResponse({"status": "error", "message": str(e)})

    # Enviar resposta via Evolution API
    client = EvolutionAPIClient()
    _send_reply(client, sender_id, reply_text, choices)

    return JsonResponse({
        "status": "ok",
        "reply": reply_text,
        "is_complete": is_complete,
        "lead_id": lead_id,
    })


@csrf_exempt
@require_POST
def evolution_webhook_auto(request):
    """Webhook da Evolution API — auto-detecta o fluxo WhatsApp ativo.

    Convenience para setups single-tenant com um único número WhatsApp.
    """
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Validar token de segurança (opcional)
    webhook_token = getattr(settings, "EVOLUTION_WEBHOOK_TOKEN", "")
    if webhook_token:
        header_token = request.headers.get("X-Webhook-Token", "")
        if header_token and header_token != webhook_token:
            return JsonResponse({"error": "Invalid webhook token"}, status=403)

    # 1) Tenta INBOUND
    parsed = parse_evolution_webhook(body)

    # 2) Tenta OUTBOUND (operador respondeu pelo celular)
    if not parsed:
        outbound = parse_evolution_webhook_outbound(body)
        if outbound:
            recipient_id, message_text, instance_name = outbound
            config = WhatsAppConfig.objects.select_related("empresa").filter(
                instance_name=instance_name,
            ).first()
            if config:
                _mirror_outbound_from_mobile(config.empresa, recipient_id, message_text)
            return JsonResponse({"status": "ok", "mirror": "outbound_mobile"})
        return JsonResponse({"status": "ignored"})

    sender_id, message_text, instance_name = parsed

    # Multi-tenant: rotear pelo instance_name da Evolution API
    config = WhatsAppConfig.objects.select_related("empresa").filter(
        instance_name=instance_name,
    ).first()
    if not config:
        return JsonResponse({"error": "No WhatsApp config for this instance"}, status=404)

    # Selecionar o fluxo elegível usando o engine centralizado.
    # Se houver sessão ativa exclusiva, retorna None e processamos como
    # continuação da sessão atual (sem disparar fluxo novo).
    from .services import select_flow_for_message

    flow = select_flow_for_message(
        empresa=config.empresa,
        sender_id=sender_id,
        message=message_text,
        channel="whatsapp",
    )

    # Continuação de sessão ativa: identifica o fluxo da sessão em andamento.
    if not flow:
        active = ChatbotSession.objects.filter(
            flow__empresa=config.empresa,
            sender_id=sender_id,
            status=ChatbotSession.Status.ACTIVE,
        ).select_related("flow").first()
        if active:
            flow = active.flow

    if not flow:
        return JsonResponse({"error": "No eligible WhatsApp flow"}, status=404)

    try:
        reply_text, choices, is_complete, lead_id = _process_evolution_message(
            flow, sender_id, message_text,
        )
    except ValueError as e:
        logger.warning("Evolution webhook auto error: %s", e)
        return JsonResponse({"status": "error", "message": str(e)})

    client = EvolutionAPIClient(
        api_url=config.effective_api_url,
        api_key=config.effective_instance_key,  # token específico da instância
        instance=config.instance_name,
    )
    _send_reply(client, sender_id, reply_text, choices)

    return JsonResponse({
        "status": "ok",
        "reply": reply_text,
        "is_complete": is_complete,
        "lead_id": lead_id,
    })

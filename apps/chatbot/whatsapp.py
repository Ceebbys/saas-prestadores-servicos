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

    Returns:
        (sender_id, message_text, instance_name) ou None se não é mensagem processável
    """
    event = body.get("event", "")
    if event != "messages.upsert":
        return None

    data = body.get("data", {})
    key = data.get("key", {})

    # Ignorar mensagens enviadas por nós (evita loop)
    if key.get("fromMe", False):
        return None

    remote_jid = key.get("remoteJid", "") or ""
    if not remote_jid:
        return None

    # Rejeita grupos, broadcasts, canais — a Evolution API não consegue
    # enviar reply individual para esses e o fluxo não faz sentido em grupo.
    _UNSUPPORTED_SUFFIXES = (
        "@g.us",           # grupos
        "@broadcast",      # listas de transmissão e status@broadcast
        "@newsletter",     # canais
    )
    if any(remote_jid.endswith(sfx) for sfx in _UNSUPPORTED_SUFFIXES):
        return None

    # WhatsApp 2024+ usa "addressing_mode=lid": o remoteJid vem como
    # "<hash>@lid" (identidade anônima) e o número real chega em `senderPn`
    # (ou variações: sender_pn, participantPn). Precisamos do número real
    # para poder responder via Evolution (ela resolve @s.whatsapp.net).
    sender_pn = (
        key.get("senderPn")
        or key.get("sender_pn")
        or data.get("senderPn")
        or data.get("sender_pn")
        or key.get("participantPn")
        or data.get("participantPn")
        or ""
    )

    if remote_jid.endswith("@lid"):
        # @lid puro sem sender_pn = contato verdadeiramente anônimo
        # (canal, story) — ignorar. Com sender_pn resolvido, processar.
        if sender_pn and sender_pn.endswith("@s.whatsapp.net"):
            sender_id = sender_pn.replace("@s.whatsapp.net", "")
        else:
            return None
    else:
        sender_id = remote_jid.replace("@s.whatsapp.net", "")

    # Precisa sobrar só dígitos e caber no tamanho de um telefone E.164
    # (max 15 dígitos). IDs de grupo/canal novos vêm com 18 dígitos sem
    # sufixo e seriam aceitos pelo isdigit — filtramos por comprimento.
    if not sender_id or not sender_id.isdigit() or len(sender_id) > 15:
        return None

    # Extrair texto da mensagem (múltiplos formatos possíveis)
    message = data.get("message", {})
    text = (
        message.get("conversation")
        or (message.get("extendedTextMessage", {}) or {}).get("text")
        or (message.get("buttonsResponseMessage", {}) or {}).get("selectedDisplayText")
        or (message.get("listResponseMessage", {}) or {})
        .get("singleSelectReply", {}).get("selectedRowId")
    )

    if not text:
        return None

    instance_name = body.get("instance", "")

    return (sender_id, text.strip(), instance_name)


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
        lines.append("_Responda com o texto da opção desejada._")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Views do webhook Evolution API
# ---------------------------------------------------------------------------

def _process_evolution_message(flow, sender_id, message_text):
    """Lógica compartilhada: processa mensagem e retorna (reply_text, choices, is_complete, lead_id)."""
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
        return reply, choices, False, None

    # Processar resposta na sessão existente
    if not message_text:
        reply = session.current_step.question_text if session.current_step else ""
        return reply, [], False, None

    result = process_response(str(session.session_key), message_text)

    if result.get("error"):
        choices = result["step"]["choices"] if result.get("step") else []
        return result["message"], choices, False, None

    if result.get("is_complete"):
        return result["message"], [], True, result.get("lead_id")

    if result.get("step"):
        return result["step"]["question"], result["step"].get("choices", []), False, None

    return "", [], False, None


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

    # Parser do payload
    parsed = parse_evolution_webhook(body)
    if not parsed:
        # Não é mensagem processável (status update, fromMe, etc.) — OK silencioso
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

    parsed = parse_evolution_webhook(body)
    if not parsed:
        return JsonResponse({"status": "ignored"})

    sender_id, message_text, instance_name = parsed

    # Multi-tenant: rotear pelo instance_name da Evolution API
    config = WhatsAppConfig.objects.select_related("empresa").filter(
        instance_name=instance_name,
    ).first()
    if not config:
        return JsonResponse({"error": "No WhatsApp config for this instance"}, status=404)

    flow = ChatbotFlow.objects.filter(
        empresa=config.empresa, channel="whatsapp", is_active=True,
    ).first()
    if not flow:
        return JsonResponse({"error": "No active WhatsApp flow for this empresa"}, status=404)

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

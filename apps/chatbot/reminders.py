"""RV06 — Service que processa lembretes de sessões idle.

Pedido do usuário: 'em todos os campos temos q ter aquela opção de marcar
o tempo de resposta fraga. tipo se o cara demora mais q 30 min pra
continuasr manda uma msg vc está ai e retoma o fluxo. Se passa disso
o fluxo começa de novo caso ele mande uma msg'.

Cada bloco de input (question/menu/collect_data/yes_no) pode ter:
- reminder_minutes: quanto tempo aguardar antes de mandar lembrete
- reminder_message: texto do lembrete

Este service:
1. Roda periodicamente (via management command + cron)
2. Busca sessões ACTIVE cujo current_node tem reminder configurado
3. Para sessões idle (now - last_activity > reminder_minutes)
   E que ainda não receberam lembrete neste nó (reminder_sent_at IS NULL),
   envia o lembrete via canal apropriado
4. Marca reminder_sent_at para evitar duplicar

O reset total da sessão (flow.session_timeout_minutes) é tratado em
_process_evolution_message ao receber próxima mensagem.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from apps.chatbot.models import ChatbotSession

logger = logging.getLogger(__name__)


def send_idle_reminders() -> dict:
    """Processa todas as sessões idle elegíveis e envia lembretes.

    Returns:
        {'checked': N, 'sent': M, 'skipped': K, 'errors': E}
    """
    stats = {"checked": 0, "sent": 0, "skipped": 0, "errors": 0}
    now = timezone.now()

    # Apenas sessões ATIVAS, sem reminder enviado pro nó atual,
    # com pelo menos algum movimento (last_activity_at preenchido).
    qs = (
        ChatbotSession.objects
        .select_related("flow", "lead", "lead__contato")
        .filter(
            status=ChatbotSession.Status.ACTIVE,
            last_activity_at__isnull=False,
            reminder_sent_at__isnull=True,
        )
    )

    for session in qs:
        stats["checked"] += 1
        try:
            if _process_session_reminder(session, now):
                stats["sent"] += 1
            else:
                stats["skipped"] += 1
        except Exception:  # noqa: BLE001
            stats["errors"] += 1
            logger.exception(
                "send_idle_reminders: erro processando session=%s",
                session.session_key,
            )
    return stats


def _to_minutes(value, unit: str) -> int:
    """RV07 — converte (valor, unit) → minutos. unit in {minutes, hours}."""
    try:
        v = int(value or 0)
    except (TypeError, ValueError):
        return 0
    if v <= 0:
        return 0
    return v * 60 if (unit or "").lower() == "hours" else v


def _resolve_reminder_config(data: dict, flow) -> dict:
    """RV07 — resolve config de reminder do nó com fallback do flow.

    Retorna dict com:
    - enabled: bool — ativo?
    - reminder_minutes: int — threshold em minutos
    - max_inactivity_minutes: int — timeout total (0 = sem limite no bloco;
      cai no flow.session_timeout_minutes)
    - auto_end_on_timeout: bool — encerra (COMPLETED) ou reseta (EXPIRED)
    - message: str — mensagem do lembrete
    - on_return_behavior: str — 'continue' | 'restart' | '' (usa flow)
    """
    # Compat: campo antigo reminder_minutes (criado em RV06, sem enable explicit)
    legacy_minutes = data.get("reminder_minutes")
    has_legacy = legacy_minutes is not None and int(legacy_minutes or 0) > 0

    # enable_reminder explicit (novo); fallback no campo antigo
    enabled = data.get("enable_reminder")
    if enabled is None:
        enabled = has_legacy
    enabled = bool(enabled)

    # reminder_value + unit (novo); fallback legacy_minutes
    rem_value = data.get("reminder_value")
    rem_unit = data.get("reminder_unit") or "minutes"
    if rem_value is None and has_legacy:
        reminder_minutes = int(legacy_minutes)
    else:
        reminder_minutes = _to_minutes(rem_value or 0, rem_unit)

    # max_inactivity (por bloco) com fallback no flow
    max_inact_value = data.get("max_inactivity_value", 0)
    max_inact_unit = data.get("max_inactivity_unit") or "minutes"
    max_inactivity_minutes = _to_minutes(max_inact_value, max_inact_unit)
    if max_inactivity_minutes <= 0:
        max_inactivity_minutes = (
            getattr(flow, "session_timeout_minutes", 0) or 0
        )

    auto_end = data.get("auto_end_on_timeout")
    if auto_end is None:
        auto_end = getattr(flow, "default_auto_end_on_timeout", False)
    auto_end = bool(auto_end)

    message = (data.get("reminder_message") or "").strip()
    if not message:
        message = "Você ainda está aí? Me responde quando puder 👋"

    on_return = (data.get("on_return_behavior") or "").strip()

    return {
        "enabled": enabled,
        "reminder_minutes": reminder_minutes,
        "max_inactivity_minutes": max_inactivity_minutes,
        "auto_end_on_timeout": auto_end,
        "message": message,
        "on_return_behavior": on_return,
    }


def _process_session_reminder(session: ChatbotSession, now) -> bool:
    """Avalia se a session deve receber reminder agora. Returns True se enviou."""
    # Resolve o nó atual no graph publicado (motor v2) ou current_step (legacy)
    node = _current_node(session)
    if node is None:
        return False
    data = node.get("data") or {}
    cfg = _resolve_reminder_config(data, session.flow)

    if not cfg["enabled"] or cfg["reminder_minutes"] <= 0:
        return False

    elapsed = now - session.last_activity_at
    if elapsed < timedelta(minutes=cfg["reminder_minutes"]):
        return False  # ainda dentro da janela, não precisa lembrete

    # Se já passou do tempo máximo, NÃO envia lembrete (fluxo morto
    # — a próxima msg do cliente reseta no _process_evolution_message,
    # ou auto_end_on_timeout encerra silenciosamente).
    max_inact = cfg["max_inactivity_minutes"]
    if max_inact > 0 and elapsed >= timedelta(minutes=max_inact):
        return False

    sent = _send_reminder_via_channel(session, cfg["message"])
    if sent:
        session.reminder_sent_at = now
        session.save(update_fields=["reminder_sent_at", "updated_at"])
        logger.info(
            "reminder enviado: session=%s node=%s elapsed=%s",
            session.session_key, node.get("id"), elapsed,
        )
        return True
    return False


def _current_node(session: ChatbotSession) -> dict | None:
    """Retorna o dict do node atual no graph publicado da sessão."""
    if not session.current_node_id:
        return None
    flow = session.flow
    published = flow.current_published_version
    if not published or not published.graph_json:
        return None
    nodes = published.graph_json.get("nodes") or []
    for n in nodes:
        if n.get("id") == session.current_node_id:
            return n
    return None


def _send_reminder_via_channel(session: ChatbotSession, message: str) -> bool:
    """Envia o lembrete via canal apropriado da sessão. Returns True se OK."""
    channel = (session.channel or "").lower()
    if channel == "whatsapp":
        return _send_whatsapp_reminder(session, message)
    # Webchat/outros: registra mensagem no histórico, mas não há canal
    # outbound automático ativo — fica para futuras integrações.
    logger.info(
        "reminder skipped: canal '%s' sem outbound automático (session=%s)",
        channel, session.session_key,
    )
    return False


def _send_whatsapp_reminder(session: ChatbotSession, message: str) -> bool:
    """Envia lembrete via Evolution API + registra na inbox."""
    from apps.chatbot.models import WhatsAppConfig
    from apps.chatbot.whatsapp import EvolutionAPIClient

    config = WhatsAppConfig.objects.filter(empresa=session.flow.empresa).first()
    if not config:
        return False
    client = EvolutionAPIClient(
        api_url=config.effective_api_url,
        api_key=config.effective_instance_key,
        instance=config.instance_name,
    )
    if not client.configured:
        return False

    phone = "".join(c for c in (session.sender_id or "") if c.isdigit())
    if not phone:
        return False

    try:
        ok = client.send_text(phone, message)
    except Exception:  # noqa: BLE001
        logger.exception(
            "reminder: erro ao enviar WhatsApp session=%s phone=%s",
            session.session_key, phone,
        )
        return False
    if not ok:
        return False

    # Registra na inbox como bot outbound (humano vê na thread)
    try:
        from apps.communications.services import record_bot_outbound
        if session.lead_id:
            record_bot_outbound(
                empresa=session.flow.empresa, lead=session.lead,
                channel="whatsapp", content=message,
                chatbot_session=session,
            )
    except Exception:  # noqa: BLE001
        logger.exception("reminder: falha gravando outbound na inbox")
    return True

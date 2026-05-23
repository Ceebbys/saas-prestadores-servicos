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


def _process_session_reminder(session: ChatbotSession, now) -> bool:
    """Avalia se a session deve receber reminder agora. Returns True se enviou."""
    # Resolve o nó atual no graph publicado (motor v2) ou current_step (legacy)
    node = _current_node(session)
    if node is None:
        return False
    data = node.get("data") or {}
    reminder_minutes = data.get("reminder_minutes")
    try:
        reminder_minutes = int(reminder_minutes or 0)
    except (TypeError, ValueError):
        return False
    if reminder_minutes <= 0:
        return False

    elapsed = now - session.last_activity_at
    if elapsed < timedelta(minutes=reminder_minutes):
        return False  # ainda dentro da janela, não precisa lembrete

    # Verifica também o session_timeout — se já passou do total, NÃO envia
    # lembrete (a próxima msg do cliente vai resetar o fluxo no
    # _process_evolution_message). Evita lembrete de sessão "morta".
    flow_timeout = getattr(session.flow, "session_timeout_minutes", 0) or 0
    if flow_timeout > 0 and elapsed >= timedelta(minutes=flow_timeout):
        return False

    message = (data.get("reminder_message") or "").strip()
    if not message:
        message = "Você ainda está aí? Me responde quando puder 👋"

    sent = _send_reminder_via_channel(session, message)
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

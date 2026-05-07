"""
Serviços do módulo de chatbot.

Processamento real de mensagens com sessões persistentes,
validação de input por tipo, e execução de ações ao completar.
A criação de leads é delegada para apps.automation.services.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.validators import (
    mask_document,
    normalize_document,
    validate_cpf_or_cnpj,
)

from .models import (
    ChatbotAction,
    ChatbotChoice,
    ChatbotFlow,
    ChatbotFlowDispatch,
    ChatbotSession,
    ChatbotStep,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialização
# ---------------------------------------------------------------------------

def _serialize_step(step: ChatbotStep) -> dict:
    """Serializa um ChatbotStep para resposta JSON."""
    choices = []
    if step.step_type == ChatbotStep.StepType.CHOICE:
        choices = list(
            step.choices.order_by("order").values_list("text", flat=True)
        )
    return {
        "id": step.pk,
        "question": step.question_text,
        "type": step.step_type,
        "required": step.is_required,
        "field_mapping": step.lead_field_mapping,
        "choices": choices,
    }


# ---------------------------------------------------------------------------
# Validação de input por tipo de step
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"[\d\s()\-+]{7,20}")
NUMBER_PREFIX_RE = re.compile(r"^(\d+)[\.\)]")
NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def _resolve_choice(step: ChatbotStep, user_response: str) -> ChatbotChoice | None:
    """Resolve qual ChatbotChoice o usuário selecionou.

    Aceita: número (1-indexed), emoji numérico (1️⃣), número com pontuação (1. / 1)),
    texto literal (case-insensitive) ou prefixo do texto (>=3 caracteres).
    """
    text = user_response.strip()
    if not text:
        return None

    choices = list(step.choices.order_by("order"))
    if not choices:
        return None

    digit = None
    if text.isdigit():
        digit = int(text)
    else:
        for i, emoji in enumerate(NUMBER_EMOJIS, start=1):
            if text.startswith(emoji):
                digit = i
                break
        if digit is None:
            m = NUMBER_PREFIX_RE.match(text)
            if m:
                digit = int(m.group(1))

    if digit is not None and 1 <= digit <= len(choices):
        return choices[digit - 1]

    low = text.lower()
    for c in choices:
        if c.text.lower() == low:
            return c

    if len(low) >= 3:
        for c in choices:
            if c.text.lower().startswith(low):
                return c

    return None


def _validate_response(step: ChatbotStep, user_response: str) -> str | None:
    """Valida a resposta do usuário. Retorna mensagem de erro ou None se válido."""
    text = user_response.strip()

    if not text:
        if step.is_required:
            return "Por favor, responda à pergunta."
        return None

    if step.step_type == ChatbotStep.StepType.EMAIL:
        if not EMAIL_RE.match(text):
            return "Por favor, informe um e-mail válido (ex: nome@email.com)."

    elif step.step_type == ChatbotStep.StepType.PHONE:
        if not PHONE_RE.fullmatch(text):
            return "Por favor, informe um telefone válido (ex: (11) 99999-0000)."

    elif step.step_type in (ChatbotStep.StepType.NAME, ChatbotStep.StepType.COMPANY):
        if len(text) < 2:
            return "Por favor, informe pelo menos 2 caracteres."

    elif step.step_type == ChatbotStep.StepType.CHOICE:
        if _resolve_choice(step, user_response) is None:
            options = ", ".join(step.choices.order_by("order").values_list("text", flat=True))
            return f"Por favor, escolha uma das opções: {options}."

    elif step.step_type == ChatbotStep.StepType.DOCUMENT:
        from django.core.exceptions import ValidationError
        try:
            validate_cpf_or_cnpj(text)
        except ValidationError as exc:
            return str(exc.messages[0]) if getattr(exc, "messages", None) else "Documento inválido."

    return None


# ---------------------------------------------------------------------------
# Início de sessão
# ---------------------------------------------------------------------------

def start_session(
    flow: ChatbotFlow,
    channel: str = "webchat",
    sender_id: str = "",
) -> dict:
    """Inicia uma nova sessão de chatbot.

    Args:
        flow: ChatbotFlow ativo
        channel: Canal de origem (webchat, whatsapp, simulator, etc.)
        sender_id: Identificador do remetente (telefone, etc.)

    Returns:
        dict com session_key, flow_name, welcome_message, step

    Raises:
        ValueError: Se o fluxo não está ativo ou não tem passos
    """
    if not flow.is_active:
        raise ValueError("Este fluxo não está ativo.")

    first_step = flow.steps.order_by("order").first()
    if not first_step:
        raise ValueError("Este fluxo não possui passos configurados.")

    session = ChatbotSession.objects.create(
        flow=flow,
        channel=channel,
        sender_id=sender_id,
        current_step=first_step,
    )

    return {
        "session_key": str(session.session_key),
        "flow_name": flow.name,
        "welcome_message": flow.welcome_message,
        "step": _serialize_step(first_step),
    }


# ---------------------------------------------------------------------------
# Processamento de resposta
# ---------------------------------------------------------------------------

def process_response(session_key: str, user_response: str) -> dict:
    """Processa a resposta do usuário e avança o fluxo.

    Args:
        session_key: UUID da sessão
        user_response: Texto da resposta do usuário

    Returns:
        dict com:
        - error (bool): True se houve erro de validação
        - message (str): Mensagem de erro ou fallback
        - step (dict|None): Próximo passo serializado
        - is_complete (bool): True se o fluxo foi concluído
        - lead_id (int|None): PK do lead criado, se houver

    Raises:
        ValueError: Se sessão não encontrada ou já finalizada
    """
    try:
        session = ChatbotSession.objects.select_related(
            "flow", "current_step",
        ).get(session_key=session_key)
    except ChatbotSession.DoesNotExist:
        raise ValueError("Sessão não encontrada.")

    if session.status != ChatbotSession.Status.ACTIVE:
        raise ValueError("Esta sessão já foi finalizada.")

    step = session.current_step
    if not step:
        raise ValueError("Sessão sem passo atual.")

    # Validar resposta
    error_msg = _validate_response(step, user_response)
    if error_msg:
        return {
            "error": True,
            "message": error_msg,
            "step": _serialize_step(step),
            "is_complete": False,
            "lead_id": None,
        }

    # Normaliza a resposta — se for CHOICE e o usuário digitou um número/emoji,
    # substitui pelo label correspondente para que o branching e o lead_data
    # fiquem com o texto humano, não "1".
    text = user_response.strip()
    if step.step_type == ChatbotStep.StepType.CHOICE:
        resolved = _resolve_choice(step, text)
        if resolved:
            text = resolved.text

    # Armazenar resposta no lead_data
    if step.lead_field_mapping:
        # notes acumula múltiplas respostas (serviço, urgência, orçamento, etc.)
        if step.lead_field_mapping == "notes" and session.lead_data.get("notes"):
            session.lead_data["notes"] += f" | {text}"
        else:
            session.lead_data[step.lead_field_mapping] = text

    # DOCUMENT step: pesquisa/cria Contato e vincula à sessão.
    if step.step_type == ChatbotStep.StepType.DOCUMENT:
        _handle_document_step(session, text)

    # Encontrar próximo passo
    next_step = _find_next_step(step, text)

    if next_step:
        session.current_step = next_step
        session.save(update_fields=["current_step", "lead_data", "updated_at"])
        return {
            "error": False,
            "message": "",
            "step": _serialize_step(next_step),
            "is_complete": False,
            "lead_id": None,
        }

    # Fluxo completo
    session.status = ChatbotSession.Status.COMPLETED
    session.current_step = None
    session.save(update_fields=["status", "current_step", "lead_data", "updated_at"])

    lead_id = _execute_flow_actions(session)

    return {
        "error": False,
        "message": (
            "✅ Prontinho! Suas informações foram registradas. "
            "Um de nossos especialistas vai te chamar em breve "
            "(normalmente em até 2 horas úteis, dias úteis das 8h às 18h)."
        ),
        "step": None,
        "is_complete": True,
        "lead_id": lead_id,
    }


# ---------------------------------------------------------------------------
# Navegação entre passos
# ---------------------------------------------------------------------------

def _find_next_step(current_step: ChatbotStep, user_response: str) -> ChatbotStep | None:
    """Determina o próximo passo com base no tipo e resposta."""
    if current_step.step_type == ChatbotStep.StepType.CHOICE:
        choice = _resolve_choice(current_step, user_response)
        if choice and choice.next_step_id:
            return choice.next_step

    # Passo marcado como terminal encerra o fluxo mesmo se houver steps de maior ordem
    # (permite múltiplos ramos no mesmo flow sem fallthrough indevido).
    if current_step.is_final:
        return None

    # Default: próximo passo na ordem
    return current_step.flow.steps.filter(
        order__gt=current_step.order,
    ).order_by("order").first()


# ---------------------------------------------------------------------------
# Execução de ações ao completar
# ---------------------------------------------------------------------------

@transaction.atomic
def _execute_flow_actions(session: ChatbotSession) -> int | None:
    """Executa as ações configuradas para on_complete.

    Returns:
        PK do lead criado, se houver
    """
    lead_id = None
    actions = ChatbotAction.objects.filter(
        flow=session.flow,
        trigger=ChatbotAction.Trigger.ON_COMPLETE,
    )

    for action in actions:
        if action.action_type == ChatbotAction.ActionType.CREATE_LEAD:
            lead = _create_lead_action(session)
            if lead:
                lead_id = lead.pk
                session.lead = lead
                session.save(update_fields=["lead", "updated_at"])
        else:
            logger.info(
                "Chatbot action type '%s' not yet implemented (flow=%s)",
                action.action_type, session.flow.pk,
            )

    # Se não há ação de create_lead mas tem dados, criar mesmo assim
    if not actions.filter(action_type=ChatbotAction.ActionType.CREATE_LEAD).exists():
        if session.lead_data.get("name") or session.lead_data.get("email"):
            lead = _create_lead_action(session)
            if lead:
                lead_id = lead.pk
                session.lead = lead
                session.save(update_fields=["lead", "updated_at"])

    return lead_id


def _create_lead_action(session: ChatbotSession):
    """Cria um lead a partir dos dados da sessão."""
    from apps.automation.services import create_lead_from_chatbot

    session_data = dict(session.lead_data)
    session_data["session_id"] = str(session.session_key)

    try:
        lead = create_lead_from_chatbot(
            session.flow.empresa, session.flow, session_data,
        )
        logger.info(
            "Lead #%s criado via chatbot session %s",
            lead.pk, session.session_key,
        )
        return lead
    except Exception:
        logger.exception(
            "Erro ao criar lead via chatbot session %s",
            session.session_key,
        )
        return None


# ---------------------------------------------------------------------------
# Delegação existente (mantida para compatibilidade)
# ---------------------------------------------------------------------------

def create_lead_from_chatbot(empresa, flow, session_data):
    """Delega para apps.automation.services.create_lead_from_chatbot."""
    from apps.automation.services import create_lead_from_chatbot as _create_lead
    return _create_lead(empresa, flow, session_data)


# ---------------------------------------------------------------------------
# DOCUMENT step: integração com Contato
# ---------------------------------------------------------------------------

def _handle_document_step(session: ChatbotSession, document_text: str) -> None:
    """Pesquisa Contato pelo CPF/CNPJ e vincula à sessão.

    - Se encontrar: armazena `contato_id` em session.lead_data e copia campos
      úteis (name/phone/email) para evitar perguntas redundantes adiante.
    - Se não encontrar: salva o documento normalizado em
      session.lead_data["cpf_cnpj"] para criar Contato ao final do flow.
    """
    from apps.contacts.services import (
        find_contato_by_document,
        link_contato_to_session,
    )

    digits = normalize_document(document_text)
    session.lead_data["cpf_cnpj"] = document_text
    session.lead_data["cpf_cnpj_normalized"] = digits

    empresa = session.flow.empresa
    contato = find_contato_by_document(empresa, document_text)
    if contato:
        link_contato_to_session(contato, session)
        logger.info(
            "chatbot: linked existing Contato id=%s to session %s (doc=%s)",
            contato.pk, session.session_key, mask_document(digits),
        )
    else:
        # Mantém os dados na sessão; o Contato será criado quando a action
        # CREATE_LEAD rodar (ver _create_lead_action via automation.services).
        session.save(update_fields=["lead_data", "updated_at"])
        logger.info(
            "chatbot: no Contato found for session %s (doc=%s)",
            session.session_key, mask_document(digits),
        )


# ---------------------------------------------------------------------------
# Seleção de fluxo: resolve qual fluxo dispara para uma mensagem entrante
# ---------------------------------------------------------------------------

def _normalize_message(text: str) -> str:
    return (text or "").strip().lower()


def _matches_keyword(flow: ChatbotFlow, message: str) -> bool:
    keywords = flow.keyword_list
    if not keywords:
        return False
    normalized = _normalize_message(message)
    return any(kw in normalized for kw in keywords)


def _has_recent_dispatch(flow: ChatbotFlow, sender_id: str) -> bool:
    """Aplica cooldown: True se houve dispatch desse fluxo para esse sender
    nos últimos `cooldown_minutes`."""
    if not flow.cooldown_minutes:
        return False
    cutoff = timezone.now() - timedelta(minutes=flow.cooldown_minutes)
    return ChatbotFlowDispatch.objects.filter(
        flow=flow,
        sender_id=sender_id,
        triggered_at__gte=cutoff,
        blocked=False,
    ).exists()


def _has_active_exclusive_session(empresa, sender_id: str) -> bool:
    """Verifica se existe sessão ACTIVE de fluxo exclusivo para esse sender."""
    return ChatbotSession.objects.filter(
        flow__empresa=empresa,
        flow__exclusive=True,
        sender_id=sender_id,
        status=ChatbotSession.Status.ACTIVE,
    ).exists()


def select_flow_for_message(
    empresa,
    sender_id: str,
    message: str,
    channel: str = "whatsapp",
) -> ChatbotFlow | None:
    """Seleciona o fluxo elegível para esta mensagem entrante.

    Regras (em ordem):
    1. Se existe sessão ACTIVE de fluxo exclusivo para este sender, NÃO inicia
       outro fluxo — engine continua a sessão atual via process_response.
    2. Se trigger_type=KEYWORD: busca match na mensagem.
    3. Se trigger_type=FIRST_MESSAGE: dispara apenas se sender não tem sessão
       ACTIVE ainda.
    4. Empate: menor `priority` ganha. Cooldown bloqueia repetições.
    5. Loga `ChatbotFlowDispatch` (blocked=False ao disparar; True ao bloquear).
    """
    if _has_active_exclusive_session(empresa, sender_id):
        return None

    flows = (
        ChatbotFlow.objects
        .filter(empresa=empresa, channel=channel, is_active=True)
        .exclude(trigger_type=ChatbotFlow.TriggerType.INACTIVITY)  # tratado separadamente
        .order_by("priority", "-created_at")
    )

    candidates: list[tuple[ChatbotFlow, str]] = []
    has_active_session = ChatbotSession.objects.filter(
        flow__empresa=empresa,
        sender_id=sender_id,
        status=ChatbotSession.Status.ACTIVE,
    ).exists()

    for flow in flows:
        if _has_recent_dispatch(flow, sender_id):
            continue

        if flow.trigger_type == ChatbotFlow.TriggerType.KEYWORD:
            if _matches_keyword(flow, message):
                candidates.append((flow, "keyword"))
        elif flow.trigger_type == ChatbotFlow.TriggerType.FIRST_MESSAGE:
            if not has_active_session:
                candidates.append((flow, "first_message"))
        elif flow.trigger_type == ChatbotFlow.TriggerType.MANUAL:
            # Manual nunca dispara automaticamente
            continue

    if not candidates:
        return None

    # Já vêm ordenados por priority; pega o primeiro.
    chosen, reason = candidates[0]
    ChatbotFlowDispatch.objects.create(
        empresa=empresa,
        flow=chosen,
        sender_id=sender_id,
        reason=reason,
        blocked=False,
        metadata={"channel": channel, "candidates": len(candidates)},
    )
    # Loga os outros como blocked
    for flow, reason in candidates[1:]:
        ChatbotFlowDispatch.objects.create(
            empresa=empresa,
            flow=flow,
            sender_id=sender_id,
            reason=f"blocked_by:{chosen.name}",
            blocked=True,
        )
    return chosen


# ---------------------------------------------------------------------------
# Disparo de fluxos por inatividade (chamado por Celery beat)
# ---------------------------------------------------------------------------

def dispatch_inactivity_flows(empresa) -> int:
    """Verifica sessões ativas inativas e dispara fluxos com trigger=INACTIVITY.

    Retorna o número de fluxos disparados.
    """
    flows = ChatbotFlow.objects.filter(
        empresa=empresa,
        is_active=True,
        trigger_type=ChatbotFlow.TriggerType.INACTIVITY,
        inactivity_minutes__isnull=False,
    ).order_by("priority")

    if not flows.exists():
        return 0

    dispatched = 0
    now = timezone.now()
    for flow in flows:
        cutoff = now - timedelta(minutes=flow.inactivity_minutes)
        candidate_sessions = ChatbotSession.objects.filter(
            flow__empresa=empresa,
            status=ChatbotSession.Status.ACTIVE,
            updated_at__lt=cutoff,
        ).order_by("sender_id", "-updated_at")

        seen_senders: set[str] = set()
        for session in candidate_sessions:
            sender_id = session.sender_id
            if not sender_id or sender_id in seen_senders:
                continue
            seen_senders.add(sender_id)
            if _has_recent_dispatch(flow, sender_id):
                continue
            ChatbotFlowDispatch.objects.create(
                empresa=empresa,
                flow=flow,
                sender_id=sender_id,
                reason=f"inactivity {flow.inactivity_minutes}min",
                blocked=False,
                metadata={"trigger_session": str(session.session_key)},
            )
            try:
                start_session(flow, channel=session.channel, sender_id=sender_id)
                dispatched += 1
            except Exception:
                logger.exception(
                    "chatbot: failed to start inactivity flow %s for %s",
                    flow.pk, sender_id,
                )
    return dispatched

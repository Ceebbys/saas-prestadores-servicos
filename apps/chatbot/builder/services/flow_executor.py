"""Motor v2 do chatbot — interpreta graph_json publicado (RV06).

Assinatura idêntica aos métodos legados (`start_session_v2`,
`process_response_v2`) para drop-in via despachador em
`apps.chatbot.services`.

Suporta 8 tipos de bloco no MVP: start, message, question, menu,
condition, collect_data, handoff, end. O bloco `api_call` está
marcado como "coming_soon" no catálogo e bloqueado no validador,
não chega ao executor em fluxos publicados.

Cria registros de:
- `ChatbotMessage` para cada outbound/inbound
- `ChatbotExecutionLog` para entrada/saída de node, ações, erros
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.chatbot.builder.services import graph_utils
from apps.chatbot.models import (
    ChatbotExecutionLog,
    ChatbotFlow,
    ChatbotMessage,
    ChatbotSession,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Regex de validação reusados do legado (apps/chatbot/services.py)
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PHONE_RE = re.compile(r"^[\d\s()\-+]{7,20}$")


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def start_session_v2(flow: ChatbotFlow, channel: str = "webchat", sender_id: str = "") -> dict:
    """Inicia uma sessão lendo o graph_json da versão publicada."""
    version = flow.current_published_version
    if version is None or not version.graph_json:
        raise ValueError("Fluxo não tem versão publicada com graph válido.")

    graph = version.graph_json
    starts = graph_utils.find_start_nodes(graph)
    if not starts:
        raise ValueError("Graph publicado não tem bloco 'Início'.")
    start_node = starts[0]

    session = ChatbotSession.objects.create(
        flow=flow,
        current_node_id=start_node["id"],
        channel=channel,
        sender_id=sender_id,
        status=ChatbotSession.Status.ACTIVE,
    )
    _log(session, start_node["id"], "session_started", "info", {
        "version_id": version.id,
        "schema_version": version.schema_version,
    })

    # Mensagem de boas-vindas do start (se houver) — senão usa welcome do flow
    welcome = (start_node.get("data") or {}).get("welcome_message") or flow.welcome_message or ""

    # Avança para o próximo node (start não pergunta nada)
    next_node = _advance_from(graph, start_node, session)
    response = _enter_node(graph, next_node, session) if next_node else _complete(session, graph, reason="no_path_from_start")

    return {
        "session_key": str(session.session_key),
        "flow_name": flow.name,
        "welcome_message": welcome,
        "step": response.get("step"),  # nome legado para compat — equivale a "prompt do node atual"
        "is_complete": response.get("is_complete", False),
        "message": response.get("message", ""),
        "lead_id": response.get("lead_id"),
    }


def process_response_v2(session_key: str, user_response: str) -> dict:
    """Processa resposta do usuário no node atual e avança."""
    try:
        session = ChatbotSession.objects.select_related("flow").get(
            session_key=session_key,
            status=ChatbotSession.Status.ACTIVE,
        )
    except ChatbotSession.DoesNotExist:
        return {"error": True, "message": "Sessão não encontrada ou expirada."}

    version = session.flow.current_published_version
    if version is None:
        return {"error": True, "message": "Fluxo não tem versão publicada."}

    graph = version.graph_json
    nodes_by_id = graph_utils.index_nodes(graph)
    current = nodes_by_id.get(session.current_node_id)
    if current is None:
        return {"error": True, "message": "Nó atual não encontrado no grafo."}

    # Registra inbound
    _msg_in(session, current["id"], user_response)

    # Valida + extrai resposta conforme tipo
    validation = _validate_user_input(current, user_response)
    if validation["error"]:
        # Re-pergunta — não avança
        _log(session, current["id"], "validation_failed", "warning", {
            "user_input_preview": user_response[:80],
            "reason": validation["message"],
        })
        _msg_out(session, current["id"], validation["message"])
        return {
            "error": False,
            "step": _step_payload(current),
            "message": validation["message"],
            "is_complete": False,
        }

    # Persistir resposta em lead_data (se aplicável)
    _store_lead_data(current, user_response, validation, session)

    # Avança para próximo node (com edge handle correto se aplicável)
    next_node = _advance_from(graph, current, session, validation=validation)
    if next_node is None:
        return _complete(session, graph, reason="no_outgoing_edge")

    return _enter_node(graph, next_node, session)


# ---------------------------------------------------------------------------
# Internals — navegação
# ---------------------------------------------------------------------------


def _advance_from(graph: dict, node: dict, session: ChatbotSession, validation: dict | None = None) -> dict | None:
    """Encontra o próximo node baseado no tipo + validação atual.

    - start: segue 'next'
    - message/question/collect_data/handoff: segue 'next'
    - menu: segue handle = validation['handle_id']
    - condition: avalia e segue 'true' ou 'false'
    - end: None (terminal)
    """
    ntype = node.get("type")
    nodes_by_id = graph_utils.index_nodes(graph)

    if ntype == "end":
        return None

    handle: str | None = None
    if ntype == "menu" and validation:
        handle = validation.get("handle_id")
    elif ntype == "condition":
        ok = _evaluate_condition(node, session)
        handle = "true" if ok else "false"
        _log(session, node["id"], "node_exited", "info", {"branch": handle})
    else:
        handle = "next"

    for e in graph.get("edges", []):
        if e["source"] != node["id"]:
            continue
        edge_handle = e.get("sourceHandle") or "next"
        if edge_handle == handle:
            target = nodes_by_id.get(e["target"])
            if target is None:
                # RV06-H — edge aponta para node inexistente (graph corrompido).
                # Loga + continua procurando outro handle (defensivo, não silencia).
                _log(session, node["id"], "error", "error", {
                    "reason": "edge_target_not_found",
                    "edge_id": e.get("id"),
                    "target": e.get("target"),
                    "handle": edge_handle,
                })
                logger.warning(
                    "Executor v2: edge %s aponta para node inexistente '%s' (source=%s)",
                    e.get("id"), e.get("target"), node["id"],
                )
                continue
            return target
    return None


# RV06-H — tipos de node suportados pelo executor v2. api_call NÃO está aqui
# (validator já bloqueia status=coming_soon, mas defesa em profundidade).
_KNOWN_NODE_TYPES = {
    "start", "message", "question", "menu", "condition",
    "collect_data", "api_call", "handoff", "end",
}


def _enter_node(graph: dict, node: dict, session: ChatbotSession) -> dict:
    """Entra em um node: envia mensagem se aplicável, avança ou aguarda input."""
    ntype = node.get("type")
    data = node.get("data") or {}

    # RV06-H — defesa contra graph publicado com tipo desconhecido (futuro tipo
    # adicionado ao catálogo mas sem handler aqui; ou graph manipulado direto
    # no DB). Loga + encerra com erro explícito ao invés de silenciar.
    if ntype not in _KNOWN_NODE_TYPES:
        _log(session, node["id"], "error", "error", {
            "reason": "unknown_node_type",
            "node_type": ntype,
        })
        logger.error(
            "Executor v2: tipo '%s' não suportado (node_id=%s, flow=%s). "
            "Adicione handler em flow_executor.py::_enter_node.",
            ntype, node["id"], session.flow_id,
        )
        return _complete(session, graph, reason=f"unknown_node_type:{ntype}", node_id=node["id"])

    _log(session, node["id"], "node_entered", "info", {"type": ntype})

    # Nodes que enviam mensagem mas não aguardam input → seguir em frente
    NO_INPUT_TYPES = {"start", "message", "condition"}
    AWAIT_INPUT_TYPES = {"question", "menu", "collect_data"}

    if ntype == "message":
        text = data.get("text", "")
        if text:
            _msg_out(session, node["id"], text)
        # Atualiza current e segue
        session.current_node_id = node["id"]
        session.save(update_fields=["current_node_id", "updated_at"])
        nxt = _advance_from(graph, node, session)
        if nxt is None:
            return _complete(session, graph, reason="end_after_message")
        return _enter_node(graph, nxt, session)

    if ntype == "condition":
        session.current_node_id = node["id"]
        session.save(update_fields=["current_node_id", "updated_at"])
        nxt = _advance_from(graph, node, session)
        if nxt is None:
            return _complete(session, graph, reason="condition_no_branch")
        return _enter_node(graph, nxt, session)

    if ntype in AWAIT_INPUT_TYPES:
        # Aguarda input → salva estado e retorna prompt
        session.current_node_id = node["id"]
        session.save(update_fields=["current_node_id", "updated_at"])
        prompt = data.get("prompt", "")
        if prompt:
            _msg_out(session, node["id"], prompt)
        return {
            "error": False,
            "step": _step_payload(node),
            "is_complete": False,
            "message": prompt,
        }

    if ntype == "handoff":
        msg = data.get("message_to_user", "")
        if msg:
            _msg_out(session, node["id"], msg)
        session.current_node_id = node["id"]
        # Marca como completed (transferência humana — bot sai do controle)
        return _complete(session, graph, reason="handoff", node_id=node["id"])

    if ntype == "api_call":
        # V2A — chamada HTTP externa com credencial do cofre
        session.current_node_id = node["id"]
        session.save(update_fields=["current_node_id", "updated_at"])
        success = _execute_api_call(node, session)
        # Segue handle 'success' ou 'error'
        handle = "success" if success else "error"
        nxt = _advance_from_handle(graph, node, session, handle)
        if nxt is None:
            return _complete(
                session, graph,
                reason=f"api_call_{handle}_no_branch", node_id=node["id"],
            )
        return _enter_node(graph, nxt, session)

    if ntype == "end":
        return _complete(session, graph, reason="end_node", node_id=node["id"])

    # Defesa: já checado no início; defensive fallback
    return _complete(session, graph, reason=f"unknown_node_type:{ntype}", node_id=node["id"])


def _advance_from_handle(graph: dict, node: dict, session: ChatbotSession, handle: str) -> dict | None:
    """Avança forçando um handle específico (api_call/condition)."""
    nodes_by_id = graph_utils.index_nodes(graph)
    for e in graph.get("edges", []):
        if e["source"] != node["id"]:
            continue
        edge_handle = e.get("sourceHandle") or "next"
        if edge_handle == handle:
            target = nodes_by_id.get(e["target"])
            if target is None:
                _log(session, node["id"], "error", "error", {
                    "reason": "edge_target_not_found",
                    "edge_id": e.get("id"),
                    "target": e.get("target"),
                    "handle": handle,
                })
                continue
            return target
    return None


def _execute_api_call(node: dict, session: ChatbotSession) -> bool:
    """Executa node `api_call`: HTTP request com credencial do cofre.

    Retorna True em sucesso (status 2xx), False em erro de qualquer tipo.
    Grava resposta em session.lead_data[response_var] se configurado.
    """
    import json as _json
    from string import Template
    import httpx

    from apps.chatbot.models import ChatbotSecret

    data = node.get("data") or {}
    secret_ref = (data.get("secret_ref") or "").strip()
    method = (data.get("method") or "GET").upper()
    path_template = (data.get("path_template") or "").strip()
    payload_template = (data.get("payload_template") or "").strip()
    response_var = (data.get("response_var") or "").strip()

    if not secret_ref or not path_template:
        _log(session, node["id"], "validation_failed", "error", {
            "reason": "api_call_missing_fields",
        })
        return False

    # Resolve segredo (tenant-isolated)
    try:
        secret = ChatbotSecret.objects.get(empresa=session.flow.empresa, name=secret_ref)
    except ChatbotSecret.DoesNotExist:
        _log(session, node["id"], "error", "error", {
            "reason": "secret_not_found",
            "secret_ref": secret_ref,
        })
        return False

    from apps.chatbot.builder.services.secrets import get_secret_value
    token = get_secret_value(secret)
    if not token:
        _log(session, node["id"], "error", "error", {
            "reason": "secret_decrypt_failed",
            "secret_ref": secret_ref,
        })
        return False

    # Substituição de variáveis em path + payload via $vars (string.Template
    # é restrito — apenas $name / ${name}, sem code execution).
    safe_vars = {k: str(v) for k, v in (session.lead_data or {}).items()}
    safe_vars["secret"] = token  # disponível para Authorization headers

    try:
        url = Template(path_template).safe_substitute(safe_vars)
    except Exception:
        url = path_template

    body_json = None
    if payload_template and method in ("POST", "PUT", "PATCH"):
        try:
            body_str = Template(payload_template).safe_substitute(safe_vars)
            body_json = _json.loads(body_str)
        except (_json.JSONDecodeError, ValueError) as exc:
            _log(session, node["id"], "error", "error", {
                "reason": "payload_template_invalid_json",
                "error": str(exc)[:200],
            })
            return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "ServicoPro-Chatbot/1.0",
    }

    _log(session, node["id"], "api_call", "info", {
        "method": method,
        "url_host": url.split("/")[2] if "://" in url else "?",  # log sem path completo
        "has_payload": body_json is not None,
    })

    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            resp = client.request(method, url, json=body_json, headers=headers)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        _log(session, node["id"], "error", "error", {
            "reason": "http_error",
            "error": str(exc)[:200],
        })
        return False

    success = 200 <= resp.status_code < 300
    _log(session, node["id"], "api_call", "info" if success else "warning", {
        "status_code": resp.status_code,
        "success": success,
    })

    if response_var:
        try:
            parsed = resp.json()
        except ValueError:
            parsed = resp.text[:2000]  # limita
        if not session.lead_data:
            session.lead_data = {}
        session.lead_data[response_var] = parsed
        session.save(update_fields=["lead_data", "updated_at"])

    return success


def _complete(session: ChatbotSession, graph: dict, reason: str, node_id: str = "") -> dict:
    """Marca sessão como concluída."""
    session.status = ChatbotSession.Status.COMPLETED
    session.current_node_id = node_id
    session.save(update_fields=["status", "current_node_id", "updated_at"])

    # Mensagem de encerramento, se o último end node tinha completion_message
    final_msg = ""
    if node_id:
        nodes_by_id = graph_utils.index_nodes(graph)
        last_node = nodes_by_id.get(node_id, {})
        final_msg = (last_node.get("data") or {}).get("completion_message", "")
    if not final_msg and session.flow.send_completion_message:
        final_msg = session.flow.completion_message or ""

    if final_msg:
        _msg_out(session, node_id or "system", final_msg)

    _log(session, node_id, "session_completed", "info", {"reason": reason})

    return {
        "error": False,
        "step": None,
        "is_complete": True,
        "message": final_msg,
        "lead_id": session.lead_id,
    }


# ---------------------------------------------------------------------------
# Internals — validação de input
# ---------------------------------------------------------------------------


def _validate_user_input(node: dict, user_response: str) -> dict:
    """Valida resposta segundo o tipo do node.

    Retorna {error, message, handle_id, normalized_value}.
    """
    ntype = node.get("type")
    data = node.get("data") or {}
    text = (user_response or "").strip()

    if ntype == "question":
        if not text:
            return {"error": True, "message": "Por favor, responda com algum texto."}
        validator = data.get("validator", "free_text")
        if validator == "name" and len(text) < 2:
            return {"error": True, "message": "Nome muito curto. Tente novamente."}
        return {"error": False, "normalized_value": text}

    if ntype == "menu":
        options = data.get("options") or []
        # Aceita: número 1-indexed, label literal (case-insensitive), prefixo curto
        try:
            idx = int(text) - 1
            if 0 <= idx < len(options):
                return {
                    "error": False,
                    "handle_id": options[idx].get("handle_id"),
                    "normalized_value": options[idx].get("label"),
                }
        except (ValueError, TypeError):
            pass
        text_low = text.lower()
        for opt in options:
            label_low = (opt.get("label") or "").lower()
            value_low = (opt.get("value") or "").lower()
            if text_low == label_low or text_low == value_low:
                return {
                    "error": False,
                    "handle_id": opt.get("handle_id"),
                    "normalized_value": opt.get("label"),
                }
        # Prefixo >= 3 chars
        if len(text_low) >= 3:
            for opt in options:
                label_low = (opt.get("label") or "").lower()
                if label_low.startswith(text_low):
                    return {
                        "error": False,
                        "handle_id": opt.get("handle_id"),
                        "normalized_value": opt.get("label"),
                    }
        labels = ", ".join(o.get("label", "?") for o in options)
        return {"error": True, "message": f"Não entendi. Escolha uma das opções: {labels}"}

    if ntype == "collect_data":
        lead_field = data.get("lead_field")
        strict = data.get("validator_strict", True)
        if lead_field == "email":
            if not _EMAIL_RE.match(text):
                if strict:
                    return {"error": True, "message": "E-mail inválido. Tente novamente."}
        elif lead_field == "phone":
            if not _PHONE_RE.match(text):
                if strict:
                    return {"error": True, "message": "Telefone inválido. Tente novamente."}
        elif lead_field == "cpf_cnpj":
            try:
                from apps.core.validators import validate_cpf_or_cnpj
                if not validate_cpf_or_cnpj(text):
                    if strict:
                        return {"error": True, "message": "Documento inválido (CPF ou CNPJ). Tente novamente."}
            except ImportError:
                pass
        elif lead_field == "name" and len(text) < 2:
            return {"error": True, "message": "Nome muito curto. Tente novamente."}
        return {"error": False, "normalized_value": text}

    # start/message/condition/end/handoff não esperam input — retorna ok
    return {"error": False, "normalized_value": text}


def _store_lead_data(node: dict, user_response: str, validation: dict, session: ChatbotSession) -> None:
    """Grava em session.lead_data conforme node + validação."""
    data = node.get("data") or {}
    lead_field = data.get("lead_field")
    if not lead_field:
        return
    if not session.lead_data:
        session.lead_data = {}
    session.lead_data[lead_field] = validation.get("normalized_value") or user_response
    session.save(update_fields=["lead_data", "updated_at"])


def _evaluate_condition(node: dict, session: ChatbotSession) -> bool:
    """Avalia condition contra session.lead_data."""
    data = node.get("data") or {}
    field = data.get("field", "")
    op = data.get("operator", "eq")
    value = data.get("value", "")
    actual = (session.lead_data or {}).get(field)

    # RV06-H — operadores que NÃO sejam exists/not_exists, comparando contra
    # campo nunca coletado, retornam False mas logam warning (debugging).
    if actual is None and op not in ("exists", "not_exists"):
        _log(session, node["id"], "validation_failed", "warning", {
            "reason": "condition_field_missing",
            "field": field,
            "operator": op,
        })

    if op == "exists":
        return actual is not None and actual != ""
    if op == "not_exists":
        return actual is None or actual == ""
    if op == "eq":
        return str(actual) == str(value)
    if op == "neq":
        return str(actual) != str(value)
    if op == "contains":
        return value.lower() in str(actual or "").lower()
    if op == "starts_with":
        return str(actual or "").lower().startswith(value.lower())
    if op == "in":
        # value é csv: "a,b,c"
        items = [s.strip() for s in value.split(",")]
        return str(actual) in items
    if op == "regex":
        try:
            return bool(re.search(value, str(actual or "")))
        except re.error:
            return False
    return False


# ---------------------------------------------------------------------------
# Internals — persistência de mensagens + logs
# ---------------------------------------------------------------------------


def _msg_in(session: ChatbotSession, node_id: str, content: str) -> None:
    ChatbotMessage.objects.create(
        session=session,
        direction=ChatbotMessage.Direction.INBOUND,
        content=content,
        node_id=node_id or "",
    )


def _msg_out(session: ChatbotSession, node_id: str, content: str, payload: dict | None = None) -> None:
    ChatbotMessage.objects.create(
        session=session,
        direction=ChatbotMessage.Direction.OUTBOUND,
        content=content,
        node_id=node_id or "",
        payload=payload or {},
    )


def _log(session: ChatbotSession, node_id: str, event: str, level: str, payload: dict | None = None) -> None:
    ChatbotExecutionLog.objects.create(
        session=session,
        node_id=node_id or "",
        event=event,
        level=level,
        payload=payload or {},
    )


def _step_payload(node: dict) -> dict:
    """Serializa o node atual em formato compatível com o consumidor (frontend chat).

    Mantém shape próximo ao serializer legado:
        {"id", "question", "type", "required", "choices": [...]}
    """
    data = node.get("data") or {}
    payload = {
        "id": node["id"],
        "question": data.get("prompt", ""),
        "type": node.get("type"),
        "required": True,
    }
    if node.get("type") == "menu":
        payload["choices"] = [
            {"text": o.get("label"), "value": o.get("handle_id"), "id": o.get("handle_id")}
            for o in data.get("options", [])
        ]
    return payload

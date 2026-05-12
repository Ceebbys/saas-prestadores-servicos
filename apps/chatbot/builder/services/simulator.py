"""V2B — Simulador inline para o construtor visual.

Executa turnos de uma "sessão sandbox" lendo o DRAFT graph (não a versão
publicada). Estado vive na própria session HTTP ou pode ser passado via
request body (stateless mode).

Sandbox NÃO persiste:
- ChatbotSession (estado em memória/HTTP session)
- ChatbotMessage / ChatbotExecutionLog (retorna em memória)
- Side effects (api_call usa httpx mas com flag de simulação)

Usado pelo botão "Testar" no Topbar do builder.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import TYPE_CHECKING

from apps.chatbot.builder.services import graph_utils
from apps.chatbot.builder.services.flow_executor import (
    _EMAIL_RE,
    _PHONE_RE,
)

if TYPE_CHECKING:
    from apps.chatbot.models import ChatbotFlow

logger = logging.getLogger(__name__)


class _SandboxSession:
    """Mock de ChatbotSession para o simulador (não persiste nada)."""

    def __init__(self, flow):
        self.flow = flow
        self.flow_id = flow.id
        self.pk = None
        self.session_key = uuid.uuid4()
        self.current_node_id = ""
        self.lead_data: dict = {}
        self.lead_id = None
        self.messages: list[dict] = []
        self.logs: list[dict] = []


def start_simulation(flow, draft_graph: dict) -> dict:
    """Inicia simulação usando o draft graph (não a versão publicada).

    Retorna estado inicial + step atual.
    """
    starts = graph_utils.find_start_nodes(draft_graph)
    if not starts:
        return {"error": True, "message": "Graph sem bloco 'Início'."}

    state = {
        "session_key": str(uuid.uuid4()),
        "current_node_id": "",
        "lead_data": {},
        "messages": [],
        "is_complete": False,
    }

    # Avança do start até parar em algum await
    return _step_through(draft_graph, state, start_node=starts[0])


def process_simulation(draft_graph: dict, state: dict, user_response: str) -> dict:
    """Processa resposta no contexto simulado e retorna novo estado."""
    nodes_by_id = graph_utils.index_nodes(draft_graph)
    current_id = state.get("current_node_id")
    current = nodes_by_id.get(current_id)
    if current is None:
        return {**state, "error": True, "message": "Nó atual inválido."}

    # Inbound message
    state["messages"].append({"direction": "inbound", "content": user_response, "node_id": current_id})

    # Valida input
    validation = _validate_user_input_sim(current, user_response)
    if validation.get("error"):
        msg = validation.get("message", "Resposta inválida.")
        state["messages"].append({"direction": "outbound", "content": msg, "node_id": current_id})
        return {**state, "is_complete": False, "message": msg, "current_node_id": current_id, "error": False}

    # Stora resposta em lead_data
    data = current.get("data") or {}
    lead_field = data.get("lead_field")
    if lead_field:
        state["lead_data"][lead_field] = validation.get("normalized_value") or user_response

    # Avança
    next_node = _advance_from_sim(draft_graph, current, state, validation=validation)
    if next_node is None:
        return _complete_sim(state, current_id, reason="end_of_flow")
    return _step_through(draft_graph, state, start_node=next_node)


def _step_through(graph: dict, state: dict, *, start_node: dict) -> dict:
    """Caminha pelos nós sem-input (start/message/condition/api_call MOCK)
    até parar em um await ou terminal."""
    nodes_by_id = graph_utils.index_nodes(graph)
    node = start_node
    safety = 50  # evita loop infinito em simulação
    while safety > 0:
        safety -= 1
        ntype = node.get("type")
        data = node.get("data") or {}
        state["current_node_id"] = node["id"]

        if ntype == "start":
            # Avança
            nxt = _advance_from_sim(graph, node, state)
            if nxt is None:
                return _complete_sim(state, node["id"], reason="no_path_from_start")
            node = nxt
            continue

        if ntype == "message":
            text = data.get("text", "")
            if text:
                state["messages"].append({"direction": "outbound", "content": text, "node_id": node["id"]})
            nxt = _advance_from_sim(graph, node, state)
            if nxt is None:
                return _complete_sim(state, node["id"], reason="end_after_message")
            node = nxt
            continue

        if ntype == "condition":
            ok = _evaluate_condition_sim(node, state)
            handle = "true" if ok else "false"
            nxt = _advance_from_handle_sim(graph, node, handle)
            if nxt is None:
                return _complete_sim(state, node["id"], reason="condition_no_branch")
            node = nxt
            continue

        if ntype == "api_call":
            # No simulador, api_call é MOCK: assume sucesso, simula resposta vazia
            state["messages"].append({
                "direction": "system",
                "content": f"[Simulação] api_call para '{data.get('path_template', '?')}' (mock: success)",
                "node_id": node["id"],
            })
            response_var = (data.get("response_var") or "").strip()
            if response_var:
                state["lead_data"][response_var] = {"_simulated": True}
            nxt = _advance_from_handle_sim(graph, node, "success")
            if nxt is None:
                return _complete_sim(state, node["id"], reason="api_call_no_branch")
            node = nxt
            continue

        if ntype in ("question", "menu", "collect_data"):
            # Para aqui — aguarda input
            prompt = data.get("prompt", "")
            if prompt:
                state["messages"].append({"direction": "outbound", "content": prompt, "node_id": node["id"]})
            return {
                **state,
                "is_complete": False,
                "step": {
                    "id": node["id"],
                    "type": ntype,
                    "prompt": prompt,
                    "options": [
                        {"label": o.get("label"), "value": o.get("handle_id")}
                        for o in (data.get("options") or [])
                    ] if ntype == "menu" else None,
                },
                "error": False,
            }

        if ntype == "handoff":
            msg = data.get("message_to_user", "")
            if msg:
                state["messages"].append({"direction": "outbound", "content": msg, "node_id": node["id"]})
            return _complete_sim(state, node["id"], reason="handoff")

        if ntype == "end":
            return _complete_sim(state, node["id"], reason="end_node")

        # Desconhecido
        return _complete_sim(state, node["id"], reason=f"unknown_node_type:{ntype}")

    return _complete_sim(state, state.get("current_node_id", ""), reason="simulation_safety_limit")


def _complete_sim(state: dict, node_id: str, reason: str) -> dict:
    state["is_complete"] = True
    state["current_node_id"] = node_id
    # Procura completion_message no node terminal
    msg = ""
    if node_id and state.get("messages"):
        # Já adicionado no _step_through
        pass
    return {**state, "error": False, "step": None, "completion_reason": reason}


def _advance_from_sim(graph: dict, node: dict, state: dict, validation: dict | None = None) -> dict | None:
    """Segue 'next' OU handle de menu (quando validation traz handle_id)."""
    ntype = node.get("type")
    handle = "next"
    if ntype == "menu" and validation:
        handle = validation.get("handle_id") or "next"
    return _advance_from_handle_sim(graph, node, handle)


def _advance_from_handle_sim(graph: dict, node: dict, handle: str) -> dict | None:
    nodes_by_id = graph_utils.index_nodes(graph)
    for e in graph.get("edges", []):
        if e["source"] != node["id"]:
            continue
        edge_handle = e.get("sourceHandle") or "next"
        if edge_handle == handle:
            target = nodes_by_id.get(e["target"])
            if target is None:
                continue
            return target
    return None


def _validate_user_input_sim(node: dict, user_response: str) -> dict:
    """Validação simplificada equivalente ao executor real."""
    ntype = node.get("type")
    data = node.get("data") or {}
    text = (user_response or "").strip()

    if ntype == "question":
        if not text:
            return {"error": True, "message": "Por favor, responda com algum texto."}
        return {"error": False, "normalized_value": text}

    if ntype == "menu":
        options = data.get("options") or []
        try:
            idx = int(text) - 1
            if 0 <= idx < len(options):
                return {"error": False, "handle_id": options[idx].get("handle_id"), "normalized_value": options[idx].get("label")}
        except (ValueError, TypeError):
            pass
        for opt in options:
            if text.lower() == (opt.get("label") or "").lower():
                return {"error": False, "handle_id": opt.get("handle_id"), "normalized_value": opt.get("label")}
        labels = ", ".join(o.get("label", "?") for o in options)
        return {"error": True, "message": f"Não entendi. Opções: {labels}"}

    if ntype == "collect_data":
        lead_field = data.get("lead_field")
        strict = data.get("validator_strict", True)
        if lead_field == "email" and not _EMAIL_RE.match(text):
            if strict:
                return {"error": True, "message": "E-mail inválido."}
        elif lead_field == "phone" and not _PHONE_RE.match(text):
            if strict:
                return {"error": True, "message": "Telefone inválido."}
        return {"error": False, "normalized_value": text}

    return {"error": False, "normalized_value": text}


def _evaluate_condition_sim(node: dict, state: dict) -> bool:
    """Avalia condition contra state.lead_data."""
    data = node.get("data") or {}
    field = data.get("field", "")
    op = data.get("operator", "eq")
    value = data.get("value", "")
    actual = (state.get("lead_data") or {}).get(field)

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
        items = [s.strip() for s in value.split(",")]
        return str(actual) in items
    if op == "regex":
        try:
            return bool(re.search(value, str(actual or "")))
        except re.error:
            return False
    return False

"""Validador semântico do graph_json (RV06).

Roda 12 etapas (todas, sempre — feedback completo, não para no primeiro erro):
1.  Schema JSON válido (jsonschema vs graph_v1.json)
2.  Exatamente 1 node `start`
3.  Pelo menos 1 node terminal (`end` ou `handoff`)
4.  Todo node alcançável a partir de start (BFS)
5.  Todos campos `data` required preenchidos (por catálogo)
6.  Menu com >=2 options + handles únicos + edges para cada handle
7.  Condition com 2 outbound (`true`, `false`) distintos
8.  api_call com 2 outbound (`success`, `error`) e secret_ref válido
9.  Sem ciclos sem saída
10. Sem nodes "soltos" (sem inbound e não-start)
11. Texto sanitizado (sem <script> etc) em text/prompt/etc
12. Limites globais (nodes, edges, tamanho de texto)

Retorno:
    {
      "valid": bool,
      "errors": [{"node_id", "field", "message", "code", "severity": "error"}],
      "warnings": [{"node_id", "field", "message", "code", "severity": "warning"}]
    }
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from django.conf import settings
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from apps.chatbot.builder.schemas import (
    get_node_type,
    load_graph_schema,
    load_node_catalog,
)
from apps.chatbot.builder.services import graph_utils

if TYPE_CHECKING:
    from apps.chatbot.models import ChatbotFlow


MAX_NODES = getattr(settings, "CHATBOT_BUILDER_MAX_NODES", 200)
MAX_EDGES = getattr(settings, "CHATBOT_BUILDER_MAX_EDGES", 500)
MAX_TEXT_FIELD_LEN = getattr(settings, "CHATBOT_BUILDER_MAX_TEXT_LEN", 5000)


def validate_graph(graph: dict, *, flow: "ChatbotFlow | None" = None) -> dict:
    """Pipeline completa de validação. Sempre executa todas as etapas."""
    errors: list[dict] = []
    warnings: list[dict] = []

    # 1. Schema JSON válido (curto-circuita o resto se schema falhar muito feio)
    schema_errors = _validate_schema(graph)
    errors.extend(schema_errors)
    # Se nem o schema básico passa, retorna direto — outras etapas pressupõem estrutura
    if schema_errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    # 12. Limites globais (antes das demais, dá erro útil rápido)
    if len(nodes) > MAX_NODES:
        errors.append(_err(
            None, None, f"Limite máximo de {MAX_NODES} nós excedido (atual: {len(nodes)}).",
            "LIMIT_NODES_EXCEEDED",
        ))
    if len(edges) > MAX_EDGES:
        errors.append(_err(
            None, None, f"Limite máximo de {MAX_EDGES} conexões excedido (atual: {len(edges)}).",
            "LIMIT_EDGES_EXCEEDED",
        ))

    # 2. Exatamente 1 node start
    starts = graph_utils.find_start_nodes(graph)
    if len(starts) == 0:
        errors.append(_err(None, None, "O fluxo precisa ter um bloco 'Início'.", "MISSING_START"))
    elif len(starts) > 1:
        for s in starts[1:]:
            errors.append(_err(
                s["id"], None,
                "Existe mais de um bloco 'Início' no fluxo. Apenas um é permitido.",
                "DUPLICATE_START",
            ))

    # 3. Pelo menos 1 terminal
    terminals = graph_utils.find_terminal_nodes(graph)
    if not terminals:
        warnings.append(_warn(
            None, None,
            "Nenhum bloco 'Encerrar' ou 'Transferir' encontrado — fluxo pode rodar indefinidamente.",
            "NO_TERMINAL_NODE",
        ))

    # 4. Todo node alcançável a partir de start
    if starts:
        reachable = graph_utils.reachable_from(graph, starts[0]["id"])
        for n in nodes:
            if n["id"] not in reachable and n.get("type") != "start":
                warnings.append(_warn(
                    n["id"], None,
                    "Este bloco não é alcançável a partir do início.",
                    "NODE_NOT_REACHABLE",
                ))

    # 5/6/7/8. Validação por tipo de bloco (usando catálogo)
    for n in nodes:
        _validate_node_data(n, graph, errors, warnings, flow=flow)

    # 9. Ciclos sem saída
    if graph_utils.has_cycle_without_exit(graph):
        errors.append(_err(
            None, None,
            "Existe um ciclo sem saída — o fluxo não consegue terminar.",
            "CYCLE_WITHOUT_EXIT",
        ))

    # 10. Nós soltos (sem inbound e não-start)
    by_tgt = graph_utils.edges_by_target(graph)
    for n in nodes:
        if n.get("type") == "start":
            continue
        if n["id"] not in by_tgt:
            warnings.append(_warn(
                n["id"], None,
                "Este bloco não tem nenhuma conexão de entrada — está solto no canvas.",
                "ORPHAN_NODE",
            ))

    # 11. Sanitização de texto (rude pass)
    _check_text_sanity(nodes, warnings)

    # `lead_field` reutilizado em múltiplos nós → warning
    _check_lead_field_collisions(nodes, warnings)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _validate_schema(graph: dict) -> list[dict]:
    """Etapa 1 — JSON Schema validation."""
    schema = load_graph_schema()
    validator = Draft7Validator(schema)
    errors: list[dict] = []
    for err in validator.iter_errors(graph):
        path_str = ".".join(str(p) for p in err.absolute_path) or "(root)"
        # Tenta extrair node_id se o erro for em um node
        node_id = None
        try:
            parts = list(err.absolute_path)
            if len(parts) >= 2 and parts[0] == "nodes":
                idx = parts[1]
                node = graph.get("nodes", [])[idx]
                node_id = node.get("id")
        except Exception:
            pass
        errors.append(_err(
            node_id, path_str, f"Estrutura inválida: {err.message}", "SCHEMA_VIOLATION",
        ))
    return errors


def _validate_node_data(
    node: dict, graph: dict, errors: list, warnings: list, flow=None,
) -> None:
    """Valida `data` do node contra o catálogo + regras estruturais por tipo."""
    ntype = node.get("type")
    catalog_entry = get_node_type(ntype)
    if not catalog_entry:
        errors.append(_err(
            node["id"], "type",
            f"Tipo de bloco desconhecido: '{ntype}'.",
            "UNKNOWN_NODE_TYPE",
        ))
        return

    # Bloco em status "coming_soon" (api_call) não pode ser publicado
    if catalog_entry.get("status") == "coming_soon":
        errors.append(_err(
            node["id"], None,
            f"O bloco '{catalog_entry['label']}' ainda não está disponível.",
            "NODE_TYPE_COMING_SOON",
        ))

    data = node.get("data") or {}

    # Campos básicos (sempre validados)
    _validate_fields(
        node["id"], data, catalog_entry.get("data_fields", []), errors,
    )

    # RV06 — Campos adicionais condicionais por action_type (apenas em node 'action')
    if ntype == "action":
        action_type = (data.get("action_type") or "").strip()
        per_type = catalog_entry.get("data_fields_per_action_type") or {}
        extra_fields = per_type.get(action_type, [])
        _validate_fields(node["id"], data, extra_fields, errors)

    # Regras específicas por tipo
    if ntype == "menu":
        _validate_menu_handles(node, graph, errors)
    elif ntype == "condition":
        _validate_condition_handles(node, graph, errors)
    elif ntype == "api_call":
        _validate_api_call_handles(node, graph, errors, flow=flow)
    elif ntype == "start":
        _validate_start(node, graph, errors)


def _validate_fields(node_id: str, data: dict, fields: list, errors: list) -> None:
    """Valida lista de field definitions contra `data`.

    Reutilizado para data_fields básicos e data_fields_per_action_type.
    Tipos suportados: string, text, integer, boolean, enum, array, select.
    """
    for field in fields:
        fname = field["name"]
        required = field.get("required", False)
        value = data.get(fname)
        max_len = field.get("max_length") or field.get("max")

        if required and (value is None or (isinstance(value, str) and not value.strip())):
            errors.append(_err(
                node_id, f"data.{fname}",
                f"Campo obrigatório '{field.get('label') or fname}' não preenchido.",
                "REQUIRED_FIELD_EMPTY",
            ))
            continue

        if isinstance(value, str) and max_len and len(value) > max_len:
            errors.append(_err(
                node_id, f"data.{fname}",
                f"Texto excede o limite de {max_len} caracteres.",
                "FIELD_TOO_LONG",
            ))

        if field["type"] == "enum" and value and value not in field.get("options", []):
            errors.append(_err(
                node_id, f"data.{fname}",
                f"Valor '{value}' não está nas opções permitidas.",
                "INVALID_ENUM_VALUE",
            ))

        if field["type"] == "array" and value is not None:
            min_items = field.get("min_items", 0)
            max_items = field.get("max_items", 9999)
            if not isinstance(value, list) or len(value) < min_items:
                errors.append(_err(
                    node_id, f"data.{fname}",
                    f"Lista precisa de pelo menos {min_items} item(s).",
                    "ARRAY_TOO_SHORT",
                ))
            elif len(value) > max_items:
                errors.append(_err(
                    node_id, f"data.{fname}",
                    f"Lista excede o limite de {max_items} item(s).",
                    "ARRAY_TOO_LONG",
                ))

        # `select` é validado apenas em "preenchido se required"; a verificação
        # de que o ID existe no tenant é feita no executor/handler (precisa de
        # acesso ao DB e à empresa do flow — fora do escopo do validator
        # estático).


def _validate_menu_handles(node: dict, graph: dict, errors: list) -> None:
    """Menu: cada option precisa ter handle_id único e edge correspondente."""
    options = (node.get("data") or {}).get("options") or []
    handle_ids: list[str] = []
    labels: dict[str, str] = {}
    for o in options:
        if isinstance(o, dict):
            hid = o.get("handle_id") or ""
            handle_ids.append(hid)
            labels[hid] = o.get("label") or hid
    # Handles únicos
    seen = set()
    for h in handle_ids:
        if not h:
            errors.append(_err(
                node["id"], "data.options",
                "Toda opção do menu precisa de um identificador único (handle_id).",
                "MENU_OPTION_MISSING_HANDLE",
            ))
            continue
        if h in seen:
            errors.append(_err(
                node["id"], "data.options",
                f"Opção '{labels.get(h, h)}' tem identificador duplicado. "
                f"Cada opção precisa de um identificador único — renomeie ou recrie.",
                "MENU_DUPLICATE_HANDLE",
            ))
        seen.add(h)
    # Cada handle tem edge?
    outbound = graph_utils.outbound_handles_of(graph, node["id"])
    for h in handle_ids:
        if h and h not in outbound:
            label = labels.get(h, h)
            errors.append(_err(
                node["id"], f"options.{h}",
                f"Opção '{label}' não está conectada a nenhum próximo bloco. "
                f"Arraste uma conexão a partir desta opção para outro bloco.",
                "MENU_OPTION_NOT_CONNECTED",
            ))


def _validate_condition_handles(node: dict, graph: dict, errors: list) -> None:
    """Condition: precisa de exatamente 2 outbound (`true`, `false`)."""
    outbound = graph_utils.outbound_handles_of(graph, node["id"])
    for required_handle in ("true", "false"):
        if required_handle not in outbound:
            errors.append(_err(
                node["id"], f"handle.{required_handle}",
                f"A saída '{required_handle}' precisa estar conectada.",
                "CONDITION_MISSING_BRANCH",
            ))


def _validate_api_call_handles(node: dict, graph: dict, errors: list, flow=None) -> None:
    """api_call: precisa de outbound `success` e `error` + secret_ref válido."""
    outbound = graph_utils.outbound_handles_of(graph, node["id"])
    for required_handle in ("success", "error"):
        if required_handle not in outbound:
            errors.append(_err(
                node["id"], f"handle.{required_handle}",
                f"A saída '{required_handle}' precisa estar conectada.",
                "API_CALL_MISSING_BRANCH",
            ))

    # V2A — secret_ref precisa existir como ChatbotSecret na empresa
    data = node.get("data") or {}
    secret_ref = (data.get("secret_ref") or "").strip()
    if secret_ref and flow is not None:
        from apps.chatbot.models import ChatbotSecret
        exists = ChatbotSecret.objects.filter(
            empresa=flow.empresa, name=secret_ref,
        ).exists()
        if not exists:
            errors.append(_err(
                node["id"], "data.secret_ref",
                f"Segredo '{secret_ref}' não está cadastrado em Configurações > Segredos do Chatbot.",
                "SECRET_NOT_FOUND",
            ))


def _validate_start(node: dict, graph: dict, errors: list) -> None:
    """start: não pode ter inbound; precisa de outbound 'next'."""
    by_tgt = graph_utils.edges_by_target(graph)
    if node["id"] in by_tgt:
        errors.append(_err(
            node["id"], None,
            "O bloco 'Início' não pode receber conexões de entrada.",
            "START_HAS_INBOUND",
        ))
    if "next" not in graph_utils.outbound_handles_of(graph, node["id"]):
        errors.append(_err(
            node["id"], None,
            "O bloco 'Início' precisa estar conectado a um próximo bloco.",
            "START_NOT_CONNECTED",
        ))


def _check_text_sanity(nodes: list[dict], warnings: list) -> None:
    """Detecta texto com <script> ou outras tags suspeitas (rude pass).

    Sanitização efetiva fica no input do form (frontend valida ANTES de salvar
    e backend re-sanitiza no save). Este check é apenas alerta defensivo.
    """
    SUSPICIOUS = ("<script", "javascript:", "onerror=", "onload=")
    text_fields = ("text", "prompt", "completion_message", "welcome_message",
                   "message_to_user", "internal_note")
    for n in nodes:
        for fname in text_fields:
            val = (n.get("data") or {}).get(fname)
            if isinstance(val, str):
                lower = val.lower()
                for s in SUSPICIOUS:
                    if s in lower:
                        warnings.append(_warn(
                            n["id"], f"data.{fname}",
                            "Texto contém marcação potencialmente insegura. Será sanitizado ao salvar.",
                            "POTENTIALLY_UNSAFE_TEXT",
                        ))
                        break


def _check_lead_field_collisions(nodes: list[dict], warnings: list) -> None:
    """Aviso se múltiplos nodes gravam no mesmo lead_field (último ganha)."""
    seen: dict[str, str] = {}
    for n in nodes:
        lf = (n.get("data") or {}).get("lead_field")
        if not lf:
            continue
        if lf in seen and seen[lf] != n["id"]:
            warnings.append(_warn(
                n["id"], "data.lead_field",
                f"O campo '{lf}' também é usado pelo bloco {seen[lf]} — o último a executar prevalece.",
                "LEAD_FIELD_COLLISION",
            ))
        else:
            seen[lf] = n["id"]


def _err(node_id: str | None, field: str | None, message: str, code: str) -> dict:
    return {
        "node_id": node_id,
        "field": field,
        "message": message,
        "code": code,
        "severity": "error",
    }


def _warn(node_id: str | None, field: str | None, message: str, code: str) -> dict:
    return {
        "node_id": node_id,
        "field": field,
        "message": message,
        "code": code,
        "severity": "warning",
    }

"""Conversor de fluxo legado (ChatbotStep/Choice) para graph_json (RV06).

Roda lazy ao primeiro clique em "Abrir editor visual" — não destrutivo:
os models legados continuam intocados. O resultado vira um draft de
`ChatbotFlowVersion`.

Mapeamento:
- ChatbotStep.step_type:
    TEXT/NAME/COMPANY      → question (com validator correspondente)
    EMAIL/PHONE/DOCUMENT   → collect_data (lead_field correspondente)
    CHOICE                 → menu (com options vindas de ChatbotChoice)
- ChatbotChoice.next_step  → edge (sourceHandle=opt_<order>)
- Step com is_final=True   → liga para node 'end' sintético
- Primeiro step (ordem ASC) recebe edge do node 'start' sintético

Posições são deixadas em (0, 0); o frontend roda dagre.js no primeiro
carregamento para auto-layout, depois persiste no graph_json.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.chatbot.models import ChatbotFlow, ChatbotStep


_STEPTYPE_MAP_QUESTION = {
    "text": "free_text",
    "name": "name",
    "company": "company",
}
_STEPTYPE_MAP_COLLECT = {
    "email": "email",
    "phone": "phone",
    "document": "cpf_cnpj",
}


def convert_legacy_flow_to_graph(flow: "ChatbotFlow") -> dict:
    """Converte ChatbotFlow legado em graph_json (schema v1).

    Retorna estrutura pronta para gravar em ChatbotFlowVersion.graph_json.
    """
    from apps.chatbot.models import ChatbotStep

    steps = list(
        ChatbotStep.objects.filter(flow=flow)
        .order_by("order", "id")
        .prefetch_related("choices")
    )

    nodes: list[dict] = []
    edges: list[dict] = []
    edge_counter = [0]
    end_node_id: str | None = None

    def _next_edge_id() -> str:
        edge_counter[0] += 1
        return f"e_{edge_counter[0]}"

    def _ensure_end_node() -> str:
        nonlocal end_node_id
        if end_node_id is None:
            end_node_id = "n_end_legacy"
            nodes.append({
                "id": end_node_id,
                "type": "end",
                "position": {"x": 0, "y": 0},
                "data": {
                    "label": "Fim",
                    "completion_message": flow.completion_message or "",
                },
            })
        return end_node_id

    # Node start sintético
    nodes.append({
        "id": "n_start",
        "type": "start",
        "position": {"x": 0, "y": 0},
        "data": {
            "label": "Início",
            "welcome_message": flow.welcome_message or "",
        },
    })

    if not steps:
        # Fluxo vazio — conecta start direto a um end sintético
        end_id = _ensure_end_node()
        edges.append({
            "id": _next_edge_id(),
            "source": "n_start",
            "sourceHandle": "next",
            "target": end_id,
            "targetHandle": "in",
            "label": "",
        })
    else:
        # Conecta start ao primeiro step
        first_id = _step_node_id(steps[0])
        edges.append({
            "id": _next_edge_id(),
            "source": "n_start",
            "sourceHandle": "next",
            "target": first_id,
            "targetHandle": "in",
            "label": "",
        })

    # Cria nodes para cada step + edges
    for idx, step in enumerate(steps):
        node = _convert_step(step)
        # Preserva position se já existia visual_config
        node["position"] = {
            "x": float(step.position_x or 0),
            "y": float(step.position_y or 0),
        }
        nodes.append(node)

        # Liga choices ou linear/final
        if step.step_type == "choice":
            choices = list(step.choices.all().order_by("order", "id"))
            for c in choices:
                if c.next_step_id:
                    edges.append({
                        "id": _next_edge_id(),
                        "source": _step_node_id(step),
                        "sourceHandle": f"opt_{c.order}",
                        "target": _step_node_id_from_pk(c.next_step_id),
                        "targetHandle": "in",
                        "label": c.text[:40] if c.text else "",
                    })
                else:
                    # Choice sem next_step → vai para próximo na ordem OU end
                    nxt = _find_next_in_order(steps, idx)
                    target = _step_node_id(nxt) if nxt else _ensure_end_node()
                    edges.append({
                        "id": _next_edge_id(),
                        "source": _step_node_id(step),
                        "sourceHandle": f"opt_{c.order}",
                        "target": target,
                        "targetHandle": "in",
                        "label": c.text[:40] if c.text else "",
                    })
        else:
            if step.is_final:
                # Terminal — vai para node end
                end_id = _ensure_end_node()
                edges.append({
                    "id": _next_edge_id(),
                    "source": _step_node_id(step),
                    "sourceHandle": "next",
                    "target": end_id,
                    "targetHandle": "in",
                    "label": "",
                })
            else:
                # Linear — próximo step por ordem (se houver)
                nxt = _find_next_in_order(steps, idx)
                if nxt:
                    edges.append({
                        "id": _next_edge_id(),
                        "source": _step_node_id(step),
                        "sourceHandle": "next",
                        "target": _step_node_id(nxt),
                        "targetHandle": "in",
                        "label": "",
                    })
                else:
                    # Último step sem is_final → criar end implícito
                    end_id = _ensure_end_node()
                    edges.append({
                        "id": _next_edge_id(),
                        "source": _step_node_id(step),
                        "sourceHandle": "next",
                        "target": end_id,
                        "targetHandle": "in",
                        "label": "",
                    })

    return {
        "schema_version": 1,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "metadata": {
            "converted_from_legacy": True,
            "legacy_flow_id": flow.id,
            "legacy_step_count": len(steps),
        },
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _step_node_id(step: "ChatbotStep") -> str:
    return f"n_step_{step.pk}"


def _step_node_id_from_pk(pk: int) -> str:
    return f"n_step_{pk}"


def _find_next_in_order(steps: list, current_idx: int):
    """Próximo step na lista (por order), ou None se for o último."""
    if current_idx + 1 < len(steps):
        return steps[current_idx + 1]
    return None


def _convert_step(step: "ChatbotStep") -> dict:
    """Converte um ChatbotStep para node graph_json baseado em step_type."""
    label = step.question_text[:60] if step.question_text else f"Passo {step.order}"
    data: dict = {"label": label}

    if step.step_type == "choice":
        choices = list(step.choices.all().order_by("order", "id"))
        options = []
        for c in choices:
            options.append({
                "label": c.text[:200],
                "value": c.text[:80],
                "handle_id": f"opt_{c.order}",
            })
        data["prompt"] = step.question_text or ""
        data["options"] = options
        return {
            "id": _step_node_id(step),
            "type": "menu",
            "position": {"x": 0, "y": 0},
            "data": data,
        }

    if step.step_type in _STEPTYPE_MAP_COLLECT:
        data["prompt"] = step.question_text or ""
        data["lead_field"] = _STEPTYPE_MAP_COLLECT[step.step_type]
        data["validator_strict"] = bool(step.is_required)
        return {
            "id": _step_node_id(step),
            "type": "collect_data",
            "position": {"x": 0, "y": 0},
            "data": data,
        }

    # text, name, company → question
    data["prompt"] = step.question_text or ""
    if step.lead_field_mapping:
        data["lead_field"] = step.lead_field_mapping
    data["validator"] = _STEPTYPE_MAP_QUESTION.get(step.step_type, "free_text")
    return {
        "id": _step_node_id(step),
        "type": "question",
        "position": {"x": 0, "y": 0},
        "data": data,
    }

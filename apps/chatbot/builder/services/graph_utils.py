"""Helpers puros sobre graph_json (sem efeitos colaterais).

Indexação, busca de nós por id, BFS a partir do start, detecção de
ciclos e nós alcançáveis. Reutilizados pelo validator e pelo executor.
"""
from __future__ import annotations

from typing import Any, Iterable


def index_nodes(graph: dict) -> dict[str, dict]:
    """Retorna {node_id: node} para acesso O(1)."""
    return {n["id"]: n for n in graph.get("nodes", [])}


def edges_by_source(graph: dict) -> dict[str, list[dict]]:
    """Retorna {source_id: [edges...]} mantendo ordem do graph_json."""
    out: dict[str, list[dict]] = {}
    for e in graph.get("edges", []):
        out.setdefault(e["source"], []).append(e)
    return out


def edges_by_target(graph: dict) -> dict[str, list[dict]]:
    """Retorna {target_id: [edges...]}."""
    out: dict[str, list[dict]] = {}
    for e in graph.get("edges", []):
        out.setdefault(e["target"], []).append(e)
    return out


def find_start_nodes(graph: dict) -> list[dict]:
    """Lista de nodes type='start'."""
    return [n for n in graph.get("nodes", []) if n.get("type") == "start"]


def find_terminal_nodes(graph: dict) -> list[dict]:
    """Nodes que terminam o fluxo: type in (end, handoff)."""
    return [
        n for n in graph.get("nodes", [])
        if n.get("type") in ("end", "handoff")
    ]


def reachable_from(graph: dict, start_id: str) -> set[str]:
    """BFS retornando set de node_ids alcançáveis a partir de start_id."""
    by_src = edges_by_source(graph)
    visited: set[str] = {start_id}
    frontier: list[str] = [start_id]
    while frontier:
        nxt: list[str] = []
        for nid in frontier:
            for e in by_src.get(nid, []):
                tgt = e.get("target")
                if tgt and tgt not in visited:
                    visited.add(tgt)
                    nxt.append(tgt)
        frontier = nxt
    return visited


def find_cycles(graph: dict) -> list[list[str]]:
    """Detecta ciclos via DFS. Retorna lista de ciclos (cada ciclo é
    uma lista de node_ids na ordem visitada). Para validador, basta
    saber se há algum ciclo "sem saída" — função independente abaixo.
    """
    by_src = edges_by_source(graph)
    color: dict[str, int] = {}  # 0=branco, 1=cinza, 2=preto
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        color[node] = 1
        path.append(node)
        for e in by_src.get(node, []):
            tgt = e.get("target")
            if not tgt:
                continue
            c = color.get(tgt, 0)
            if c == 0:
                dfs(tgt, path)
            elif c == 1:
                # Back-edge — ciclo encontrado; extrair sub-path
                if tgt in path:
                    idx = path.index(tgt)
                    cycles.append(path[idx:] + [tgt])
        path.pop()
        color[node] = 2

    for n in graph.get("nodes", []):
        nid = n["id"]
        if color.get(nid, 0) == 0:
            dfs(nid, [])
    return cycles


def has_cycle_without_exit(graph: dict) -> bool:
    """Detecta ciclos onde nenhum nó tem outbound edge fora do ciclo.

    Ciclos "com saída" são aceitos (ex.: loop de validação que sai ao
    receber resposta correta). Ciclos "sem saída" são proibidos.
    """
    cycles = find_cycles(graph)
    if not cycles:
        return False
    by_src = edges_by_source(graph)
    for cycle in cycles:
        cycle_set = set(cycle)
        has_exit = False
        for nid in cycle_set:
            for e in by_src.get(nid, []):
                if e.get("target") not in cycle_set:
                    has_exit = True
                    break
            if has_exit:
                break
        if not has_exit:
            return True
    return False


def node_has_outbound_with_handle(
    graph: dict, node_id: str, handle: str
) -> bool:
    """True se existe edge com source=node_id e sourceHandle=handle."""
    for e in graph.get("edges", []):
        if e.get("source") == node_id and e.get("sourceHandle") == handle:
            return True
    return False


def outbound_handles_of(graph: dict, node_id: str) -> set[str]:
    """Set de sourceHandles que saem de node_id."""
    return {
        e.get("sourceHandle") or "next"
        for e in graph.get("edges", [])
        if e.get("source") == node_id
    }


# ---------------------------------------------------------------------------
# RV06 Hotfix — Sanitização defensiva contra extras do React Flow
# ---------------------------------------------------------------------------

# Whitelist do schema graph_v1.json para nodes
_ALLOWED_NODE_KEYS = frozenset({
    "id", "type", "position", "data",
    "width", "height", "selected", "dragging", "positionAbsolute",
})

# Whitelist do schema graph_v1.json para edges
_ALLOWED_EDGE_KEYS = frozenset({
    "id", "source", "target", "sourceHandle", "targetHandle",
    "label", "type", "animated", "data", "style", "selected",
    "markerEnd", "markerStart",
})

# Whitelist para position
_ALLOWED_POSITION_KEYS = frozenset({"x", "y"})


def sanitize_graph_for_storage(graph: dict) -> dict:
    """RV06 Hotfix — Remove campos transitórios injetados pelo React Flow
    antes de gravar no banco / validar contra o schema.

    O React Flow adiciona automaticamente em cada node: `className`,
    `measured`, `selectable`, `connectable`, `deletable`, `draggable`,
    `focusable`, `parentId`, `expandParent`, `extent`, `zIndex`,
    `sourcePosition`, `targetPosition`, `hidden`, `ariaLabel`,
    `handleBounds`. Esses campos quebram o `additionalProperties: false`
    do schema graph_v1.

    Mantém apenas o whitelist do schema. Aplicado em:
    - GraphSaveView (POST /save/) — para fluxos novos
    - GraphValidateView (POST /validate/) — para fluxos legacy que
      já tinham lixo salvo no banco antes desta correção.

    Não muta o `graph` original.
    """
    if not isinstance(graph, dict):
        return graph
    sanitized = dict(graph)
    nodes_in = graph.get("nodes") or []
    edges_in = graph.get("edges") or []
    sanitized["nodes"] = [_sanitize_node(n) for n in nodes_in if isinstance(n, dict)]
    sanitized["edges"] = [_sanitize_edge(e) for e in edges_in if isinstance(e, dict)]
    return sanitized


def _sanitize_node(node: dict) -> dict:
    out = {k: v for k, v in node.items() if k in _ALLOWED_NODE_KEYS}
    # Sanitize nested position (não permite x/y extras)
    pos = out.get("position")
    if isinstance(pos, dict):
        out["position"] = {k: v for k, v in pos.items() if k in _ALLOWED_POSITION_KEYS}
    return out


def _sanitize_edge(edge: dict) -> dict:
    return {k: v for k, v in edge.items() if k in _ALLOWED_EDGE_KEYS}

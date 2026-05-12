"""Carregamento dos schemas canônicos do builder visual.

`graph_v1.json` é o JSON Schema do grafo. `node_catalog.json` é a tabela
de tipos de bloco com seus campos esperados, handles, ícones e cores.

Ambos são compartilhados com o frontend via endpoint `GET /api/chatbot/node-catalog/`.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_SCHEMAS_DIR = Path(__file__).parent


@lru_cache(maxsize=4)
def load_graph_schema() -> dict:
    """Retorna o JSON Schema do graph_json (cached)."""
    with (_SCHEMAS_DIR / "graph_v1.json").open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=4)
def load_node_catalog() -> dict:
    """Retorna o catálogo de tipos de bloco (cached)."""
    with (_SCHEMAS_DIR / "node_catalog.json").open(encoding="utf-8") as f:
        return json.load(f)


def get_node_type(node_type: str) -> dict | None:
    """Retorna a definição de um tipo de bloco ou None se desconhecido."""
    catalog = load_node_catalog()
    for entry in catalog.get("nodes", []):
        if entry["type"] == node_type:
            return entry
    return None

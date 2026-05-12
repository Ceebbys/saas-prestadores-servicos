"""RV06 — Construtor visual de fluxos do chatbot (React Flow island).

Subpacote isolado para a evolução visual do chatbot:
- `schemas/` — JSON Schema do graph_json e catálogo de tipos de bloco.
- `services/` — converter (legacy→graph_json), validator e executor v2.
- `api/` — endpoints JSON consumidos pelo bundle React.

O motor legacy (`apps.chatbot.services`) continua intacto. O despachador
em `apps.chatbot.services.start_session` decide qual interpretador usar
baseado em `flow.use_visual_builder` e `flow.current_published_version`.
"""

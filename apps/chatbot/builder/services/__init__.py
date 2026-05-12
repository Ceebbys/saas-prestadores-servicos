"""Services do construtor visual de fluxos do chatbot (RV06).

- `graph_utils` — helpers puros sobre o graph_json (índices, BFS, ciclos).
- `flow_validator` — pipeline de validação semântica do grafo.
- `flow_converter` — conversão lazy ChatbotStep/Choice → graph_json.
- `flow_executor` — motor v2 que interpreta o graph_json publicado.
"""

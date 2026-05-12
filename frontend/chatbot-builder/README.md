# Chatbot Builder (React Flow island)

Frontend isolado em Vite + React + TypeScript para o construtor visual de
fluxos do chatbot do SaaS. É a única parte React do projeto; o resto é
Django + HTMX + Alpine.js.

## Comandos

```bash
npm install         # 1ª vez
npm run dev         # http://localhost:5173 (mock data via index.html)
npm run typecheck   # tsc --noEmit
npm run build       # gera bundle em ../../static/js/chatbot-builder/
```

## Output do build

```
static/js/chatbot-builder/
├── main.js         # ~344 KB (~111 KB gzip)
├── style.css       # ~25 KB (~4.6 KB gzip)
└── index.html      # artefato do Vite, não usado pelo Django
```

Django serve via `{% static 'js/chatbot-builder/main.js' %}` no template
`templates/chatbot/flow_builder.html`. WhiteNoise re-hasheia no
`collectstatic` (CompressedManifestStaticFilesStorage).

## Arquitetura

```
main.tsx
  └─ App.tsx
      ├─ Topbar (Salvar / Validar / Publicar)
      ├─ Sidebar (paleta de blocos arrastáveis)
      ├─ Canvas (React Flow + drag-drop)
      │   └─ nodes/GenericNode | MenuNode | ConditionNode
      └─ PropertiesPanel (campos dinâmicos por catálogo)
```

- **State:** zustand store em `src/store/builderStore.ts`
- **API:** hooks em `src/hooks/useGraphAPI.ts` + autosave em `useAutosave.ts`
- **Schemas:** TypeScript em `src/types.ts` — mirror de
  `apps/chatbot/builder/schemas/{graph_v1.json,node_catalog.json}`.

## Como adicionar novo tipo de bloco

1. Adicionar entrada em `apps/chatbot/builder/schemas/node_catalog.json`.
2. Adicionar `type` no enum de nodes em `apps/chatbot/builder/schemas/graph_v1.json`.
3. Adicionar regras no validator em `apps/chatbot/builder/services/flow_validator.py`.
4. Adicionar handler no executor v2 em `apps/chatbot/builder/services/flow_executor.py`.
5. Se precisar de UI especial, criar componente em `src/components/nodes/`
   e registrar em `Canvas.tsx::nodeTypes`. Caso contrário, `GenericNode` cobre.

## Estilos

Sem Tailwind no bundle React (Tailwind v4 fica no Django via `output.css`
pré-compilado). Builder usa CSS direto em `src/styles/builder.css` com
paleta indigo/slate alinhada ao SaaS.

## Como o Django carrega

`templates/chatbot/flow_builder.html`:

```html
<div id="chatbot-builder-root"
     data-flow-id="..."
     data-csrf-token="..."
     data-graph-endpoint="..."
     ...></div>
{{ initial_graph|json_script:"chatbot-initial-graph" }}
<script type="module" src="{% static 'js/chatbot-builder/main.js' %}"></script>
```

`main.tsx` lê o `dataset` para descobrir endpoints + CSRF token e monta o app.

## Auth

Cookie de sessão Django (same-origin). CSRF via header `X-CSRFToken`.
**Não** usa token API.

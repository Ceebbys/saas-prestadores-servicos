# RV06 — Construtor visual de fluxos do chatbot

Sexta rodada de evolução. Transforma o editor manual de fluxos (formulários +
formset HTMX) em um **construtor visual drag-and-drop** com React Flow,
mantendo Django+HTMX como base do SaaS.

## Resumo executivo

- React Flow entra como **ilha isolada** em `frontend/chatbot-builder/` (Vite +
  React 18 + TypeScript). O resto do SaaS permanece 100% server-side.
- Fluxos versionados via `ChatbotFlowVersion` (DRAFT/PUBLISHED/ARCHIVED) com
  `graph_json` validado por JSON Schema.
- **Dual storage**: fluxos legados (ChatbotStep/Choice) coexistem com fluxos
  visuais. Despachador escolhe o motor pela flag `use_visual_builder`.
- **Conversão lazy**: ao clicar "Abrir editor visual" pela primeira vez, um
  conversor cria draft a partir dos steps/choices existentes.
- 8 tipos de bloco no MVP: Início, Mensagem, Pergunta, Menu, Condição,
  Coletar dado, Transferir, Encerrar. `api_call` adiado para V2.
- Auditoria estruturada: `ChatbotMessage` + `ChatbotExecutionLog` (tabelas
  relacionais, não JSON).
- Build remoto: `npm ci && npm run build` na VPS (Node 20 LTS).

**Suite:** 467 testes verde (+57 novos do RV06).

---

## Arquitetura

```
                    ┌──────────────────────────┐
                    │     ChatbotFlow          │
                    │  + use_visual_builder    │  ← flag de regime
                    └──────────┬───────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
   (regime legado)                  (regime visual)
   ChatbotStep + Choice           ChatbotFlowVersion
   gravado pelo editor manual      (draft + N published)
   (apps/chatbot/forms.py)         graph_json canônico
              │                                 │
              └─────────────────┬───────────────┘
                                │
                       apps.chatbot.services
                       (despachador legacy/v2)
                                │
              ┌─────────────────┴────────────────┐
              │                                  │
   _start_session_legacy            start_session_v2
   _process_response_legacy         process_response_v2
   (motor v1 intacto)               (motor v2 lê graph_json)
```

## Modelos novos (`apps/chatbot/models.py`)

- **ChatbotFlowVersion** — versão de fluxo (`numero` sequencial, `status`,
  `graph_json`, `validation_errors`, `published_at`, `published_by`).
  Constraints: 1 DRAFT por flow + 1 PUBLISHED por flow.
- **ChatbotMessage** — mensagens trocadas (`direction`, `content`, `payload`,
  `node_id`). Index `(session, created_at)` + `(direction, created_at)`.
- **ChatbotExecutionLog** — eventos de execução por nó (`event`, `level`,
  `payload`). Index `(session, created_at)` + `(level, -created_at)`.
- **ChatbotSecret** — cofre Fernet de credenciais (preparado para V2, sem
  UI de CRUD no MVP).

## Campos adicionados

- `ChatbotFlow.use_visual_builder` (bool) — marcado automaticamente no
  primeiro publish bem-sucedido.
- `ChatbotFlow.current_published_version` (FK) — atalho para o executor.
- `ChatbotSession.current_node_id` (CharField) — apontador do motor v2.

## Migration

**`apps/chatbot/migrations/0011_visual_builder_v1.py`** — apenas operações
additivas (CreateModel + AddField), zero RunPython. Aplicar com:

```bash
python manage.py migrate chatbot
```

## Schema do graph_json

Canônico em `apps/chatbot/builder/schemas/graph_v1.json` (JSON Schema Draft-07).
Estrutura:

```json
{
  "schema_version": 1,
  "viewport": {"x": 0, "y": 0, "zoom": 1},
  "metadata": {},
  "nodes": [
    {"id": "n_start", "type": "start", "position": {"x": 100, "y": 100}, "data": {}}
  ],
  "edges": [
    {"id": "e1", "source": "n_start", "target": "n_msg1",
     "sourceHandle": "next", "targetHandle": "in"}
  ]
}
```

Validação backend via `jsonschema` strict (recusa keys extras). Schema TS
espelhado em `frontend/chatbot-builder/src/types.ts`.

## Catálogo de tipos de bloco

`apps/chatbot/builder/schemas/node_catalog.json` — fonte da verdade para
backend (validator) e frontend (paleta + propriedades dinâmicas).

| `type` | Status | `data` fields chave | Validador |
|---|---|---|---|
| `start` | ✅ | `welcome_message` (opt) | 1 por graph, sem inbound |
| `message` | ✅ | `text` req | text não vazio |
| `question` | ✅ | `prompt` req, `lead_field` opt | prompt não vazio |
| `menu` | ✅ | `prompt`, `options[]` >=2 | handles únicos + conectados |
| `condition` | ✅ | `field`, `operator`, `value` | 2 outbound (true/false) |
| `collect_data` | ✅ | `lead_field` (email/phone/cpf_cnpj/name) | validator por tipo |
| `api_call` | ⏳ V2 | `secret_ref`, `method`, `path` | (bloqueado no validator) |
| `handoff` | ✅ | `message_to_user`, `queue` (opt) | queue ou assign_to |
| `end` | ✅ | `completion_message` (opt) | sem outbound |

Frontend obtém via `GET /api/chatbot/node-catalog/`.

## Endpoints API

| Método | Path | Descrição |
|---|---|---|
| GET | `/api/chatbot/flows/<pk>/graph/` | retorna draft graph (cria se não existe) |
| POST | `/api/chatbot/flows/<pk>/graph/save/` | autosave do draft |
| POST | `/api/chatbot/flows/<pk>/validate/` | roda validator |
| POST | `/api/chatbot/flows/<pk>/publish/` | publica (exige válido); cria PUBLISHED, arquiva anterior |
| POST | `/api/chatbot/flows/<pk>/builder/init/` | converte legacy → draft (lazy) |
| GET | `/api/chatbot/node-catalog/` | catálogo de blocos |
| GET | `/chatbot/flows/<pk>/builder/` | template host do React (HTML) |

**Auth:** session-based + CSRF. **Tenant isolation:** `BuilderAPIView.dispatch`
valida `flow.empresa_id == request.empresa.id` (defesa contra IDOR).
**Rate limit:** 60 calls/60s por user via `@rate_limit_per_user` em save/validate/publish.

## Validador

`apps/chatbot/builder/services/flow_validator.py::validate_graph(graph, flow=None)`

Pipeline (todas as etapas rodam — feedback completo):

1. Schema JSON válido (jsonschema)
2. Exatamente 1 node `start`
3. Pelo menos 1 node terminal (warning se ausente)
4. Todo node alcançável a partir de start (BFS)
5. Campos `data` required preenchidos (por catálogo)
6. Menu com >=2 options, handles únicos, todos conectados
7. Condition com 2 outbound (`true`, `false`)
8. api_call bloqueado (status=coming_soon)
9. Sem ciclos sem saída
10. Sem nós soltos (sem inbound, exceto start)
11. Sanitização básica de texto (alerta para `<script>`, `javascript:`)
12. Limites globais (200 nodes, 500 edges, 5000 chars)

Retorno: `{valid: bool, errors: [...], warnings: [...]}`.

## Motor v2

`apps/chatbot/builder/services/flow_executor.py::start_session_v2 / process_response_v2`

Mesma assinatura dos legados. Interno:
- Lê `flow.current_published_version.graph_json`
- Estado: `ChatbotSession.current_node_id`
- Navegação: índice por node.id + edges por (source, sourceHandle)
- Cria `ChatbotMessage` (inbound/outbound) + `ChatbotExecutionLog` por turno

Despachador em `apps/chatbot/services.py::start_session` decide v1 ou v2 pelo
flag `flow.use_visual_builder`.

## Conversor legacy → graph_json

`apps/chatbot/builder/services/flow_converter.py::convert_legacy_flow_to_graph(flow)`

Mapeamento:
- `step_type=text/name/company` → `question`
- `step_type=email/phone/document` → `collect_data`
- `step_type=choice` → `menu` com options
- `ChatbotChoice.next_step` → edge (`sourceHandle=opt_<order>`)
- `is_final=True` → edge para node `end` sintético
- Primeiro step recebe edge do `start` sintético

Lazy: roda ao chamar `POST /api/chatbot/flows/<pk>/builder/init/`. Idempotente
(se draft já existe, retorna existente).

---

## Frontend (`frontend/chatbot-builder/`)

### Stack
- Vite 5 + React 18 + TypeScript 5
- @xyflow/react v12 (React Flow renomeado)
- zustand 4 (state)
- dagre 0.8 (auto-layout)
- Sem Tailwind no bundle — CSS direto em `src/styles/builder.css`

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│ TOPBAR: nome | status | Salvar | Validar | Publicar          │
├──────────┬──────────────────────────────────┬───────────────┤
│ SIDEBAR  │     CANVAS (React Flow)          │ PROPS PANEL   │
│ Paleta   │  Background grid + MiniMap       │ Campos do     │
│ por      │  Drag-drop da paleta             │ bloco         │
│ categoria│  Connect handles                 │ selecionado   │
└──────────┴──────────────────────────────────┴───────────────┘
```

### Estrutura

```
frontend/chatbot-builder/
├── package.json            (Vite + React + reactflow)
├── vite.config.ts          (output: ../../static/js/chatbot-builder/)
├── tsconfig.json
├── index.html              (mock host para npm run dev)
└── src/
    ├── main.tsx            (entry; lê dataset do <div root>)
    ├── App.tsx             (carrega catálogo, monta layout)
    ├── types.ts            (mirror TS do schema)
    ├── components/
    │   ├── Topbar.tsx
    │   ├── Sidebar.tsx           (paleta)
    │   ├── Canvas.tsx            (React Flow + drag-drop)
    │   ├── PropertiesPanel.tsx
    │   ├── MenuOptionsEditor.tsx
    │   └── nodes/
    │       ├── GenericNode.tsx   (start/message/question/etc.)
    │       ├── MenuNode.tsx      (handles dinâmicos por option)
    │       └── ConditionNode.tsx (handles true/false)
    ├── store/builderStore.ts     (zustand)
    ├── hooks/
    │   ├── useGraphAPI.ts         (save/validate/publish)
    │   └── useAutosave.ts         (debounced 1500ms)
    └── styles/builder.css
```

### Como rodar (dev local)

```bash
cd frontend/chatbot-builder
npm install         # 1ª vez
npm run dev         # abre http://localhost:5173 (mock data)
npm run typecheck   # validar TS
npm run build       # gera static/js/chatbot-builder/{main.js,style.css}
```

### Como o template Django carrega

`templates/chatbot/flow_builder.html` provê o `<div id="chatbot-builder-root">`
com `data-*` attributes (endpoints + CSRF + flow id) e carrega
`{% static 'js/chatbot-builder/main.js' %}`. O React lê o dataset no `main.tsx`
e monta.

Graph inicial é embebido em `<script type="application/json" id="chatbot-initial-graph">`
para evitar segundo round-trip (mas o cliente faz `GET /graph/` ao montar mesmo assim, race-safe).

---

## Deploy / Build pipeline

### Setup inicial (1x na VPS)

```bash
python deploy/ssh_exec.py "bash /opt/saas-prestadores/install_node.sh"
```

Instala Node 20 LTS via NodeSource (Debian/Ubuntu/CentOS/Rocky). Idempotente.

### Deploy contínuo

`deploy/deploy_saas.py` ganhou 2 etapas novas (entre `tailwind build` e `migrate`):

```
chatbot-builder npm ci      → npm ci --no-audit --no-fund --prefer-offline
chatbot-builder build       → npm run build (output em static/js/chatbot-builder/)
```

Skip com `--skip-chatbot-builder` em deploys que não tocam o frontend.

### Como o WhiteNoise serve

- `static/js/chatbot-builder/` é ignorado no `.gitignore` (bundle gerado no deploy).
- `collectstatic --noinput` copia para `staticfiles/js/chatbot-builder/`.
- `CompressedManifestStaticFilesStorage` re-hasheia + comprime (`.gz` siblings).
- Template usa `{% static 'js/chatbot-builder/main.js' %}` (Django resolve hash do manifest em prod).

---

## Como usar (perspectiva do usuário final)

1. **Listagem de fluxos:** `/chatbot/flows/` ganha botão de "Construtor visual"
   (ícone de cards empilhados) ao lado do botão de edição manual.
2. **Editar fluxo (form manual):** `/chatbot/flows/<pk>/edit/` agora tem botão
   topo "Abrir editor visual ↗" que dispara `POST /builder/init/` (cria draft
   convertido) e redireciona para `/builder/`.
3. **Construtor visual:** monta blocos arrastando da paleta, conecta handles,
   edita propriedades no painel direito. Autosave a cada 1.5s de inatividade.
4. **Validar:** botão Validar marca nós com erro (borda vermelha) e lista
   problemas no painel direito.
5. **Publicar:** botão Publicar exige fluxo válido. Após publish, o motor
   passa a usar `graph_json`. Editor manual vira read-only com banner
   "Este fluxo é gerenciado pelo construtor visual".

---

## Como adicionar novo tipo de bloco (4 lugares)

1. **`schemas/node_catalog.json`** — adicionar entrada com `type`, `data_fields`, `handles`, `status="active"`.
2. **`schemas/graph_v1.json`** — adicionar o `type` no enum de nodes.
3. **`flow_validator.py`** — se houver regra estrutural específica, criar
   função `_validate_<type>_handles()` e chamar em `_validate_node_data`.
4. **`flow_executor.py`** — adicionar handler do tipo em `_enter_node()`
   (envia mensagem? aguarda input? avança?).
5. **Frontend:** registrar componente customizado em `Canvas.tsx::nodeTypes`
   se precisar de UI especial (handles dinâmicos, preview customizado).
   Caso contrário, `GenericNode` já cobre.

---

## Testes (`apps/chatbot/tests/builder/`)

- `test_flow_validator.py` (21) — pipeline de validação
- `test_flow_converter.py` (8) — conversão legacy → graph_json
- `test_flow_executor_v2.py` (13) — motor v2 + despachador + persistência
- `test_api_endpoints.py` (15) — auth + tenant + limites + rate limit

**Suite total:** 467 (era 410 antes do RV06).

---

## Segurança & limites

| Item | Valor | Aplicado em |
|---|---|---|
| Tamanho máx. `graph_json` | 512 KB | `BuilderAPIView.json_body` (413 Payload Too Large) |
| Máx. nodes | 200 | `save` view + validator (422) |
| Máx. edges | 500 | `save` view + validator (422) |
| Máx. chars por field texto | 5000 | validator (FIELD_TOO_LONG) |
| API keys / secrets | tabela `ChatbotSecret` (Fernet) | nunca embed em graph_json |
| CSRF | obrigatório em POSTs | session middleware Django |
| Tenant isolation | `flow.empresa_id == request.empresa.id` | base view |
| Rate limit | 60 calls / 60s / user | `@rate_limit_per_user` |
| Audit | `ChatbotExecutionLog` | executor v2 |

Configurável via env: `CHATBOT_BUILDER_MAX_NODES`, `..._MAX_EDGES`,
`..._MAX_GRAPH_BYTES`, `..._RATE_LIMIT_CALLS`, `..._RATE_LIMIT_WINDOW`.

---

## Limitações abertas (MVP)

1. **`api_call` desabilitado** — V2 trará UI de gerenciamento de `ChatbotSecret`
2. **Sem simulador inline** no builder — V2 (botão "Testar")
3. **Sem undo/redo persistente** — React Flow tem undo nativo apenas em memória
4. **Sem templates pré-prontos** de fluxo — backlog
5. **Sem colaboração multi-user** simultânea — last-write-wins
6. **`graph_json` schema_version 1** — versionamento de schema preparado mas só 1 versão hoje

---

## Comandos operacionais

```bash
# Setup inicial (1x)
bash install_node.sh                    # local
python deploy/ssh_exec.py "bash /opt/saas-prestadores/install_node.sh"  # VPS

# Desenvolvimento frontend
cd frontend/chatbot-builder
npm install
npm run dev                                    # http://localhost:5173 (mock)
npm run typecheck
npm run build                                  # gera bundle

# Backend
python manage.py migrate                       # aplica 0011
python manage.py test apps                     # 467 testes
python manage.py collectstatic --noinput

# Deploy completo
python deploy/deploy_saas.py                   # inclui chatbot-builder build automaticamente

# Skip do build do frontend
python deploy/deploy_saas.py --skip-chatbot-builder
```

---

## Próximos passos (V2)

- Bloco `api_call` funcional + tela CRUD de `ChatbotSecret`
- Simulador inline (botão "Testar" no topbar)
- Templates pré-prontos (biblioteca de fluxos)
- Métricas de conversão por bloco
- A/B testing entre versões publicadas
- WhatsApp Cloud API oficial (atualmente Evolution)
- Dashboards de uso via `ChatbotExecutionLog`

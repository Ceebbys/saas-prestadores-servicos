# Arquitetura do ServiçoPro

## Visão Geral

Monólito Django multi-tenant com 10 apps, isolamento por empresa (tenant), HTMX para interatividade sem SPA, e pipeline de automação ponta a ponta.

## Multi-tenant

### Camada de Modelo

```
TimestampedModel (abstract)
  └── TenantOwnedModel (abstract)
        ├── empresa = FK(Empresa, CASCADE)
        ├── created_at (auto)
        └── updated_at (auto)
```

Todos os modelos de negócio herdam de `TenantOwnedModel`, garantindo que cada registro pertence a uma empresa.

### Camada de Middleware

`EmpresaMiddleware` (`apps.core.middleware`) seta `request.empresa` a partir de `request.user.active_empresa` em cada request autenticada.

### Camada de View

`EmpresaMixin` (`apps.core.mixins`) filtra o queryset por `empresa=request.empresa` e injeta `empresa` ao salvar formulários. Todas as 60+ views autenticadas usam este mixin.

## Grafo de Dependências entre Módulos

```
chatbot → crm → proposals → contracts → operations → finance
                    ↑                                    ↑
                automation ──────────────────────────────┘
```

O módulo `automation` orquestra o fluxo completo entre todos os outros módulos.

## Pipeline de Automação

5 passos encadeados, cada um com função dedicada em `apps/automation/services.py`:

| Passo | Função | Entrada | Saída |
|-------|--------|---------|-------|
| 1 | `create_lead_from_chatbot()` | ChatbotFlow + session_data | Lead (status=NOVO) |
| 2 | `create_proposal_from_lead()` | Lead + ProposalTemplate | Proposal (status=DRAFT) |
| 3 | `create_contract_from_proposal()` | Proposal + ContractTemplate | Contract (status=DRAFT) |
| 4 | `create_work_order_from_contract()` | Contract + ServiceType | WorkOrder (status=PENDING) |
| 5 | `create_billing_from_work_order()` | WorkOrder | FinancialEntry[] (status=PENDING) |

`run_full_pipeline()` executa todos os 5 passos com transições de status simuladas para demonstração.

## Idempotência

Cada passo do pipeline implementa verificação de duplicatas antes de criar:

| Passo | Estratégia |
|-------|-----------|
| Chatbot → Lead | `Lead.external_ref` = session_id (unique por empresa) |
| Lead → Proposta | `AutomationLog` com action=LEAD_TO_PROPOSAL e source=lead.pk |
| Proposta → Contrato | `Contract.filter(proposal=proposal)` |
| Contrato → OS | `WorkOrder.filter(contract=contract)` |
| OS → Financeiro | `FinancialEntry.filter(related_work_order=wo, auto_generated=True)` |

## Real vs Stub

| Funcionalidade | Estado | Detalhes |
|---------------|--------|----------|
| CRUD completo (10 módulos) | Real | Totalmente funcional |
| Multi-tenant isolation | Real | EmpresaMixin em todas as views |
| Pipeline de automação | Real | Todas as entidades criadas |
| Numeração sequencial | Real | PREFIX-YYYY-NNNN por empresa/ano |
| Geração de parcelas | Real | Divisão exata com ajuste na última |
| Templates com variáveis | Real | {cliente}, {valor}, {proposta} |
| WhatsApp Business API | Stub | Webhook aceita POST, retorna JSON |
| Pix QR Code | Stub | Payload simulado, pronto para PSP |
| Boleto bancário | Stub | Código de barras simulado |
| process_chatbot_response | Stub | Aguarda integração WhatsApp |

## Padrão de Services

Lógica de negócio vive em arquivos `services.py` por app:

- `apps/automation/services.py` — Orquestração do pipeline (6 funções)
- `apps/finance/services.py` — Geração de parcelas, Pix/boleto stubs
- `apps/chatbot/services.py` — Delegação para automation (create_lead_from_chatbot)

Regras:
- `@transaction.atomic` para consistência
- Verificação de idempotência antes de criar
- `AutomationLog` para rastreabilidade
- Empresa como argumento obrigatório

## Numeração Sequencial

`generate_number(empresa, prefix, model_class)` em `apps/core/utils.py`:

```
PROP-2026-0001  (Proposta)
CONT-2026-0001  (Contrato)
OS-2026-0001    (Ordem de Serviço)
```

Sequência por empresa e por ano, garantindo numeração independente entre tenants.

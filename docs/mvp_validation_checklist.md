# MVP Validation Checklist

Checklist de validação do hardening realizado no projeto ServiçoPro MVP.

## Bloco 1: Correções Funcionais Críticas

- [x] Finance "Ver vencidos" — filtro `?status=overdue` traduzido para `status=pending AND date < today`
- [x] Calendar meses em português — dict `MONTH_NAMES_PT` substitui `calendar.month_name`
- [x] Lead list — opções de filtro dinâmicas via `status_choices`/`source_choices` do context
- [x] Work order delete — `<form method="post">` substitui `hx-post` para redirect correto
- [x] Work order contract link clicável — `<a href>` para o detalhe do contrato
- [x] Lead source colors — 6 cores adicionadas: `site`, `indicacao`, `google`, `instagram`, `telefone`, `outro`
- [x] Proposal detail phone — filtro `|phone_format` aplicado

## Bloco 2: Segurança e Isolamento

- [x] Dashboard usa `EmpresaMixin` — consistente com todos os outros views
- [x] `ProposalCreateView.get_initial()` — valida que lead/opportunity pertencem à empresa
- [x] `ContractCreateView.get_initial()` — valida que lead pertence à empresa

## Bloco 3: Ações de Status e Completude

- [x] Work order status actions — botões Agendar/Iniciar/Concluir/Pausar/Cancelar/Retomar com validação de transição
- [x] Lead status action no detalhe — dropdown Alpine.js para mudar status
- [x] Contract cancel button — botão Cancelar para contratos sent/signed/active
- [x] Proposal edit condicional — botão Editar só aparece para draft/sent
- [x] Settings delete — 5 views de delete (ServiceType, PipelineStage, ProposalTemplate, ContractTemplate, FinancialCategory) com botões nas tabelas

## Bloco 4: Breadcrumbs e Navegação

- [x] `proposal_list.html` — Dashboard → Propostas
- [x] `contract_list.html` — Dashboard → Contratos
- [x] `work_order_list.html` — Dashboard → Ordens de Serviço
- [x] `entry_list.html` — Financeiro → Lançamentos
- [x] `calendar.html` — Dashboard → Calendário
- [x] `overview.html` — Dashboard → Financeiro
- [x] Settings sub-pages — já tinham breadcrumbs (confirmado)

### Revisão final — breadcrumbs adicionais encontrados e corrigidos

- [x] `lead_list.html` — Dashboard → Leads
- [x] `pipeline_board.html` — Dashboard → Pipeline
- [x] `settings/index.html` — Dashboard → Configurações
- [x] `operations/service_type_list.html` — Dashboard → Tipos de Serviço

## Bloco 5: Refinamento UI Premium

- [x] Dashboard pipeline progress bars — usa `total_opportunities` como base
- [x] Dashboard propostas aceitas recentes — nova seção com link e valor
- [x] Finance overview ações — coluna editar + marcar como pago nos lançamentos recentes
- [x] Work order detail checklist progress bar — barra visual com contagem x/y
- [x] Opportunity detail — propostas relacionadas do lead exibidas

## Riscos Conhecidos

1. **HTMX partial rendering** — Algumas views usam `HtmxResponseMixin` mas nem todas as ações (mark paid, status change) retornam partials. Funciona com redirects mas pode ser melhorado com swaps HTMX futuramente.
2. **PipelineStage delete** — Protegido por `PROTECT` constraint se houver oportunidades vinculadas. Mensagem de erro exibida ao usuário.
3. **Roles/permissions** — O MVP usa `EmpresaMixin` para isolamento por empresa mas não implementa granularidade por role (OWNER vs MEMBER). Todos os membros da empresa têm acesso igual.
4. **Busca textual** — Usa `icontains` simples. Para volume grande de dados, considerar `SearchVector`/`SearchRank` do PostgreSQL.

## Bloco 6: Chatbot

- [x] ChatbotFlow model com webhook_token UUID
- [x] ChatbotStep com 6 tipos (TEXT, CHOICE, EMAIL, PHONE, NAME, COMPANY)
- [x] ChatbotChoice com next_step navigation
- [x] ChatbotAction com triggers (ON_COMPLETE, ON_TIMEOUT, ON_KEYWORD)
- [x] CRUD completo de fluxos, passos e ações
- [x] Webhook endpoint com validação de token
- [x] process_chatbot_response stub preparado para WhatsApp Business API
- [x] create_lead_from_chatbot delega para automation.services
- [x] Sidebar com link Chatbot e active state

## Bloco 7: Automação

- [x] AutomationLog model com EntityType, Action, Status choices
- [x] create_lead_from_chatbot — idempotente via external_ref
- [x] create_proposal_from_lead — usa ProposalTemplate default com itens
- [x] create_contract_from_proposal — substituição de variáveis no template
- [x] create_work_order_from_contract — scheduled_date = now + 7 dias
- [x] create_billing_from_work_order — reutiliza generate_entries_from_proposal
- [x] run_full_pipeline — execução demo com transições de status
- [x] Pipeline Demo view com 6 cards visuais conectados
- [x] Log list view com filtros por ação/status e paginação
- [x] Seed data com 5 logs por empresa (25 total)

## Bloco 8: Hardening Final

- [x] 83 testes automatizados (models, tenant, pipeline, views)
- [x] Monkey-patch para compatibilidade Django 5.1 + Python 3.14
- [x] README.md com quick start, módulos e limitações
- [x] docs/architecture.md com pipeline, idempotência e real vs stub
- [x] smoke_test.md atualizado com seções Chatbot, Automação, Equipes
- [x] mvp_validation_checklist.md atualizado com Blocos 6-8
- [x] Senha corrigida no smoke_test.md (demo1234 → Demo123!)
- [x] Auditoria de 60+ views — todas com EmpresaMixin

## Próximos Passos Pós-MVP

- [ ] Implementar permissões granulares por role (OWNER, ADMIN, MANAGER, MEMBER)
- [ ] Adicionar soft-delete para entidades principais
- [ ] Notificações em tempo real (WebSocket ou polling)
- [ ] Export de relatórios (PDF, Excel)
- [ ] Integração com WhatsApp Business API (substituir stubs)
- [ ] Integração com gateway de pagamento (Pix real, boleto real)
- [ ] Multi-idioma (i18n)
- [ ] API REST para integrações externas
- [ ] Full-text search com PostgreSQL SearchVector

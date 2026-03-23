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

## Próximos Passos Pós-MVP

- [ ] Implementar permissões granulares por role (OWNER, ADMIN, MANAGER, MEMBER)
- [ ] Adicionar soft-delete para entidades principais
- [ ] Implementar auditoria/log de ações
- [ ] Notificações em tempo real (WebSocket ou polling)
- [ ] Export de relatórios (PDF, Excel)
- [ ] Integração com gateway de pagamento
- [ ] Multi-idioma (i18n)
- [ ] API REST para integrações externas

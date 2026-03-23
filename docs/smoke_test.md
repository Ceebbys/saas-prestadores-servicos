# Smoke Test Guide

Roteiro rápido de teste manual para validação do ServiçoPro MVP.

## Pré-requisitos

```bash
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```

Acesse: http://127.0.0.1:8000

## Contas de Teste

| Empresa | Email | Senha |
|---------|-------|-------|
| GeoPrime Topografia | `admin@geoprime-topografia.demo` | `Demo123!` |
| Campo Forte Consultoria | `admin@campo-forte-consultoria.demo` | `Demo123!` |

---

## 1. Autenticação

- [ ] Login com `admin@geoprime-topografia.demo` / `demo1234`
- [ ] Dashboard carrega com métricas, leads recentes e OS próximas
- [ ] Sidebar navega para todos os módulos
- [ ] Logout funciona
- [ ] Login com `admin@campo-forte-consultoria.demo` — dados diferentes

## 2. Dashboard

- [ ] Cards de estatísticas exibem valores (leads, propostas, OS)
- [ ] Financeiro do mês mostra receitas, despesas e saldo
- [ ] Pipeline mostra etapas com barras proporcionais
- [ ] Leads recentes com badge de status
- [ ] Próximas OS com data e status
- [ ] Propostas aceitas recentes com valor (se houver)
- [ ] Ações rápidas funcionam (links para criar lead, proposta, OS, lançamento)

## 3. CRM — Leads

- [ ] Lista de leads carrega com paginação
- [ ] Filtros por status e source funcionam (opções dinâmicas)
- [ ] Busca por nome/empresa funciona
- [ ] Criar novo lead — formulário salva
- [ ] Detalhe do lead mostra informações completas
- [ ] Badge de source tem cor apropriada
- [ ] Mudar status do lead via dropdown funciona
- [ ] Editar lead funciona
- [ ] Excluir lead funciona
- [ ] Breadcrumbs presentes

## 4. CRM — Pipeline

- [ ] Board kanban carrega com colunas por etapa
- [ ] Criar oportunidade funciona
- [ ] Detalhe da oportunidade mostra progresso no pipeline
- [ ] Mover oportunidade entre etapas funciona
- [ ] Marcar como ganha/perdida funciona
- [ ] Propostas relacionadas do lead são exibidas
- [ ] Excluir oportunidade funciona

## 5. Propostas

- [ ] Lista carrega com paginação
- [ ] Breadcrumb Dashboard → Propostas
- [ ] Filtro por status funciona
- [ ] Criar proposta (com ou sem lead pré-selecionado)
- [ ] Detalhe mostra dados, itens e valor total
- [ ] Telefone do lead formatado corretamente
- [ ] Botão Editar só aparece para draft/sent
- [ ] Transições de status: draft → sent → viewed → accepted/rejected
- [ ] Proposta aceita/rejeitada não mostra botão Editar

## 6. Contratos

- [ ] Lista carrega com paginação
- [ ] Breadcrumb Dashboard → Contratos
- [ ] Criar contrato funciona
- [ ] Detalhe mostra dados e status
- [ ] Transições: draft → sent → signed → active → completed
- [ ] Botão Cancelar aparece para sent/signed/active
- [ ] Cancelar contrato funciona

## 7. Ordens de Serviço

- [ ] Lista carrega com paginação
- [ ] Breadcrumb Dashboard → Ordens de Serviço
- [ ] Criar OS funciona
- [ ] Detalhe mostra informações, checklist, observações
- [ ] Link do contrato é clicável
- [ ] Checklist progress bar mostra x/y concluídos
- [ ] Botões de status: Agendar → Iniciar → Concluir
- [ ] Pausar e Retomar funcionam
- [ ] Cancelar funciona (com confirmação)
- [ ] Excluir funciona (redirect correto, sem problema HTMX)
- [ ] Toggle checklist item funciona

## 8. Calendário

- [ ] Calendário carrega com meses em **português**
- [ ] Breadcrumb Dashboard → Calendário
- [ ] Navegação entre meses funciona
- [ ] OS aparecem no dia correto
- [ ] Click na OS navega para detalhe

## 9. Financeiro

- [ ] Overview carrega com cards de resumo
- [ ] Breadcrumb Dashboard → Financeiro
- [ ] Alerta de vencidos aparece se houver lançamentos vencidos
- [ ] "Ver vencidos" filtra corretamente (pendentes com data passada)
- [ ] Lançamentos recentes mostram ações (editar, marcar pago)
- [ ] Marcar como pago funciona
- [ ] Lista de lançamentos carrega
- [ ] Breadcrumb Financeiro → Lançamentos
- [ ] Filtros por tipo, status, categoria, datas funcionam
- [ ] Criar lançamento funciona
- [ ] Editar lançamento funciona

## 10. Configurações

- [ ] Index mostra cards para todos os tipos
- [ ] Tipos de Serviço — listar, criar, editar, **excluir**
- [ ] Etapas do Pipeline — listar, criar, editar, **excluir** (com proteção se houver oportunidades)
- [ ] Templates de Proposta — listar, criar, editar, **excluir**
- [ ] Templates de Contrato — listar, criar, editar, **excluir**
- [ ] Categorias Financeiras — listar, criar, editar, **excluir**
- [ ] Breadcrumbs presentes em todas as sub-páginas

## 11. Isolamento Multiempresa

- [ ] Login como GeoPrime — anotar quantidade de leads, propostas, OS
- [ ] Login como Campo Forte — verificar que os dados são **completamente diferentes**
- [ ] Tentar acessar URL de recurso da outra empresa (ex: `/leads/1/`) — deve retornar 404
- [ ] Criar recurso em Campo Forte — verificar que não aparece em GeoPrime

## 12. UX/UI Geral

- [ ] Mensagens de sucesso/erro aparecem após ações
- [ ] Empty states exibidos quando não há dados
- [ ] Responsividade — sidebar colapsa no mobile
- [ ] Badges de status consistentes em todos os módulos
- [ ] Tabelas responsivas (colunas ocultas em telas menores)

---

## Validação Rápida (Comandos)

```bash
# Verificar sistema
python manage.py check

# Verificar migrações pendentes
python manage.py showmigrations | grep "\[ \]"

# Rodar testes (se existirem)
python manage.py test

# Popular dados demo
python manage.py seed_demo_data

# Resetar dados demo
python manage.py reset_demo_data
```

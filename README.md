# ServiçoPro: SaaS para Prestadores de Serviços

Plataforma web multi-tenant para gestão completa de empresas prestadoras de serviços. Cobre desde a captação de leads via chatbot até o faturamento, passando por propostas, contratos e ordens de serviço.

## Tech Stack

- **Backend:** Django 5.1, Python 3.14
- **Frontend:** HTMX, Alpine.js, Tailwind CSS
- **Database:** PostgreSQL (SQLite em dev)
- **Deploy:** Render (Gunicorn + WhiteNoise)

## Módulos

| App | Descrição |
|-----|-----------|
| `accounts` | Autenticação por email, empresas (tenants), memberships |
| `dashboard` | Dashboard com métricas, pipeline, leads recentes, OS próximas |
| `crm` | Leads, pipeline kanban, oportunidades |
| `proposals` | Propostas com itens, templates, cálculo automático |
| `contracts` | Contratos com templates, substituição de variáveis |
| `operations` | Ordens de serviço, checklist, equipes, calendário |
| `finance` | Lançamentos financeiros, parcelas, categorias, contas bancárias |
| `chatbot` | Fluxos conversacionais, webhook para WhatsApp Business API |
| `automation` | Pipeline automatizado ponta a ponta com rastreabilidade |
| `settings_app` | Configurações por empresa (tipos, templates, categorias, equipes) |

## Arquitetura

- **Multi-tenant:** `TenantOwnedModel` (FK empresa), `EmpresaMixin` (filtra queryset por empresa), `EmpresaMiddleware` (seta `request.empresa`)
- **Services pattern:** Lógica de negócio em `services.py` (idempotente, `@transaction.atomic`)
- **Numeração sequencial:** `PREFIX-YYYY-NNNN` por empresa/ano (propostas, contratos, OS)
- **Pipeline de automação:** Chatbot → Lead → Proposta → Contrato → OS → Financeiro

## Quick Start

```bash
git clone <repo-url>
cd saas_prestadores_servicos

python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

pip install -r requirements.txt

# Configurar variáveis (ou usar SQLite padrão)
export USE_SQLITE=1  # para dev rápido sem PostgreSQL

python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```

Acesse http://127.0.0.1:8000 com:
- **Email:** `admin@geoprime-topografia.demo`
- **Senha:** `Demo123!`

## Testes

```bash
python manage.py test apps.core.tests -v2
```

83 testes cobrindo: criação de modelos (19), isolamento multi-tenant (10), pipeline de automação (10), acesso a views (44).

## Documentação

- [`docs/smoke_test.md`](docs/smoke_test.md) — Roteiro de teste manual
- [`docs/architecture.md`](docs/architecture.md) — Arquitetura e pipeline
- [`docs/mvp_validation_checklist.md`](docs/mvp_validation_checklist.md) — Checklist de validação
- [`docs/demo_scenarios.md`](docs/demo_scenarios.md) — Cenários de demonstração
- [`docs/deploy_render.md`](docs/deploy_render.md) — Guia de deploy no Render

## Limitações Conhecidas

- **Permissões por role:** Todos os membros da empresa têm acesso igual (sem granularidade OWNER/ADMIN/MEMBER)
- **Busca textual:** Usa `icontains` simples (sem full-text search)
- **Integrações:** WhatsApp Business API, Pix e boleto são stubs preparados para conexão futura
- **Relatórios:** Sem export PDF/Excel no MVP

# Deploy no Render — ServiçoPro

## Visão Geral

O ServiçoPro é deployado no Render como um **Web Service** com **PostgreSQL** gerenciado. A stack é:

| Componente | Tecnologia |
|---|---|
| Framework | Django 5.1 |
| Frontend | HTMX + Tailwind CSS |
| Banco | PostgreSQL (Render managed) |
| WSGI Server | Gunicorn |
| Static Files | WhiteNoise |
| Python | 3.12 |

### Arquivos de deploy

| Arquivo | Função |
|---|---|
| `render.yaml` | Blueprint — define serviços, banco, variáveis |
| `build.sh` | Script de build — Tailwind, deps, migrate, collectstatic |
| `runtime.txt` | Fixa versão do Python |
| `requirements/base.txt` | Dependências de produção |
| `config/settings/prod.py` | Settings de produção |

### Estrutura CSS / Tailwind

```
src/css/input.css          ← Fonte Tailwind (NÃO servido como static)
static/css/output.css      ← CSS compilado final (servido pelo WhiteNoise)
templates/base.html        ← Referencia {% static 'css/output.css' %}
```

O `input.css` contém `@import "tailwindcss"` e diretivas `@source` — ele NÃO pode estar dentro de `static/` porque o WhiteNoise tenta processá-lo como CSS final e falha ao resolver o import.

**Build local (Windows):**
```bash
./tailwindcss.exe -i src/css/input.css -o static/css/output.css --minify
```

**Build no Render (Linux):**
O `build.sh` baixa automaticamente o binário Tailwind CLI para Linux e compila antes do `collectstatic`.

---

## Variáveis de Ambiente

| Variável | Valor | Nota |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` | Definido no render.yaml |
| `SECRET_KEY` | *(auto-gerado)* | Render gera automaticamente |
| `DATABASE_URL` | *(auto-preenchido)* | Vinculado ao banco PostgreSQL |
| `ALLOWED_HOSTS` | `.onrender.com` | Definido no render.yaml |
| `PYTHON_VERSION` | `3.12.10` | Definido no render.yaml |
| `DEMO_SEED` | `true` | Permite rodar seed no shell |
| `RENDER_EXTERNAL_HOSTNAME` | *(auto)* | Render define automaticamente |

> `CSRF_TRUSTED_ORIGINS` é configurado automaticamente via `RENDER_EXTERNAL_HOSTNAME`.

---

## Como Fazer o Deploy

### Opção 1: Blueprint (Recomendado)

1. Faça push do repositório para o GitHub
2. Acesse [dashboard.render.com](https://dashboard.render.com)
3. Clique em **New → Blueprint**
4. Conecte o repositório
5. O Render lê o `render.yaml` e cria automaticamente:
   - Web Service `saas-prestadores-servicos`
   - PostgreSQL `saas-prestadores-db`
   - Todas as variáveis de ambiente
6. Clique em **Apply** e aguarde o deploy

### Opção 2: Manual

1. Crie um **PostgreSQL** no Render (plano Free)
2. Crie um **Web Service** apontando para o repositório
3. Configure:
   - **Build Command**: `./build.sh`
   - **Start Command**: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - **Health Check Path**: `/healthz/`
4. Adicione as variáveis de ambiente listadas acima
5. Vincule o `DATABASE_URL` ao PostgreSQL criado

---

## Pós-Deploy: Migrations

As migrations rodam automaticamente no `build.sh` a cada deploy. Se precisar rodar manualmente:

```bash
# No Render Shell do Web Service:
python manage.py migrate
```

---

## Pós-Deploy: Criar Superuser

```bash
# No Render Shell:
python manage.py createsuperuser
```

---

## Pós-Deploy: Popular Base Demo

```bash
# No Render Shell:
python manage.py seed_demo_data
```

Isso cria 5 empresas demo com dados completos:

| Empresa | Login | Senha |
|---|---|---|
| GeoPrime Topografia | `admin@geoprime-topografia.demo` | `Demo123!` |
| Campo Forte Consultoria | `admin@campo-forte-consultoria.demo` | `Demo123!` |

> Cada empresa tem: leads, pipeline, propostas, contratos, ordens de serviço e lançamentos financeiros.

### Resetar e Re-Popular

```bash
# No Render Shell:
DEMO_SEED=true python manage.py reset_demo_data
```

Ou apenas limpar sem re-popular:

```bash
DEMO_SEED=true python manage.py reset_demo_data --no-reseed
```

---

## Limitações do Render Free

| Limitação | Impacto | Solução |
|---|---|---|
| **Spin-down após 15min** | Primeira requisição leva ~30s | Normal para demo; upgrade para plano pago elimina |
| **PostgreSQL free expira em 90 dias** | Banco é deletado | Recriar banco e re-popular com `seed_demo_data` |
| **Filesystem efêmero** | Uploads de media são perdidos no redeploy | Para demo, sem impacto (não há uploads críticos). Para produção real, usar S3/Cloudflare R2 |
| **512 MB RAM** | Suficiente para demo | Monitorar se necessário |
| **750 horas/mês** | Suficiente para 1 serviço | OK para demo |

### Media Files

O Render Free tem filesystem efêmero — arquivos em `media/` são perdidos a cada deploy. Para um ambiente de **demonstração**, isso não é problema porque:

- O sistema funciona sem uploads obrigatórios
- Dados demo são re-criáveis via `seed_demo_data`

Para **produção real**, configure um serviço de storage externo (AWS S3, Cloudflare R2, etc.) e use `django-storages`.

---

## Checklist Final Pós-Deploy

```
[ ] Deploy completou sem erros no Render Dashboard
[ ] Acessar https://seu-app.onrender.com/healthz/ → {"status": "ok"}
[ ] Acessar a página de login
[ ] Rodar seed_demo_data no Shell
[ ] Login com admin@geoprime-topografia.demo / Demo123!
[ ] Navegar: Dashboard → Leads → Pipeline → Propostas → Contratos → OS → Financeiro → Configurações
[ ] Verificar que CSS/JS carregam corretamente (WhiteNoise)
[ ] Verificar breadcrumbs em todas as páginas
[ ] Logout e login com admin@campo-forte-consultoria.demo → dados diferentes (isolamento)
[ ] Acessar /admin/ com superuser (se criado)
```

---

## Troubleshooting

### collectstatic falha com erro de @import "tailwindcss"
- O arquivo `input.css` (fonte Tailwind) NÃO deve estar em `static/css/`
- Ele deve ficar em `src/css/input.css`
- O `build.sh` compila para `static/css/output.css` antes do `collectstatic`

### CSS não carrega / página sem estilo
- Verifique se `collectstatic` rodou no build (ver logs do deploy)
- Verifique se `WhiteNoise` está no MIDDLEWARE
- Verifique nos logs se o Tailwind CLI compilou com sucesso

### 500 Internal Server Error
- Verifique os logs no Render Dashboard
- Confirme que `DATABASE_URL` está vinculado
- Confirme que migrations rodaram

### CSRF verification failed
- Verifique que `RENDER_EXTERNAL_HOSTNAME` está definido (Render faz automaticamente)
- Se usando domínio custom, adicione-o em `CSRF_TRUSTED_ORIGINS`

### seed_demo_data bloqueado
- No Render Shell, rode com: `DEMO_SEED=true python manage.py seed_demo_data --force`
- Ou verifique que `DEMO_SEED=true` está nas variáveis de ambiente do serviço

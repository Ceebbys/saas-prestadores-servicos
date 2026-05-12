# Deploy das melhorias da Inbox (Fases 2-5)

Este documento cobre o que precisa rodar na VPS para que as 4 melhorias da
inbox unificada funcionem em produção:

- **Fase 2** — IMAP polling per tenant
- **Fase 3** — Django Channels + WebSocket (live inbox)
- **Fase 4** — Notificações (in-app + Web Push + email digest)
- **Fase 5** — Templates de resposta rápida

## Sumário do que precisa ser feito na VPS

```bash
# 1. Atualizar dependências Python
pip install -r requirements/base.txt

# 2. Aplicar migrations
python manage.py migrate

# 3. Gerar par de chaves VAPID (para Web Push)
python manage.py generate_vapid
# Cola VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY no .env

# 4. Restart serviços
systemctl restart saas-prestadores-asgi.service  # ASGI (Daphne) — NOVO
systemctl restart saas-celery-worker.service
systemctl restart saas-celery-beat.service       # IMAP poller + digest

# 5. Caddy reload (para proxy de ws://)
systemctl reload caddy
```

## Detalhes por fase

### Fase 2 — IMAP polling

**O que muda:**
- Celery beat dispara `apps.communications.tasks.poll_email_inboxes` a cada 5min
- Lê IMAP de tenants com `EmpresaEmailConfig.imap_active=True`
- Materializa e-mails em `ConversationMessage(channel='email', direction='inbound')`

**Pré-requisitos:**
- Celery worker rodando (já existia)
- Celery beat rodando (já existia)
- Redis rodando (broker)
- `EmpresaEmailConfig.imap_*` campos preenchidos pelo tenant via `/settings/email/`

**Como testar:**
1. Em uma empresa de testes, configurar IMAP (imap.gmail.com:993, SSL, INBOX) com app-password
2. Clicar "Testar conexão IMAP" → deve mostrar verde
3. Aguardar 5min OU disparar manualmente: `celery -A config call apps.communications.tasks.poll_email_inboxes`
4. Conferir `ConversationMessage` no admin Django

### Fase 3 — Channels + WebSocket

**O que muda:**
- Servidor ASGI (Daphne) substitui ou roda em paralelo com Gunicorn (WSGI)
- WebSocket endpoints `/ws/inbox/` e `/ws/notifications/`
- Channel layer usa Redis em produção (`CHANNELS_REDIS_URL`)
- HTML adiciona `<body data-realtime-enabled="true">` + `static/js/realtime.js`

**Necessário:**
1. **systemd unit Daphne** — substituir Gunicorn por Daphne (ou rodar paralelo)

```ini
# /etc/systemd/system/saas-prestadores-asgi.service
[Unit]
Description=ServiçoPro ASGI (Daphne)
After=network.target redis.service

[Service]
Type=simple
User=saas
Group=saas
WorkingDirectory=/opt/saas-prestadores
EnvironmentFile=/opt/saas-prestadores/.env
ExecStart=/opt/saas-prestadores/venv/bin/daphne \
    -b 127.0.0.1 -p 8001 \
    --proxy-headers \
    config.asgi:application
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

2. **Caddy** — adicionar proxy WS

```caddy
servicos.cebs-server.cloud {
    # HTTP/HTTPS normal vai pro Gunicorn (WSGI) na porta 8000
    reverse_proxy /static/* localhost:8000
    reverse_proxy /media/* localhost:8000

    # WebSocket (ws://) → Daphne (ASGI) na porta 8001
    @websocket {
        header Connection *Upgrade*
        header Upgrade websocket
    }
    reverse_proxy @websocket localhost:8001

    # Tudo mais (HTTP) → Daphne (ele também serve HTTP normal)
    reverse_proxy localhost:8001
}
```

Alternativa mais simples — Daphne atende TUDO (HTTP + WS):

```caddy
servicos.cebs-server.cloud {
    reverse_proxy localhost:8001
}
```

E desliga Gunicorn (`systemctl disable --now saas-prestadores.service`).

3. **`.env`** — adicionar:
```bash
REDIS_URL=redis://localhost:6379/0          # já existia para Celery
CHANNELS_REDIS_URL=redis://localhost:6379/1  # opcional; usa REDIS_URL se vazio
CACHE_REDIS_URL=redis://localhost:6379/2     # opcional; usa REDIS_URL se vazio
```

**Como testar:**
1. Acessar inbox em duas abas/browsers diferentes
2. Enviar mensagem WhatsApp para o tenant
3. Ambas as abas devem atualizar em <1s sem F5
4. Console do browser: `wss://servicos.cebs-server.cloud/ws/inbox/` conectado

### Fase 4 — Notificações

**O que muda:**
- Bell no topbar com badge de não-lidas
- Notificações in-app criadas automaticamente em:
  - Nova mensagem inbound (notifica `conversation.assigned_to`)
  - Conversa atribuída a outro user
- Web Push para browser fora da página (requires VAPID)
- Email digest diário às 8h via Celery beat

**Necessário:**
1. **Gerar VAPID keys** (1ª vez apenas):
```bash
python manage.py generate_vapid
# Cola output no .env: VAPID_PUBLIC_KEY=... VAPID_PRIVATE_KEY=...
```

2. **`.env`** — adicionar:
```bash
VAPID_PUBLIC_KEY=BL9...
VAPID_PRIVATE_KEY=mj-...
VAPID_CONTACT_EMAIL=admin@cebs-server.cloud
```

3. **Service Worker** está em `static/js/service-worker.js` — colectstatic distribui automaticamente.

4. **Celery beat** — task `send_daily_digest` é registrada em `config/celery.py`:
```python
"send-daily-digest-8am": {
    "task": "apps.communications.tasks.send_daily_digest",
    "schedule": crontab(hour=8, minute=0),
},
```

**Como testar:**
1. Atribuir conversa para um colega → ele vê badge no bell + dropdown HTMX
2. Em outro browser/incógnito, com permissão de notificação ativa, clicar "Ativar notificações" → recebe push
3. Aguardar 24h sem ler → digest por e-mail chega às 8h (ou testar manual:
   `celery -A config call apps.communications.tasks.send_daily_digest`)

### Fase 5 — Templates de resposta rápida

**O que muda:**
- Nova tela `/inbox/templates/` para CRUD
- Composer da inbox aceita `/` para abrir dropdown com templates
- Variáveis: `{{ lead.name }}`, `{{ empresa.name }}`, etc.

**Pré-requisitos:**
- Jinja2 instalado (vem com Django, sem nova dep)

**Como testar:**
1. Criar template em `/inbox/templates/create/` com conteúdo `Olá {{ lead.name }}!`
2. Abrir uma conversa, digitar `/` no composer → dropdown abre
3. Selecionar template → textarea recebe `Olá <Nome do Lead>!`
4. Enviar normalmente

## Rollback

Cada fase é independente. Em ordem inversa de impacto:

1. **Fase 2** — para desligar IMAP: setar `imap_active=False` no admin (por tenant) OU remover beat entry `poll-email-inboxes-every-5-min`.
2. **Fase 3** — para desligar Channels: voltar Gunicorn, remover Daphne service. WebSocket fica indisponível mas HTTP continua. Polling HTMX (30s fallback) ainda funciona.
3. **Fase 4** — para desligar Push: remover `VAPID_*` do .env. Bell + in-app continuam funcionando, só push browser pára.
4. **Fase 5** — para desligar templates: feature flag não existe; basta apagar/desativar (`is_active=False`) os templates.

## Monitoramento

Logs importantes (via journalctl):

```bash
# IMAP poller
journalctl -u saas-celery-beat -f | grep -E "poll_email_inboxes|imap_"

# Channels
journalctl -u saas-prestadores-asgi -f | grep -E "websocket|channels"

# Notificações
journalctl -u saas-prestadores-asgi -f | grep -E "notification|push"
```

Métricas via admin Django:
- `/admin/communications/conversationmessage/` — volume de mensagens por canal
- `/admin/communications/notification/` — notificações criadas / lidas
- `/admin/accounts/empresaemailconfig/` — status do `imap_last_poll_*`

## Conta de testes (para QA)

```bash
ssh saas@2.24.200.251
cd /opt/saas-prestadores
source venv/bin/activate
python manage.py shell
>>> # Criar notif manual
>>> from apps.accounts.models import User
>>> from apps.communications.notifications import notify
>>> from apps.communications.models import Notification
>>> u = User.objects.get(email="ceebbys@gmail.com")
>>> notify(u, type=Notification.Type.SYSTEM, title="Teste manual", body="Funcionando!")
```

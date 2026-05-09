# RV04 — SMTP por tenant + Soft-delete + GTK Windows

Resolve duas das limitações documentadas no RV03.

---

## RV04-A — SMTP por tenant

**Problema:** todos os e-mails saíam do mesmo SMTP global, com remetente da plataforma. Cliente final percebia falta de personalização.

**Solução:** modelo `EmpresaEmailConfig` (OneToOne com `Empresa`) com host, port, username, senha (criptografada via Fernet), use_tls/ssl, from_email, from_name, is_active. `apps/proposals/services/email.py` resolve em duas camadas:

1. `EmpresaEmailConfig` ativa → SMTP do tenant + remetente da empresa
2. Fallback → SMTP global do `settings.py`

### Arquivos novos
- `apps/core/encryption.py` — wrapper de Fernet, lê `settings.FERNET_KEY` (com fallback derivado de `SECRET_KEY` apenas em DEBUG)
- `apps/accounts/models.py::EmpresaEmailConfig`
- `apps/accounts/migrations/0002_empresa_email_config.py`
- `apps/accounts/tests/test_email_config.py` — 9 testes
- `apps/settings_app/forms.py::EmpresaEmailConfigForm` (senha write-only)
- `apps/settings_app/views.py::EmailConfigView` + `EmailConfigTestView`
- `templates/settings/email_config.html`

### Configurar em produção

1. **Gerar uma chave Fernet (uma vez, persistente):**
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   # → cole no .env como FERNET_KEY=<valor>
   ```
2. **Usuário final** acessa `Configurações > E-mail (SMTP)`, preenche:
   - Servidor (ex.: `smtp.gmail.com`)
   - Porta (587 TLS / 465 SSL)
   - Usuário + senha de app (Gmail/Outlook)
   - From e-mail + nome de exibição
   - Marca "Ativa"
3. Botão **"Testar conexão"** envia e-mail de teste para o usuário logado.
4. A partir desse momento, propostas saem do SMTP da empresa.

### Limitações
- A chave Fernet precisa ser persistente em backups: **se perder a chave, perde todas as senhas SMTP** dos tenants.
- Senhas só podem ser RE-criadas, não recuperadas (write-only no form).

---

## RV04-B — Soft-delete em Proposal

**Problema:** exclusão era definitiva, sem rollback. Erro humano custava caro.

**Solução:** mixin `SoftDeletableModel` em `apps/core/models.py`:
- `deleted_at` (DateTime, indexado, default null)
- Manager default `objects` filtra `deleted_at__isnull=True`
- Manager paralelo `all_objects` retorna tudo
- `instance.delete()` faz soft-delete; `instance.hard_delete()` força exclusão real
- `instance.restore()` limpa `deleted_at`

Aplicado em `Proposal`. Outros modelos podem herdar do mixin no futuro.

### Arquivos novos/alterados
- `apps/core/models.py` — `SoftDeletableModel`, `SoftDeleteManager`, `SoftDeleteAllManager`, `SoftDeleteQuerySet`
- `apps/proposals/models.py::Proposal` — passa a herdar `SoftDeletableModel`
- `apps/proposals/migrations/0008_proposal_soft_delete.py`
- `apps/proposals/views.py` — `ProposalDeleteView` agora soft-delete; `ProposalTrashView`, `ProposalRestoreView`, `ProposalHardDeleteView` (novos)
- `apps/proposals/management/commands/purge_deleted_proposals.py`
- `templates/proposals/proposal_trash.html`
- `apps/proposals/tests/test_soft_delete.py` — 11 testes

### Como usar (cliente final do SaaS)

- **Excluir** uma proposta no detalhe → vai para a lixeira (não some do banco)
- Listagem de propostas tem botão **Lixeira** no canto superior direito
- Na lixeira: **restaurar** ou **excluir definitivamente** (com confirmação extra)
- Em produção, agendar **cron** para purga automática:
  ```cron
  # Diariamente às 03:00, hard-delete propostas na lixeira há mais de 60 dias
  0 3 * * * cd /opt/saas-prestadores && DJANGO_SETTINGS_MODULE=config.settings.prod \
            ./venv/bin/python manage.py purge_deleted_proposals --days 60
  ```
  Ou colocar como task Celery beat em `config/celery.py`.

### Auditoria
Cada operação gera entry em `AutomationLog`:
- `event=proposal_deleted` (soft-delete inicial)
- `event=proposal_restored`
- `event=proposal_hard_deleted` (manual da lixeira)
- `event=proposal_purged_from_trash` (cron automático)

---

## RV04-C — GTK no Windows (PDF local)

WeasyPrint precisa de GTK Runtime no Windows para gerar PDF localmente. Em
produção (Linux) não há esse problema.

### Opção 1 — GTK Runtime Installer (recomendado, ~5 min)

1. Baixar: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
   - Pegar a release mais recente, arquivo `gtk3-runtime-X.X.X-X-ts-win64.exe`
2. Executar como administrador. Aceitar defaults (instala em `C:\Program Files\GTK3-Runtime Win64\`).
3. Marcar a opção **"Set up PATH environment variable"** durante a instalação.
4. **Reabrir o terminal** (ou reiniciar o VS Code / Claude Code) — variáveis de ambiente só carregam em novos processos.
5. Testar:
   ```bash
   python -c "import weasyprint; print(weasyprint.HTML(string='<p>ok</p>').write_pdf()[:8])"
   # → b'%PDF-1.7\n' = OK
   ```

### Opção 2 — WSL2 (se já tem)

```bash
wsl
sudo apt-get update && sudo apt-get install -y libgobject-2.0-0 libcairo2 libpango-1.0-0
cd /mnt/c/Users/MyPC/Documents/Development/saas_prestadores_servicos
python3 manage.py runserver
```

### Opção 3 — Docker dev (se preferir isolar)

Adicione `Dockerfile.dev` baseado em `python:3.12-slim` com `apt-get install libgobject-2.0-0 libpango-1.0-0 libcairo2 libpangoft2-1.0-0` e `docker-compose.dev.yml`. Já tem GTK pré-instalado.

### Workaround sem GTK (se não conseguir instalar)

- O preview HTML continua funcionando localmente (`/proposals/<id>/preview/`)
- DOCX continua funcionando (não depende de WeasyPrint)
- PDF funciona normalmente em produção (Linux)
- Testes mockam `render_proposal_pdf` automaticamente

---

## Comandos operacionais

```bash
# Instalar dependências (cryptography já estava, sem novos pacotes)
pip install -r requirements/base.txt

# Aplicar migrations
python manage.py migrate

# Gerar Fernet key (uma vez, em deploy)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → adicionar ao .env como FERNET_KEY=<valor>

# Coletar estáticos
python manage.py collectstatic --noinput

# Rodar testes
python manage.py test apps -v 2
# → 302/302 passando

# Purga manual de lixeira (dry-run)
python manage.py purge_deleted_proposals --days 60 --dry-run
```

---

## Próximos passos (limitações ainda abertas)

- **DOCX rich formatting** (RV03 #3) → integrar `pypandoc` se feedback de cliente reclamar
- **WhatsApp Cloud API oficial** (RV03 #2) → migrar provider quando volume justificar
- **Soft-delete em outros modelos** → expandir gradualmente para `Lead`, `Contract`, etc.
- **SMTP por tenant em outros canais** → password reset ainda usa SMTP global; estender se necessário

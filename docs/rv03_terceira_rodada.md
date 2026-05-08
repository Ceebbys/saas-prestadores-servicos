# RV03 — Terceira Rodada de Correções e Melhorias

Documento de handover. Cobre as 7 frentes implementadas, comandos de operação e
as limitações conhecidas. Para o plano detalhado, ver
`.claude/plans/c-users-mypc-downloads-terceira-rodada-vast-pearl.md`.

---

## Resumo do que foi alterado

| # | Frente | Status | Notas |
|---|--------|--------|-------|
| 1 | Chatbot — mensagem oculta removida + botão Salvar no rodapé | ✅ | Migration `chatbot/0007` |
| 2 | Chatbot — hierarquia visual (1, 1.1, 1.2…) | ✅ | Migration `chatbot/0008` |
| 3 | Propostas — logo + editor rich-text (Quill) | ✅ | Migration `proposals/0004` |
| 4 | Propostas — Preview, PDF (WeasyPrint), DOCX (docxtpl) | ✅ | Sem migração |
| 5 | Propostas — status editável + exclusão com auditoria | ✅ | Migration `proposals/0005` |
| 6 | Propostas — envio por e-mail e WhatsApp | ✅ | Migration `proposals/0006` |
| 7 | Pipeline triggers (regras configuráveis) | ✅ | Migration `automation/0002` |
| 8 | Serviços Pré-Fixados (estende ServiceType) | ✅ | Migration `operations/0004` |
| 9 | Integrações serviço ↔ chatbot/lead/proposta | ✅ | Migrations `chatbot/0009`, `crm/0009`, `proposals/0007` |

**Suite de testes:** 282/282 passando (`python manage.py test apps`).

---

## Como usar (cliente final do SaaS)

### 1. Configurar mensagem de encerramento do chatbot

Editar fluxo → seção **Encerramento**:

- ✅ Marcar **"Enviar mensagem ao concluir"** se quiser texto final
- Editar livremente o texto (em branco = nada enviado)
- ⚠️ Por padrão, fluxos novos não enviam mensagem oculta

### 2. Organizar etapas do chatbot por hierarquia

- Cada etapa pode ter um **pai** (FK para outra etapa do mesmo fluxo)
- **Subordem** define a posição entre irmãos do mesmo pai
- Códigos hierárquicos (`1`, `1.1`, `1.2`, `2`, `2.1`) são **calculados automaticamente**
- A engine continua roteando via `Próxima etapa` (`next_step`) — hierarquia é puramente visual

### 3. Cadastrar Serviços Pré-Fixados

Sidebar → **Catálogo > Serviços Pré-Fixados** (ou **Configurações > Serviços Pré-Fixados**):

Campos:
- Nome, código (opcional), categoria, tags
- **Preço padrão** (decimal BR)
- **Prazo padrão (dias)**
- **Descrição padrão (rich)** — usada em propostas
- **Modelo de proposta padrão** (FK)
- **Modelo de contrato padrão** (FK)
- **Pipeline padrão + etapa padrão** (validados — etapa precisa pertencer ao pipeline)
- Observações internas, ativo/inativo

### 4. Vincular Serviço a opção do Chatbot

No editor de etapa → **"Configurar destinos das opções"** → cada opção tem um campo **"Serviço associado"**.
Quando o cliente escolher essa opção, o serviço fica salvo na sessão e flui para o Lead criado.

### 5. Imagem (logo) no cabeçalho da proposta

Editar proposta → seção **Cabeçalho**:
- Upload de PNG/JPG/JPEG/WEBP, máx 2MB, validado
- Storage isolado por empresa (`media/proposals/headers/<empresa_id>/`)
- Cascata: imagem da proposta → imagem do template → logo da empresa
- Checkbox **"Usar imagem do template"** alterna herança

### 6. Editor rich-text (Quill)

Em **Propostas → Editar** e em **Configurações → Templates de Proposta**:

- Toolbar: alinhamento (esq/centro/dir/just), tamanho da fonte, negrito/itálico/sublinhado, listas, blockquote, link
- HTML é **sanitizado no save** via `nh3` (allowlist em `apps/proposals/sanitizer.py`)
- Tags `<script>`, `onclick=`, `onerror=` são removidas

### 7. Pré-visualização, PDF e DOCX

Botões no detalhe da proposta:
- **Visualizar** → renderiza a proposta em página HTML
- **PDF** → download via WeasyPrint (layout fiel, contador de páginas)
- **Word** → download via docxtpl (limitação documentada — formatação rich vira texto plano)

### 8. Status editável (incluindo desfazer Aceita)

Detalhe da proposta:
- Botão **"Desfazer"** aparece para status terminais (`accepted`, `rejected`, `cancelled`, `expired`)
- Volta o status para `draft` (limpa `accepted_at`/`rejected_at`)
- ⚠️ **Lançamentos financeiros gerados** ao aceitar **permanecem** — toast avisa para reverter manualmente
- Histórico de transições registrado em `ProposalStatusHistory`

### 9. Excluir proposta

Botão **Excluir** (vermelho) → modal de **confirmação dupla**:
- Mostra número, título, status, total, lead
- Aviso reforçado se já foi enviada/aceita
- Exige digitar o número da proposta para liberar o botão de exclusão
- Snapshot completo gravado em `AutomationLog` antes da exclusão

### 10. Enviar por e-mail

Botão **E-mail** → modal:
- Destinatário, assunto e mensagem editáveis
- PDF anexado automaticamente
- Template HTML brandado em `templates/emails/proposal_send.html`
- Em sucesso, `last_email_sent_at` registrado e (se DRAFT) status → SENT

### 11. Enviar por WhatsApp

Botão **WhatsApp** → modal:
- Telefone (apenas dígitos, ex.: `11999998888`)
- Mensagem editável
- Estratégia: tenta `sendMedia` (PDF anexo) → fallback para link público
- Toast verde = anexo OK, amarelo = anexo falhou + link enviado, vermelho = ambos falharam
- Empresa precisa ter WhatsApp configurado (Configurações → WhatsApp)
- Endpoint público: `/p/<uuid>/` (UUID4 gerado por proposta, indexado, sem auth)

### 12. Configurar gatilhos de pipeline

Sidebar → **Configurações** → **Automações de Pipeline**:

- **Quando**: evento (proposta criada/enviada/aceita/rejeitada/cancelada/expirada)
- **Pipeline + Etapa destino** (validação cruzada — etapa precisa pertencer ao pipeline)
- **Prioridade** (menor = primeiro), **Ativa**

Quando a proposta muda de status, signal `post_save` dispara em `transaction.on_commit` →
`apps.automation.services.execute_proposal_event` → executa todas as regras ativas.
Falha numa regra **nunca** bloqueia mudança de status. Recursão prevenida via flag
`Lead._suppress_automation`.

---

## Comandos operacionais

```bash
# Instalar dependências novas (weasyprint, docxtpl, python-docx, nh3)
pip install -r requirements/base.txt

# Aplicar migrations (ordem automática)
python manage.py migrate

# Backfill de hierarquia em fluxos antigos do chatbot
python manage.py rebuild_chatbot_hierarchy

# Coletar estáticos (Quill vendored)
python manage.py collectstatic --noinput

# Rodar suite de testes
python manage.py test apps -v 2

# Subir dev
python manage.py runserver 8000
```

### Em produção (VPS)

Após `git pull` e `pip install -r requirements/base.txt`:

```bash
sudo chown -R saas:saas /opt/saas-prestadores
sudo -u saas python manage.py migrate
sudo -u saas python manage.py rebuild_chatbot_hierarchy
sudo -u saas python manage.py collectstatic --noinput
sudo systemctl restart saas-prestadores.service
```

---

## Pontos de atenção em produção

1. **WeasyPrint requer GTK em Windows** — só rodar PDF em Linux/produção. Em testes
   Windows, `render_proposal_pdf` é mockado.
2. **SMTP é global** — todas empresas enviam pelo mesmo backend. SMTP por tenant é
   evolução futura.
3. **Evolution API quirks** — `sendMedia` pode falhar em algumas versões; o fallback
   para link público garante entrega.
4. **Token público é UUID4** — alta entropia, mas considere rate-limiting via reverse
   proxy (Caddy/nginx) no `/p/*` se houver abuso.
5. **Hard delete de proposta** é definitivo — recuperação só via backup.
6. **Mensagem de encerramento do chatbot é OFF por default em fluxos existentes** —
   se cliente quer mensagem antiga, precisa ativar manualmente em cada fluxo.

---

## Limitações documentadas

- **DOCX** não preserva formatação rich; serve como fallback estruturado.
  Para layout fiel, usar PDF.
- **Hierarquia do chatbot** é puramente visual; reorganizar parent/subordem
  não muda o comportamento da engine (que segue `next_step` + `order`).
- **Soft-delete** não implementado nesta rodada (padrão atual do projeto é
  hard delete).
- **Loop de automação** prevenido por `_suppress_automation`. Não há detecção
  de ciclos entre regras (regra A move para etapa X, regra B reage à mudança…).
  Hoje, regras só reagem a eventos de proposta — não a mudanças de lead.

---

## Estrutura final dos arquivos

### Novos
- `apps/proposals/sanitizer.py` — allowlist nh3
- `apps/proposals/signals.py` — post_init/post_save com tracking
- `apps/proposals/services/render.py` — preview/PDF/DOCX
- `apps/proposals/services/email.py` — envio e-mail
- `apps/proposals/services/whatsapp.py` — envio WhatsApp + fallback
- `apps/proposals/tests/test_*.py` — 25 testes
- `apps/automation/tests/test_pipeline_rules.py` — 7 testes
- `apps/operations/tests/test_servicetype.py` — 4 testes
- `apps/chatbot/management/commands/rebuild_chatbot_hierarchy.py`
- `apps/chatbot/tests/test_hierarchy.py` — 9 testes
- `templates/proposals/render/proposal_print.html`
- `templates/proposals/partials/_delete_confirm.html`
- `templates/proposals/partials/_send_email_form.html`
- `templates/proposals/partials/_send_whatsapp_form.html`
- `templates/emails/proposal_send.html`, `proposal_send.txt`
- `templates/settings/automation_rule_*.html`
- `static/vendor/quill/quill.js`, `quill.snow.css`
- `static/js/rich-text-init.js`

### Modelos novos
- `apps.automation.models.PipelineAutomationRule`
- `apps.proposals.models.ProposalStatusHistory`

### Models alterados
- `ChatbotFlow` — `+send_completion_message`, `+completion_message`
- `ChatbotStep` — `+parent`, `+subordem`, `+codigo_hierarquico`, `+nivel`
- `ChatbotChoice` — `+servico` (FK ServiceType)
- `Proposal` — `+header_image`, `+body`, `+servico`, `+public_token`, `+viewed_at`,
  `+last_email_sent_at`, `+last_whatsapp_sent_at`, status `CANCELLED`,
  `+use_template_header_image`
- `ProposalTemplate` — `+header_image`
- `ServiceType` — catálogo completo: `+code`, `+category`, `+default_price`,
  `+default_description`, `+default_prazo_dias`, `+default_proposal_template`,
  `+default_contract_template`, `+default_pipeline`, `+default_stage`, `+tags`,
  `+internal_notes`. Verbose name → "Serviço Pré-Fixado"
- `Lead` — `+servico`
- `AutomationLog.Action` — `+PROPOSAL_PIPELINE_TRIGGER`, `+PROPOSAL_DELETED`

### Rotas novas
- `proposals:preview/pdf/docx/delete/send_email/send_whatsapp`
- `proposal_public` (em `/p/<uuid:token>/`)
- `settings_app:automation_rule_list/create/update/delete`

### Sidebar
- Nova seção **Catálogo** entre Comercial e Operacional, com link "Serviços Pré-Fixados"

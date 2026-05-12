# RV05 — Correções, Melhorias e Evolução Estrutural

Quinta rodada de revisão. Resolve **4 bugs críticos** reportados em produção, entrega
**6 melhorias estruturais** + **1 evolução estratégica** (preparação fluxo visual), e
extrai uma **camada compartilhada** (`apps/core/document_render/`) antes que o terceiro
documento (Recibo? OS impressa?) chegue e a divergência fique cara.

A revisão é dividida em 6 fases de risco crescente, com commits separados para rollback
granular se necessário.

---

## Resumo executivo

| # | Item | Tipo | Status |
|---|------|------|--------|
| 1 | Bug 500 ao subir imagem ao cabeçalho da proposta | Bug | Resolvido (`STORAGES["default"]` + `url_fetcher`) |
| 2 | Editor de fontes mostrando "normal" | Bug | Resolvido (`FontStyle.whitelist` + sanitizer 0.3) |
| 3 | Delete de lead pelo pipeline não some da lista | Bug | Resolvido (`SoftDeletableModel` + cascade soft) |
| 4 | Botão Cancelar do lead form vai a página incompleta | Bug | Resolvido (`<a href>` + `next` safe) |
| 5 | Encerrar conversa por etapa (chatbot) | Melhoria | Resolvido (reuso de `is_final`, label nova) |
| 6 | Ações automáticas por etapa do fluxo | Melhoria | Resolvido (`ChatbotAction.step` + `ON_STEP`) |
| 7 | Múltiplas formas de pagamento na proposta | Melhoria | Resolvido (`FormaPagamento` M2M + seed 6) |
| 8 | Rodapé configurável da proposta | Melhoria | Resolvido (`footer_image` + `footer_content` rich) |
| 9 | Padronização Contratos (cabeçalho/rodapé/rich/PDF/DOCX) | Melhoria | Resolvido (replica Proposta) |
| 10 | Camada compartilhada `apps/core/document_render/` | Refactor | Resolvido (sanitizer + image_validation + pdf) |
| 11 | Preparação para fluxo visual (drag-and-drop futuro) | Evolução | Resolvido (campos backend only: position/node_type) |

**Testes:** 364 testes passando (subiu de 302 → 364, +62 testes RV05).

---

## RV05-A — Bug 500 ao subir imagem ao cabeçalho

### Causa-raiz

Django 5+ exige `STORAGES["default"]` explícito em `settings.STORAGES`. Settings legado
tinha apenas `staticfiles`, fazendo `default_storage` falhar com `InvalidStorageError`
no momento do upload. Caía em 500 antes mesmo de chegar no form.

### Solução

**`config/settings/base.py`:**
```python
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
```

**`apps/core/document_render/pdf.py`** (novo) — WeasyPrint não chamava `url_fetcher` porque
faltava `base_url`. Solução: factory pattern que aceita o host do request como interno,
bloqueia `file://`, `ftp://`, e `data:` malicioso, resolve `/media/*` via `default_storage`
(preparado para S3 futuro):

```python
def _make_media_url_fetcher(internal_hosts: frozenset):
    allowed = _ALWAYS_INTERNAL_HOSTS | internal_hosts
    def fetcher(url: str) -> dict:
        parsed = urlparse(url)
        if parsed.scheme in _BLOCKED_SCHEMES:
            raise ValueError(f"Esquema bloqueado: {parsed.scheme}")
        if parsed.scheme in {"data"}:
            # filtro data:image/png;base64 OK; data: com script bloqueado
            ...
        if parsed.path.startswith("/media/"):
            name = parsed.path[len("/media/"):]
            if default_storage.exists(name):
                with default_storage.open(name, "rb") as f:
                    return {"file_obj": f, "mime_type": _guess_mime(name)}
        return weasyprint.urls.default_url_fetcher(url)
    return fetcher

def render_html_to_pdf(html, *, base_url=None) -> bytes:
    effective_base = base_url or DEFAULT_BASE_URL
    base_host = urlparse(effective_base).netloc
    fetcher = _make_media_url_fetcher(frozenset({base_host}) if base_host else frozenset())
    return weasyprint.HTML(string=html, base_url=effective_base, url_fetcher=fetcher).write_pdf()
```

`ProposalPDFView` (e a nova `ContractPDFView`) envolvem `render_*_pdf` em try/except:
`ValueError` → 4xx legível; exception genérica → 5xx com Sentry/log.

### Diagnóstico

A causa-raiz foi descoberta com `deploy/reproduce_bug500.py` — script que roda
`Client().post()` dentro da VPS com `DJANGO_SETTINGS_MODULE=config.settings.prod` para
capturar o traceback completo (em log normal apenas o 500 chegava).

---

## RV05-B — Editor de fontes mostrando "normal"

### Causa-raiz

Quill 2.x registra apenas `SizeStyle` por padrão. Sem registrar `FontStyle`, qualquer
fonte salva no banco vinha como dropdown rotulado "normal" quando recarregado. Além
disso, `SizeStyle.whitelist` não tinha o valor `false` (sem tamanho explícito), gerando
mesmo problema para a opção default.

Adicionalmente, o sanitizer (nh3 < 0.3) **preservava `style` cru**, deixando
brecha para `<p style="background:url(javascript:alert(1))">`.

### Solução

**`static/js/rich-text-init.js`:**
```javascript
const FONT_WHITELIST = ["arial", "times-new-roman", "georgia", "verdana", "tahoma", "courier-new"];
const SIZE_WHITELIST = [false, "10px", "12px", "14px", "16px", "18px", "20px", "24px", "32px"];

const FontStyle = Quill.import("attributors/style/font");
FontStyle.whitelist = FONT_WHITELIST;
Quill.register(FontStyle, true);

const SizeStyle = Quill.import("attributors/style/size");
SizeStyle.whitelist = SIZE_WHITELIST;
Quill.register(SizeStyle, true);

const toolbar = [
    [{ header: [1, 2, 3, false] }],
    [{ font: FONT_WHITELIST }],
    [{ size: SIZE_WHITELIST }],
    ["bold", "italic", "underline"],
    [{ list: "ordered" }, { list: "bullet" }],
    [{ align: [] }],
    ["link", "clean"],
];
```

**`static/css/quill-fonts.css`** (novo) — rótulos amigáveis no dropdown:
```css
.ql-picker.ql-font [data-value="arial"]::before { content: "Arial"; }
.ql-picker.ql-font [data-value="georgia"]::before { content: "Georgia"; }
/* ... */
```

**`apps/core/document_render/sanitizer.py`** — usa `nh3 ≥ 0.3` com
`filter_style_properties`:
```python
SAFE_STYLE_PROPS = {
    "text-align", "font-size", "font-weight", "font-style", "font-family",
    "margin", "padding", "color", "background-color",
    "text-decoration", "list-style-type",
}

def sanitize_rich_html(html: str) -> str:
    if not html:
        return ""
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "tel"},
        link_rel="noopener noreferrer",
        filter_style_properties=SAFE_STYLE_PROPS,
    )
```

Resultado: `font-family` preservado, `background:url(javascript:...)` removido.

---

## RV05-C — Delete de lead pelo pipeline

### Causa-raiz

Pipeline UI estava chamando hard-delete em `Opportunity`, sem tocar no `Lead`. O lead
continuava ativo no banco com `pipeline_stage` apontando para o estágio, aparecendo na
listagem `/crm/leads/`. Não era um bug de "esconder" — era de modelagem: a UI nunca
chamou nenhum endpoint que deletasse o lead em si.

### Solução

**Lead vira soft-deletable + cascade explícito:**
```python
# apps/crm/models.py
class Lead(SoftDeletableModel, TenantOwnedModel):
    # ...
    def delete(self, using=None, keep_parents=False, hard: bool = False, cascade_soft: bool = True):
        from django.db.models import ProtectedError
        # Pré-check LGPD: contrato vinculado bloqueia delete
        contracts = list(self.contracts.all()[:5])
        if contracts:
            raise ProtectedError(
                "Lead vinculado a contrato(s). Cancele ou exclua o contrato primeiro.",
                set(contracts),
            )
        if hard:
            return super().delete(using=using, keep_parents=keep_parents, hard=True)
        if cascade_soft:
            # Hard-delete oportunidades (volátil), soft-delete propostas pré-aceitas
            self.opportunities.all().delete()
            from apps.proposals.models import Proposal
            Proposal.all_objects.filter(
                lead=self,
                status__in=[Proposal.Status.DRAFT, Proposal.Status.SENT, Proposal.Status.VIEWED],
                deleted_at__isnull=True,
            ).update(deleted_at=timezone.now())
        return super().delete(using=using, keep_parents=keep_parents)
```

**Contract.lead → PROTECT** (proteção LGPD: contrato assinado nunca fica órfão):
```python
lead = models.ForeignKey("crm.Lead", on_delete=models.PROTECT, related_name="contracts")
```

**Nova URL + view:** `crm:lead_delete_cascade` chama `lead.delete()` (soft + cascade).

**UI dual no pipeline:**
- "Excluir oportunidade (mantém lead)" — comportamento legado
- "Excluir lead inteiro" — abre modal de confirmação, faz POST em `lead_delete_cascade`

Manager default já filtra `deleted_at__isnull=True`, então sumir da lista é automático.

---

## RV05-D — Botão Cancelar do lead form

### Causa-raiz

Template usava `<button hx-get="..." hx-target="body">`. O `HtmxResponseMixin` da view
respondia com o partial `_lead_table.html`, gerando layout incompleto (tabela sem
header/menu).

### Solução

**`templates/crm/partials/_lead_form.html`:**
```django
<a href="{{ cancel_url|default:'/crm/leads/' }}"
   class="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50">
    Cancelar
</a>
```

**`apps/crm/views.py`** — helper compartilhado:
```python
def _resolve_cancel_url(request, default_name: str = "crm:lead_list") -> str:
    next_url = (request.GET.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return next_url
    return reverse(default_name)
```

`LeadCreateView`/`LeadUpdateView.get_context_data` populam `cancel_url`. Open-redirect
para `https://attacker.com/steal` é descartado.

---

## RV05-E — Encerrar conversa por etapa (chatbot)

Cliente reportou: "queria marcar um passo como o final do fluxo, mas não acho a opção".

**`ChatbotStep.is_final` já existia** desde RV03, com semântica idêntica à pedida. Bastava
ajustar a UI:

- `apps/chatbot/forms.py::ChatbotStepForm` — `labels["is_final"] = "Encerrar conversa neste passo"`
- `help_texts["is_final"] = "Se marcado, a conversa termina ao executar este passo."`
- `templates/chatbot/partials/_step_list.html` — checkbox visível no editor inline

Engine (`process_response`) já tratava corretamente. Adicionou-se teste explícito
`test_step_marked_final_completes_conversation`.

**Decisão arquitetural:** **não** criar campo novo `encerrar_conversa`. Duplicaria
semântica e geraria estado contraditório (`is_final=True, encerrar_conversa=False`?).

---

## RV05-F — Ações automáticas por etapa

Antes de RV05, `ChatbotAction` só rodava no fim do fluxo (`ON_COMPLETE`). Cliente
queria executar ação **imediatamente após** um passo específico (ex.: após coletar
e-mail, criar lead; após escolher serviço, criar oportunidade).

### Modelo

```python
class ChatbotAction(TimestampedModel):
    flow = models.ForeignKey(ChatbotFlow, on_delete=CASCADE, related_name="actions")
    step = models.ForeignKey(ChatbotStep, on_delete=CASCADE,
                              null=True, blank=True, related_name="actions")
    trigger = models.CharField(choices=Trigger.choices, default=Trigger.ON_COMPLETE)
    action_type = models.CharField(choices=ActionType.choices)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(step__isnull=False, trigger="on_step")
                    | models.Q(step__isnull=True) & ~models.Q(trigger="on_step")
                ),
                name="chatbot_action_step_trigger_consistency",
            ),
        ]
        ordering = ["order", "id"]
```

CheckConstraint força mutex: `ON_STEP` exige `step`, demais triggers exigem `step=None`.

### Engine

```python
# apps/chatbot/services.py
def _execute_step_actions(session, step) -> None:
    actions = ChatbotAction.objects.filter(
        flow=session.flow, step=step,
        trigger=ChatbotAction.Trigger.ON_STEP, is_active=True,
    ).order_by("order", "id")
    for action in actions:
        try:
            _execute_action(action, session)
        except Exception:
            logger.exception("Action %s failed for session %s", action.pk, session.pk)
            # Não quebra a conversa
```

Chamado em `process_response` APÓS enviar a mensagem do step e ANTES de avançar.
`_execute_flow_actions` (legado, `ON_COMPLETE`) filtra `step__isnull=True` para não rodar
ações per-step duas vezes.

### UI

`templates/chatbot/partials/_step_list.html` — seção colapsável "Ações automáticas desta
etapa" com inline formset dentro do editor de step.

### Compatibilidade

Migration cria coluna `step_id` (nullable) — actions existentes continuam com
`step=None, trigger=ON_COMPLETE`. Zero downtime.

---

## RV05-G — Múltiplas formas de pagamento

### Modelo global vs. per-tenant

**Decisão:** `FormaPagamento` é **global** (não `TenantOwnedModel`). Cliente final só
escolhe quais formas aceitar; o catálogo é universal.

```python
class FormaPagamento(models.Model):
    slug = models.SlugField(unique=True, max_length=40)
    nome = models.CharField(max_length=80)
    ordem = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["ordem", "nome"]
```

**Migration `0009_forma_pagamento_global_and_footer.py`** seeda 6 formas fixas em
`RunPython`:

| slug | nome | ordem |
|------|------|-------|
| `pix` | Pix | 1 |
| `cartao_credito` | Cartão de Crédito | 2 |
| `cartao_debito` | Cartão de Débito | 3 |
| `dinheiro` | Dinheiro | 4 |
| `transferencia` | Transferência | 5 |
| `boleto` | Boleto | 6 |

E faz backfill: para cada `Proposal.payment_method` (legado CharField) preenchido, vincula
ao `FormaPagamento` correspondente via M2M. Idempotente, reversível.

### Dual-read

`Proposal.payment_method` (CharField legado) **mantido por 1 release** como dual-read.
Template renderiza `payment_methods` se houver, senão cai no legado:

```django
{% with formas=proposal.payment_methods.all %}
{% if formas %}
    Formas: {% for f in formas %}{{ f.nome }}{% if not forloop.last %} · {% endif %}{% endfor %}
{% elif proposal.payment_method %}
    {{ proposal.get_payment_method_display }}
{% endif %}
{% endwith %}
```

Drop do `CharField` previsto para RV06.

### Form

```python
class ProposalForm(...):
    class Meta:
        fields = [..., "payment_methods", "payment_method", ...]
        widgets = {
            "payment_methods": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment_methods"].queryset = (
            self.fields["payment_methods"].queryset.filter(is_active=True)
        )
        self.fields["payment_methods"].required = False
```

---

## RV05-H — Rodapé configurável da proposta

Simétrico ao header já existente desde RV03:

```python
class Proposal(SoftDeletableModel, TenantOwnedModel):
    footer_image = models.ImageField(
        upload_to=_proposal_footer_image_path, null=True, blank=True,
        verbose_name="Imagem do rodapé (logo/identidade)",
        help_text="PNG, JPG ou WEBP. Máx. 2MB.",
    )
    footer_content = models.TextField(
        blank=True, verbose_name="Conteúdo do rodapé",
        help_text="Texto rico — observações finais, contatos, info legais.",
    )
```

`_proposal_footer_image_path` reusa o mesmo padrão de isolamento por empresa do header.
Template `proposal_print.html`:

```django
{% if proposal.footer_content or footer_image_url %}
<div style="margin-top:30px;padding-top:14px;border-top:2px solid #4f46e5;">
    {% if footer_image_url %}
    <div style="text-align:center;margin-bottom:10px;">
        <img src="{{ footer_image_url }}" alt="Rodapé" style="max-height:60px;max-width:240px;">
    </div>
    {% endif %}
    {% if proposal.footer_content %}
    <div class="rich-content">{{ proposal.footer_content|safe }}</div>
    {% endif %}
</div>
{% endif %}
```

`ProposalTemplate` também ganha `footer_image` + `footer_content` para herança.

---

## RV05-I — Contratos padronizados

### Antes

Contract tinha apenas `title`, `content` (texto plano), `terms`, `value`, `lead`. Sem
imagens, sem rich-text, sem render PDF, sem DOCX, sem preview.

### Depois

```python
class Contract(SoftDeletableModel, TenantOwnedModel):
    # ... campos legados ...
    header_image = models.ImageField(upload_to=_contract_header_image_path, ...)
    header_content = models.TextField(blank=True)
    introduction = models.TextField(blank=True)
    body = models.TextField(blank=True)         # rich — substitui `content` legado
    terms = models.TextField(blank=True)
    footer_image = models.ImageField(upload_to=_contract_footer_image_path, ...)
    footer_content = models.TextField(blank=True)
    lead = models.ForeignKey("crm.Lead", on_delete=models.PROTECT, ...)  # LGPD
```

`ContractTemplate` ganha os mesmos campos para herança.

### Forms

`apps/contracts/forms.py::ContractForm` espelha `ProposalForm`:
- `data-rich-text="true"` em `introduction`, `body`, `terms`, `header_content`, `footer_content`
- `clean_header_image` / `clean_footer_image` via `core.document_render.image_validation`
- `clean_*` rich via `core.document_render.sanitizer.sanitize_rich_html`

### Render

Novo `apps/contracts/services/render.py`:

```python
def build_contract_context(contract: Contract, request=None) -> dict:
    body = contract.body or contract.content or ""  # dual-read
    return {
        "contract": contract,
        "empresa": contract.empresa,
        "lead": contract.lead,
        "body": body,
        "header_image_url": _resolve_image_url(contract.header_image, request),
        "footer_image_url": _resolve_image_url(contract.footer_image, request),
        # ...
    }

def render_contract_pdf(contract, request=None) -> bytes:
    from apps.core.document_render.pdf import render_html_to_pdf
    html = render_contract_html(contract, request=request)
    base_url = request.build_absolute_uri("/") if request else None
    return render_html_to_pdf(html, base_url=base_url)

def render_contract_docx(contract) -> bytes:
    # python-docx idiossincrático — mantém estrutura mas sem rich formatting fiel
    ...
```

`templates/contracts/render/contract_print.html` — cópia ajustada de `proposal_print.html`,
com seções Cabeçalho, Introdução, Conteúdo, Termos, Assinaturas, Rodapé.

### URLs

- `contracts:preview` — `/contracts/<pk>/preview/` (HTML)
- `contracts:pdf` — `/contracts/<pk>/pdf/` (`application/pdf`)
- `contracts:docx` — `/contracts/<pk>/docx/` (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`)

Multi-tenant: cada view valida `empresa=request.empresa`; outro tenant recebe 404.

### Migração legado `content` → `body`

`contracts/0003_sanitize_legacy_content.py` (RunPython idempotente):
1. Para cada Contract com `content` preenchido e `body` vazio
2. Escapa HTML (`<` `>` viram entities), aplica `sanitize_rich_html`
3. Persiste em `body`
4. `content` mantido por 1 release para rollback

### ContractStatusHistory

Análogo a `ProposalStatusHistory`: signal em `apps/contracts/signals.py` registra
mudanças de `status` ao salvar.

---

## RV05-J — Camada compartilhada `apps/core/document_render/`

### Estrutura

```
apps/core/document_render/
├── __init__.py
├── sanitizer.py          # sanitize_rich_html, SAFE_STYLE_PROPS
├── image_validation.py   # validate_document_image, MAX_BYTES, ALLOWED_EXTS
└── pdf.py                # render_html_to_pdf, _make_media_url_fetcher
```

### Shim de compatibilidade

`apps/proposals/sanitizer.py`:
```python
# Mantido por compatibilidade — use apps.core.document_render.sanitizer
from apps.core.document_render.sanitizer import sanitize_rich_html as sanitize_proposal_html  # noqa
```

`apps/proposals/forms.py`:
```python
from apps.core.document_render.image_validation import (
    ALLOWED_DOCUMENT_IMAGE_EXTS as ALLOWED_HEADER_IMAGE_EXTS,
    MAX_DOCUMENT_IMAGE_BYTES as MAX_HEADER_IMAGE_BYTES,
    validate_document_image as _validate_header_image,
)
```

Aliases preservados → zero alteração em código legado dos testes/views.

### Decisão: **não** abstrair DOCX agora

DOCX é idiossincrático demais por tipo de documento (`python-docx` montando parágrafos,
tabelas e estilos manualmente). Tentar uma camada compartilhada agora geraria over-
engineering. Quando o terceiro documento (Recibo, OS impressa) aparecer, **aí sim** vale
extrair `render_*_docx` com helpers comuns. Sanitizer + imagem + PDF são puros e
ortogonais — esses entram agora.

---

## RV05-K — Preparação para fluxo visual

Cliente vislumbrou no futuro um editor drag-and-drop (React Flow / Drawflow / N8N-style)
para o chatbot. RV05 entrega apenas **o backend pronto**, sem mudança de UI:

```python
class ChatbotStep(TimestampedModel):
    class NodeType(models.TextChoices):
        MESSAGE = "message", "Mensagem"
        QUESTION = "question", "Pergunta"
        CONDITION = "condition", "Condição"
        ACTION = "action", "Ação"

    node_type = models.CharField(choices=NodeType.choices, default=NodeType.MESSAGE)
    position_x = models.FloatField(default=0.0)
    position_y = models.FloatField(default=0.0)
    visual_config = models.JSONField(default=dict, blank=True)
```

Quando RV06 escolher o framework visual, basta serializar o grafo via DRF e o frontend
escreve nesses campos sem migration nova. Baixo risco hoje, evita migration amanhã.

---

## Migrations

Aplicadas em ordem na VPS (todas reversíveis):

| Ordem | Migration | Conteúdo |
|---|---|---|
| 1 | `crm/0010_lead_soft_delete` | `deleted_at` indexed em `Lead` |
| 2 | `contracts/0002_contract_rich_fields_protect_softdelete` | rich fields + PROTECT em `lead` + `deleted_at` |
| 3 | `contracts/0003_sanitize_legacy_content` | RunPython idempotente migra `content` → `body` |
| 4 | `chatbot/0010_action_per_step_visual_fields` | `step` FK + `ON_STEP` + CheckConstraint + position/node_type |
| 5 | `proposals/0009_forma_pagamento_global_and_footer` | seed 6 formas + M2M + `footer_image`/`footer_content` |

Verificação:
```bash
python manage.py showmigrations | grep -E "\[X\] (0010|0009|0002|0003)"
```

---

## Arquivos novos

```
apps/core/document_render/__init__.py
apps/core/document_render/sanitizer.py
apps/core/document_render/image_validation.py
apps/core/document_render/pdf.py
apps/contracts/services/__init__.py
apps/contracts/services/render.py
apps/contracts/signals.py
apps/contracts/migrations/0002_contract_rich_fields_protect_softdelete.py
apps/contracts/migrations/0003_sanitize_legacy_content.py
apps/contracts/tests/__init__.py
apps/contracts/tests/test_contract_render.py
apps/proposals/migrations/0009_forma_pagamento_global_and_footer.py
apps/proposals/tests/test_payment_methods.py
apps/proposals/tests/test_footer.py
apps/proposals/tests/test_pdf_image.py
apps/proposals/tests/test_quill_fonts.py
apps/crm/migrations/0010_lead_soft_delete.py
apps/crm/tests/test_lead_soft_delete.py
apps/chatbot/migrations/0010_action_per_step_visual_fields.py
apps/chatbot/tests/test_per_step_actions.py
templates/contracts/render/contract_print.html
static/css/quill-fonts.css
deploy/ssh_sudo.py
deploy/reproduce_bug500.py
deploy/smoke_rv05.py
```

## Arquivos modificados (resumo)

- `config/settings/base.py` — `STORAGES["default"]`
- `apps/chatbot/models.py`, `services.py`, `forms.py`, `views.py`, `urls.py`, `admin.py`
- `apps/proposals/models.py`, `forms.py`, `services/render.py`, `sanitizer.py` (shim), `views.py`
- `apps/crm/models.py`, `views.py`, `forms.py`, `urls.py`
- `apps/contracts/models.py`, `forms.py`, `views.py`, `urls.py`, `apps.py`, `admin.py`
- `static/js/rich-text-init.js`
- `templates/chatbot/partials/_step_list.html`, `_action_list.html`
- `templates/proposals/proposal_form.html`, `render/proposal_print.html`
- `templates/contracts/contract_form.html`, `contract_detail.html`
- `templates/crm/partials/_lead_form.html`, `opportunity_detail.html`

---

## Rotas novas

| Verb | URL | View | Acesso |
|------|-----|------|--------|
| POST | `/crm/leads/<pk>/delete-cascade/` | `LeadDeleteCascadeView` | logado, mesma empresa |
| GET | `/contracts/<pk>/preview/` | `ContractPreviewView` | logado, mesma empresa |
| GET | `/contracts/<pk>/pdf/` | `ContractPDFView` | logado, mesma empresa |
| GET | `/contracts/<pk>/docx/` | `ContractDOCXView` | logado, mesma empresa |

Pipeline e flow chatbot mantêm URLs originais; URL `chatbot:action_add` agora aceita
opcionalmente `step_pk` na query string para vincular a action ao step.

---

## Como usar (cliente final do SaaS)

### Encerrar conversa em um passo
1. Acesse **Chatbot > Fluxos > [seu fluxo]**
2. No editor de cada step, marque o checkbox **"Encerrar conversa neste passo"**
3. Salve. Conversa termina automaticamente ao chegar nesse step.

### Adicionar ação automática a um passo específico
1. No editor do step, abra a seção **"Ações automáticas desta etapa"**
2. Escolha o tipo de ação (criar lead, criar oportunidade, enviar e-mail, etc.)
3. Ordem `0` = primeira ação a rodar. Use `is_active=False` para desligar sem deletar.

### Configurar múltiplas formas de pagamento na proposta
1. Em **Propostas > Nova Proposta**, role até **Formas de Pagamento**
2. Marque os checkboxes desejados (PIX, Cartão, etc.) — pode escolher múltiplas
3. Marque **"Parcelado"** + número de parcelas se aplicável
4. Salve. PDF/DOCX/Preview mostram todas as formas escolhidas.

### Configurar rodapé da proposta
1. Em **Propostas > [proposta] > Editar**, role até **Rodapé**
2. Faça upload de imagem (logo, identidade) — PNG/JPG/WEBP, max 2MB
3. Edite o **Conteúdo do rodapé** com formatação rich (Quill) — observações, contatos, info legais
4. Para fixar como padrão da empresa: faça o mesmo em **Templates > [template default]**

### Excluir lead pelo Pipeline
1. No detalhe da oportunidade no pipeline, há **dois botões**:
   - **"Excluir oportunidade (mantém lead)"** — só remove a oportunidade, lead continua disponível
   - **"Excluir lead inteiro"** — abre modal de confirmação. Soft-delete em cascade (lead + oportunidades + propostas pré-aceitas). Lead some das listagens.
2. Contratos vinculados **bloqueiam** o delete do lead (proteção LGPD). Cancele ou exclua o contrato primeiro.

### Cancelar criação de lead
Botão Cancelar agora é navegação plana. Se a página de origem passou `?next=/path/de/volta`, volta para lá; senão, vai para `/crm/leads/`.

### Criar contrato com cabeçalho/rodapé e rich-text
1. **Contratos > Novo Contrato**
2. Preencha rich-text em **Cabeçalho**, **Introdução**, **Conteúdo**, **Termos**, **Rodapé**
3. Faça upload das imagens de cabeçalho e rodapé (opcional)
4. Salve e baixe PDF (`/contracts/<pk>/pdf/`) ou DOCX (`/contracts/<pk>/docx/`). Preview HTML em `/preview/`.

---

## Comandos operacionais

```bash
# Dependências (nenhuma nova lib em RV05)
pip install -r requirements/base.txt

# Aplicar migrations
python manage.py migrate

# Coletar estáticos (CSS de fontes e JS Quill atualizado)
python manage.py collectstatic --noinput

# Rodar testes (esperado: 364 passando)
python manage.py test apps -v 2

# Deploy completo na VPS
python deploy/ssh_exec.py "cd /opt/saas-prestadores && git pull && ./venv/bin/python manage.py migrate && ./venv/bin/python manage.py collectstatic --noinput"
python deploy/ssh_sudo.py "systemctl restart saas-prestadores.service"

# Smoke-test prod ponta-a-ponta (cobre todos os 11 itens RV05)
python deploy/ssh_exec.py "cd /opt/saas-prestadores && DJANGO_SETTINGS_MODULE=config.settings.prod ./venv/bin/python smoke_rv05.py"
```

---

## Pontos de atenção em produção

1. **Backup do MEDIA_ROOT** — imagens de cabeçalho/rodapé ficam em `/opt/saas-prestadores/media/`. Sem backup, perda de imagens em incidente. Sugestão: rsync diário para storage offsite ou migrar para S3 (default_storage está preparado).
2. **Fernet key (herança RV04)** — ainda crítica para senhas SMTP. Sem backup → todos os tenants precisam recadastrar SMTP. Não esqueça.
3. **Caddyfile** — bloco `/media/*` apontando para `/opt/saas-prestadores/media/` é apenas para **preview HTML** dos PDFs (acessibilidade dos clientes). PDF em si **não depende** do Caddy: `media_url_fetcher` lê via `default_storage`.
4. **`Proposal.payment_method` (CharField legado)** — drop previsto em RV06. Manter dual-read até confirmar que nenhum cliente tem template fiscal referenciando o campo antigo.
5. **`Contract.content` (CharField legado)** — idem, drop em RV06 após auditoria de impressões.
6. **GTK no Windows** — herda RV04; ainda necessário para PDF local. Em produção (Linux), zero issue.

---

## Limitações que ficam abertas

1. **DOCX rich formatting fiel** — RV03 limitation, ainda válida. Integrar `pypandoc` (que usa Pandoc) se cliente reclamar de perda de bold/italic em DOCX. Avaliar custo de instalar Pandoc na VPS vs. converter via libreoffice headless (já presente).
2. **Fluxo visual drag-and-drop** — apenas backend preparado. Escolha do framework (React Flow vs. Drawflow vs. N8N forked) fica para RV06.
3. **Soft-delete em ContractTemplate / ProposalTemplate** — apenas Contract e Proposal e Lead viraram soft-deletable. Templates podem expandir gradualmente.
4. **WhatsApp Cloud API oficial** — RV03 limitation; ainda via Evolution API. Migrar quando volume justificar custos do Meta Business.
5. **Trash UI para Lead/Contract** — Proposal já tem `ProposalTrashView`. Lead e Contract ficam só com admin/manager `all_objects` por enquanto. Adicionar templates de lixeira é trivial em RV06.
6. **`FormaPagamentoEmpresa` (per-tenant customization)** — modelo previsto na decisão arquitetural mas não implementado. Catálogo global de 6 formas atende 99% dos casos; se cliente pedir "Crypto" customizada, criar então.
7. **Trigger ON_STEP em outros tipos de step** — implementado para step de tipo TEXT/NAME/EMAIL/PHONE/SELECT. Tipos `CONDITION` e `ACTION` (novos no `NodeType`) ainda não rodam ON_STEP — backend apenas modelado.

---

## Riscos mitigados

| Risco | Como foi mitigado |
|---|---|
| Migração `payment_method` → `payment_methods` em produção quebrando templates impressos | Dual-read no template e DOCX. CharField mantido por 1 release. Backfill na migration. |
| `Contract.lead` mudando de CASCADE para PROTECT em produção com contratos órfãos | Pré-check em `Lead.delete()` raise `ProtectedError` legível. Migration verificou: zero contratos órfãos. |
| `url_fetcher` lendo filesystem expõe SSRF | Allowlist `/media/` + bloqueio `file://`, `ftp://`. Hosts externos via `default_url_fetcher` somente após filtro. |
| `_execute_flow_actions` rodando per-step actions duas vezes | `_execute_flow_actions` agora filtra `step__isnull=True`. Teste `test_legacy_on_complete_action_still_fires` garante. |
| Soft-delete em Lead deixando filhos órfãos visíveis | `Lead.delete()` propaga soft-delete em Opportunity (hard) e Proposal pré-aceita (soft). Teste `test_cascade_soft_deletes_opportunity_and_draft_proposals` cobre. |
| Migração `content` plain → `body` rich quebrando caracteres especiais | RunPython escapa HTML antes de sanitizar; idempotente; reversível. |
| Caddy não servir `/media/` corretamente após mudança | PDF não depende de Caddy (lê via `default_storage`). Preview HTML degrada-se com mensagem amigável se imagem ausente. |
| Quill registrando FontStyle em runtime quebrar outras telas | Testado em ProposalForm, ContractForm, ProposalTemplateForm, ServiceTypeForm. Todas funcionam. |

---

## Testes RV05 (62 testes novos)

```
apps/core/tests/test_document_render.py                  6 tests
apps/proposals/tests/test_pdf_image.py                   5 tests
apps/proposals/tests/test_quill_fonts.py                 7 tests
apps/proposals/tests/test_payment_methods.py             6 tests
apps/proposals/tests/test_footer.py                      4 tests
apps/crm/tests/test_lead_soft_delete.py                  9 tests
apps/crm/tests/test_lead_cancel.py                       4 tests
apps/chatbot/tests/test_per_step_actions.py             10 tests
apps/chatbot/tests/test_visual_fields.py                 3 tests
apps/contracts/tests/test_contract_render.py             8 tests
```

Total RV05: **62 novos** | Suite completa: **364 passando**.

Smoke-test ponta-a-ponta em produção: `deploy/smoke_rv05.py` cobre os 11 itens via
combinação ORM (manipulação direta de model) + HTTP (`requests.Session` autenticada,
endpoints reais). Roda dentro da VPS com `DJANGO_SETTINGS_MODULE=config.settings.prod`.

---

## Próximos passos (RV06)

- Drop `Proposal.payment_method` (CharField legado)
- Drop `Contract.content` (CharField legado)
- Escolher framework visual e implementar editor drag-and-drop do chatbot
- Trash UI para Lead e Contract
- ContractStatusHistory com signal completo (assinatura, cancelamento, expiração)
- Avaliar `pypandoc` para DOCX rich formatting fiel
- Avaliar storage S3 (`default_storage` já preparado)
- Recibo simples (terceiro documento) — bom momento para extrair `core/document_render/docx_helpers.py`

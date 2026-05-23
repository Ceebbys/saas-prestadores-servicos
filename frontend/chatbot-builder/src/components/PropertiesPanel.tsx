/**
 * Painel direito — propriedades do bloco selecionado.
 *
 * Renderiza campos editáveis dinamicamente baseado no catálogo
 * (`data_fields` de cada NodeCatalogEntry).
 *
 * RV06 — Suporta:
 *   - Tipo `select` com options carregadas via /api/chatbot/options/<source>/
 *   - Campos condicionais por `action_type` (data_fields_per_action_type)
 */
import { useEffect, useRef, useState } from "react";
import { useBuilderStore } from "../store/builderStore";
import { useGraphAPI } from "../hooks/useGraphAPI";
import { MenuOptionsEditor } from "./MenuOptionsEditor";
import type { GraphNode, NodeCatalogField, OptionItem } from "../types";

export function PropertiesPanel() {
  const selectedNodeId = useBuilderStore((s) => s.selectedNodeId);
  const node = useBuilderStore((s) => s.nodes.find((n) => n.id === selectedNodeId));
  const entry = useBuilderStore((s) => (node ? s.getCatalogEntry(node.type) : undefined));
  const updateNodeData = useBuilderStore((s) => s.updateNodeData);
  const deleteNode = useBuilderStore((s) => s.deleteNode);
  const validationErrors = useBuilderStore((s) => s.validationErrors);

  if (!node || !entry) {
    return (
      <aside className="properties-panel properties-panel--empty">
        <p>Selecione um bloco para editar suas propriedades.</p>
      </aside>
    );
  }

  const nodeErrors = validationErrors.filter((e) => e.node_id === node.id);

  // RV06 — Quando node é "action", buscar campos extras baseado no action_type
  // selecionado. data_fields_per_action_type vem do catálogo.
  let extraFields: NodeCatalogField[] = [];
  if (entry.type === "action" && entry.data_fields_per_action_type) {
    const at = String((node.data as any).action_type || "create_lead");
    extraFields = entry.data_fields_per_action_type[at] || [];
  }

  return (
    <aside className="properties-panel">
      <div className="properties-panel__header" style={{ borderTopColor: entry.color }}>
        <h2>{entry.label}</h2>
        <p className="properties-panel__hint">{entry.description}</p>
      </div>

      {nodeErrors.length > 0 && (
        <div className="properties-panel__errors">
          <strong>Problemas detectados:</strong>
          <ul>
            {nodeErrors.map((e, i) => (
              <li key={i}>
                {e.field && <code>{e.field}</code>}: {e.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* RV06 — Banner explicativo para Condition (bloco confuso para leigo) */}
      {node.type === "condition" && (
        <ConditionHelpBanner />
      )}

      <div className="properties-panel__fields">
        {entry.data_fields.map((field) => (
          <FieldEditor
            key={field.name}
            field={field}
            value={(node.data as any)[field.name]}
            onChange={(v) => updateNodeData(node.id, { [field.name]: v })}
            node={node}
          />
        ))}
        {/* RV06 — campos extras condicionais (por action_type) */}
        {extraFields.length > 0 && (
          <div className="properties-panel__extra-fields">
            <div className="properties-panel__divider">
              <span>Configuração da ação</span>
            </div>
            {extraFields.map((field) => (
              <FieldEditor
                key={`extra-${field.name}`}
                field={field}
                value={(node.data as any)[field.name]}
                onChange={(v) => updateNodeData(node.id, { [field.name]: v })}
                node={node}
              />
            ))}
          </div>
        )}
      </div>

      <div className="properties-panel__footer">
        <button
          className="btn btn--danger btn--small"
          onClick={() => {
            if (entry.type === "start") {
              alert("O bloco Início não pode ser removido.");
              return;
            }
            if (confirm("Remover este bloco?")) {
              deleteNode(node.id);
            }
          }}
          disabled={entry.type === "start"}
        >
          Remover bloco
        </button>
      </div>
    </aside>
  );
}

function FieldEditor({
  field,
  value,
  onChange,
  node,
}: {
  field: NodeCatalogField;
  value: unknown;
  onChange: (v: unknown) => void;
  node: GraphNode;
}) {
  const id = `field-${node.id}-${field.name}`;

  // Caso especial: options de menu
  if (field.type === "array" && field.name === "options") {
    return (
      <MenuOptionsEditor
        value={(value as any[]) || []}
        onChange={onChange}
      />
    );
  }

  if (field.type === "boolean") {
    return (
      <div className="field field--checkbox">
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value ?? field.default)}
          onChange={(e) => onChange(e.target.checked)}
        />
        <label htmlFor={id}>{labelize(field)}</label>
        {field.help && <p className="field__help">{field.help}</p>}
      </div>
    );
  }

  if (field.type === "enum") {
    return (
      <div className="field">
        <label htmlFor={id}>{labelize(field)}</label>
        <select
          id={id}
          value={(value as string) ?? (field.default as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
        >
          {(field.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {humanizeEnumOption(field.name, opt) || "(vazio)"}
            </option>
          ))}
        </select>
        {field.help && <p className="field__help">{field.help}</p>}
      </div>
    );
  }

  // RV06 — select dinâmico carregado de /api/chatbot/options/<source>/
  if (field.type === "select") {
    return <DynamicSelect field={field} value={value} onChange={onChange} id={id} />;
  }

  if (field.type === "text") {
    return (
      <TextFieldWithVariables
        id={id}
        field={field}
        value={value}
        onChange={onChange}
      />
    );
  }

  if (field.type === "integer") {
    return (
      <div className="field">
        <label htmlFor={id}>{labelize(field)}</label>
        <input
          id={id}
          type="number"
          min={field.min}
          max={field.max}
          value={(value as number) ?? (field.default as number) ?? 0}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        {field.help && <p className="field__help">{field.help}</p>}
      </div>
    );
  }

  // string default — também fallback de tipos desconhecidos (com warning)
  if (field.type !== "string" && field.type !== undefined) {
    // RV06-H — avisa quando aparecer tipo novo no catálogo sem suporte no
    // FieldEditor (mantém UX usável com input simples)
    console.warn(
      `[PropertiesPanel] Tipo de campo "${field.type}" sem editor dedicado — usando input string como fallback. Adicione case em FieldEditor.`,
    );
  }
  return (
    <div className="field">
      <label htmlFor={id}>{labelize(field)}</label>
      <input
        id={id}
        type="text"
        maxLength={field.max_length ?? 200}
        value={(value as string) ?? (field.default as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
      />
      {field.help && <p className="field__help">{field.help}</p>}
    </div>
  );
}

/**
 * RV06 — Dropdown que carrega options de /api/chatbot/options/<source>/.
 *
 * Usado para selecionar serviços, pipeline stages, proposal templates etc.
 * Cache em memória de 30s no hook fetchOptions evita refetch a cada render.
 */
function DynamicSelect({
  field,
  value,
  onChange,
  id,
}: {
  field: NodeCatalogField;
  value: unknown;
  onChange: (v: unknown) => void;
  id: string;
}) {
  const { fetchOptions } = useGraphAPI();
  const [opts, setOpts] = useState<OptionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    if (!field.source) {
      setLoading(false);
      setError("Campo sem 'source' definido no catálogo.");
      return;
    }
    setLoading(true);
    setError(null);
    fetchOptions(field.source).then((list) => {
      if (!alive) return;
      setOpts(list);
      setLoading(false);
    }).catch(() => {
      if (!alive) return;
      setLoading(false);
      setError("Falha ao carregar opções.");
    });
    return () => { alive = false; };
  }, [field.source, fetchOptions]);

  // RV06 — Quando há valor selecionado, mostra preview dos `extra` (nome,
  // valor, descrição, prazo, modelo). Atende o item 1 da fatura RV06.
  const selected = opts.find((o) => o.value === (value as string));
  const extras = selected?.extra as Record<string, unknown> | undefined;

  return (
    <div className="field">
      <label htmlFor={id}>{labelize(field)}</label>
      <select
        id={id}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading}
      >
        <option value="">{loading ? "Carregando…" : "— selecione —"}</option>
        {opts.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {error && <p className="field__help field__help--error">{error}</p>}
      {!error && opts.length === 0 && !loading && (
        <p className="field__help">
          Nenhuma opção cadastrada — vá em Configurações para criar.
        </p>
      )}
      {field.help && <p className="field__help">{field.help}</p>}
      {extras && Object.keys(extras).length > 0 && (
        <SelectedOptionPreview extras={extras} />
      )}
    </div>
  );
}


/**
 * Card de preview mostrando os campos extras do item selecionado.
 * Atende o pedido do cliente (RV06 Item 1): ao selecionar um serviço,
 * mostrar nome, valor, descrição, prazo e modelo relacionado.
 */
function SelectedOptionPreview({ extras }: { extras: Record<string, unknown> }) {
  const fmt = (k: string, v: unknown): { label: string; value: string } | null => {
    if (v == null || v === "") return null;
    const text = String(v);
    switch (k) {
      case "price":
        return {
          label: "Valor",
          value: text.startsWith("R$") ? text : `R$ ${text}`,
        };
      case "prazo_dias":
        return { label: "Prazo", value: `${text} dia(s)` };
      case "category":
        return { label: "Categoria", value: text };
      case "description":
      case "default_description":
        return { label: "Descrição", value: text };
      case "proposal_template_id":
        return { label: "Modelo de proposta", value: `#${text}` };
      case "contract_template_id":
        return { label: "Modelo de contrato", value: `#${text}` };
      default:
        return null;
    }
  };

  // Dedupe description/default_description (preferir default se ambos)
  const filtered = { ...extras };
  if (filtered.default_description && filtered.description) {
    delete filtered.description;
  }

  const rows = Object.entries(filtered)
    .map(([k, v]) => fmt(k, v))
    .filter((r): r is { label: string; value: string } => r !== null);

  if (rows.length === 0) return null;

  return (
    <div className="select-preview">
      <div className="select-preview__title">Dados carregados</div>
      <dl className="select-preview__list">
        {rows.map((r, i) => (
          <div key={i} className="select-preview__row">
            <dt>{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}


function labelize(field: NodeCatalogField): string {
  if (field.label) return field.label;
  const map: Record<string, string> = {
    label: "Rótulo interno",
    text: "Texto da mensagem",
    prompt: "Pergunta/Texto",
    lead_field: "Campo do lead",
    validator: "Validador",
    validator_strict: "Rejeitar formato inválido",
    options: "Opções",
    field: "Qual dado verificar?",
    operator: "Como comparar?",
    value: "Comparar com qual valor?",
    delay_ms: "Atraso (ms)",
    welcome_message: "Mensagem de boas-vindas",
    completion_message: "Mensagem final",
    message_to_user: "Mensagem ao usuário",
    queue: "Fila/Departamento",
    internal_note: "Nota interna",
    secret_ref: "Segredo (cofre)",
    method: "Método HTTP",
    path_template: "URL",
    payload_template: "Body",
    response_var: "Variável de resposta",
    action_type: "Tipo de ação",
    order: "Ordem de execução",
    is_active: "Ativa",
    // RV06 — campos extras por action_type
    servico_id: "Serviço pré-fixado",
    pipeline_stage_id: "Etapa do pipeline",
    tag_name: "Tag",
    event_name: "Nome do evento",
    proposal_template_id: "Template de proposta",
    contract_template_id: "Template de contrato",
    auto_create_if_missing: "Criar se não existir",
    to: "Destinatário",
    to_custom: "E-mail customizado",
    subject: "Assunto",
    body: "Corpo do e-mail",
    _unimplemented_warning: "Aviso",
  };
  return map[field.name] ?? field.name;
}


// Rótulos amigáveis para valores de enum específicos.
const ENUM_LABELS: Record<string, Record<string, string>> = {
  action_type: {
    create_lead: "Criar lead",
    update_pipeline: "Atualizar pipeline",
    apply_tag: "Aplicar tag",
    link_servico: "Vincular serviço pré-fixado",
    register_event: "Registrar evento",
    send_email: "Enviar e-mail",
    send_whatsapp: "Enviar WhatsApp",
    send_proposal: "Enviar proposta",      // RV06
    send_contract: "Enviar contrato",      // RV06
    create_task: "Criar tarefa (em breve)",
  },
  to: {
    lead: "Lead (e-mail coletado)",
    admin: "Admin da empresa",
    custom: "E-mail customizado",
  },
  operator: {
    exists: "✓ Existe (campo foi preenchido)",
    not_exists: "✗ Não existe (campo está vazio)",
    eq: "= Igual a",
    neq: "≠ Diferente de",
    contains: "Contém o texto",
    starts_with: "Começa com",
    in: "Está na lista (separe por vírgula)",
    regex: "Combina com regex (avançado)",
  },
  field: {
    email: "E-mail do lead",
    phone: "Telefone do lead",
    name: "Nome do lead",
    company: "Empresa do lead",
    cpf_cnpj: "CPF / CNPJ",
    notes: "Observações",
    servico_id: "Serviço vinculado",
  },
  method: {
    GET: "GET", POST: "POST", PUT: "PUT", PATCH: "PATCH", DELETE: "DELETE",
  },
  validator: {
    free_text: "Texto livre",
    name: "Nome (mín. 2 chars)",
    company: "Empresa",
  },
  lead_field: {
    "": "— (não gravar)",
    name: "Nome",
    email: "E-mail",
    phone: "Telefone",
    company: "Empresa",
    cpf_cnpj: "CPF/CNPJ",
    notes: "Observações",
  },
};

function humanizeEnumOption(fieldName: string, value: string): string {
  const inner = ENUM_LABELS[fieldName];
  return inner?.[value] ?? value;
}


/**
 * RV06 — Textarea com botão "🪄 Inserir variável".
 *
 * Cliente pediu: poder inserir {{ servico.name }}, {{ lead.name }} etc.
 * nas mensagens. Botão abre dropdown com lista de variáveis disponíveis
 * (carregada do backend via /api/chatbot/options/template_vars/).
 * Click numa variável insere `{{ path }}` na posição do cursor.
 */
type PickerTab = "dynamic" | "registered";
type RegisteredCategory = "services" | "proposal_templates" | "contract_templates" | "pipeline_stages";

const REGISTERED_CATEGORIES: { key: RegisteredCategory; label: string; icon: string }[] = [
  { key: "services", label: "Serviços cadastrados", icon: "🛠️" },
  { key: "pipeline_stages", label: "Etapas do pipeline", icon: "📍" },
  { key: "proposal_templates", label: "Templates de proposta", icon: "📄" },
  { key: "contract_templates", label: "Templates de contrato", icon: "📑" },
];


function TextFieldWithVariables({
  id, field, value, onChange,
}: {
  id: string;
  field: NodeCatalogField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const { fetchOptions } = useGraphAPI();
  const [vars, setVars] = useState<OptionItem[]>([]);
  const [varsLoaded, setVarsLoaded] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [tab, setTab] = useState<PickerTab>("dynamic");
  const [registered, setRegistered] = useState<Record<RegisteredCategory, OptionItem[]>>({
    services: [], pipeline_stages: [], proposal_templates: [], contract_templates: [],
  });
  const [registeredLoaded, setRegisteredLoaded] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!showPicker || varsLoaded) return;
    fetchOptions("template_vars")
      .then((list) => {
        setVars(list);
        setVarsLoaded(true);
      })
      .catch(() => setVarsLoaded(true));
  }, [showPicker, varsLoaded, fetchOptions]);

  useEffect(() => {
    if (!showPicker || tab !== "registered" || registeredLoaded) return;
    // Carrega as 4 categorias em paralelo
    Promise.all(
      REGISTERED_CATEGORIES.map((c) =>
        fetchOptions(c.key).catch(() => [] as OptionItem[]),
      ),
    ).then((results) => {
      const next: any = {};
      REGISTERED_CATEGORIES.forEach((c, i) => { next[c.key] = results[i]; });
      setRegistered(next);
      setRegisteredLoaded(true);
    });
  }, [showPicker, tab, registeredLoaded, fetchOptions]);

  function insertVariable(snippet: string) {
    const ta = textareaRef.current;
    const current = (value as string) || "";
    if (!ta) {
      onChange(current + snippet);
      setShowPicker(false);
      return;
    }
    const start = ta.selectionStart ?? current.length;
    const end = ta.selectionEnd ?? current.length;
    const next = current.slice(0, start) + snippet + current.slice(end);
    onChange(next);
    setShowPicker(false);
    setTimeout(() => {
      ta.focus();
      const pos = start + snippet.length;
      ta.setSelectionRange(pos, pos);
    }, 0);
  }

  return (
    <div className="field field--text-with-vars">
      <div className="field__header">
        <label htmlFor={id}>{labelize(field)}</label>
        <button
          type="button"
          className="field__var-button"
          onClick={() => setShowPicker((v) => !v)}
          title="Inserir variável dinâmica OU nome de algo cadastrado"
        >
          🪄 Inserir variável
        </button>
      </div>
      <textarea
        ref={textareaRef}
        id={id}
        rows={3}
        maxLength={field.max_length ?? 5000}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
      />
      {showPicker && (
        <div className="var-picker">
          <div className="var-picker__header">
            <strong>Inserir no texto</strong>
            <button
              type="button"
              className="var-picker__close"
              onClick={() => setShowPicker(false)}
              title="Fechar"
            >
              ×
            </button>
          </div>
          {/* Abas: Dinâmica (placeholders) vs Cadastrados (nome literal) */}
          <div className="var-picker__tabs">
            <button
              type="button"
              className={`var-picker__tab ${tab === "dynamic" ? "is-active" : ""}`}
              onClick={() => setTab("dynamic")}
            >
              🔄 Variáveis dinâmicas
            </button>
            <button
              type="button"
              className={`var-picker__tab ${tab === "registered" ? "is-active" : ""}`}
              onClick={() => setTab("registered")}
            >
              📋 Cadastrados
            </button>
          </div>

          {tab === "dynamic" && (
            <>
              <p className="var-picker__hint">
                Variáveis substituídas <strong>na hora do envio</strong> pelo
                valor real (ex: serviço que o cliente escolheu).
              </p>
              {!varsLoaded && <p className="var-picker__loading">Carregando…</p>}
              {varsLoaded && vars.length === 0 && (
                <p className="var-picker__empty">Nenhuma variável disponível.</p>
              )}
              <ul className="var-picker__list">
                {vars.map((v) => (
                  <li
                    key={v.value}
                    className="var-picker__item"
                    onClick={() => insertVariable(v.value)}
                    title={`Inserir: ${v.value}`}
                  >
                    <div className="var-picker__label">{v.label}</div>
                    <div className="var-picker__path">
                      <code>{v.value}</code>
                      {(v.extra as any)?.example && (
                        <span className="var-picker__example">
                          → ex.: {(v.extra as any).example}
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}

          {tab === "registered" && (
            <>
              <p className="var-picker__hint">
                Insere o <strong>nome literal</strong> de algo já cadastrado
                no sistema (serviço, etapa, template). Útil para mencionar
                itens específicos no texto.
              </p>
              {!registeredLoaded && <p className="var-picker__loading">Carregando…</p>}
              {registeredLoaded && (
                REGISTERED_CATEGORIES.every((c) => registered[c.key].length === 0) ? (
                  <p className="var-picker__empty">
                    Nada cadastrado ainda. Crie em Serviços, Pipelines ou Templates.
                  </p>
                ) : (
                  <div className="var-picker__categories">
                    {REGISTERED_CATEGORIES.map((c) => {
                      const items = registered[c.key];
                      if (!items || items.length === 0) return null;
                      return (
                        <details key={c.key} className="var-picker__category" open>
                          <summary>
                            {c.icon} {c.label} <span className="var-picker__count">({items.length})</span>
                          </summary>
                          <ul className="var-picker__list">
                            {items.map((item) => (
                              <li
                                key={item.value}
                                className="var-picker__item"
                                onClick={() => insertVariable(item.label)}
                                title={`Inserir o nome: ${item.label}`}
                              >
                                <div className="var-picker__label">{item.label}</div>
                                <div className="var-picker__path">
                                  <span className="var-picker__example">
                                    Insere: <strong>{item.label}</strong>
                                  </span>
                                </div>
                              </li>
                            ))}
                          </ul>
                        </details>
                      );
                    })}
                  </div>
                )
              )}
            </>
          )}
        </div>
      )}
      {field.help && <p className="field__help">{field.help}</p>}
    </div>
  );
}


/**
 * Banner explicativo no Condition. Cliente reportou: 'essa parada
 * variavel num entendi'. Mostra exemplos práticos + sugere yes_no
 * como alternativa mais simples para perguntas SIM/NÃO.
 */
function ConditionHelpBanner() {
  return (
    <div className="condition-help">
      <div className="condition-help__suggestion">
        <strong>💡 Dica</strong>: se você quer apenas perguntar SIM/NÃO,
        use o bloco verde <strong>"Pergunta SIM/NÃO"</strong> — é bem mais
        simples. Esta "Condição avançada" só serve para verificar dados
        <em> já coletados</em> antes no fluxo.
      </div>
      <details className="condition-help__details">
        <summary>Como funciona esta Condição? (clique para ver exemplos)</summary>
        <div className="condition-help__body">
          <p>São 3 passos:</p>
          <ol>
            <li>
              <strong>Qual dado verificar?</strong> Escolha um dado que o bot
              já coletou em um bloco anterior (e-mail, telefone, nome...).
            </li>
            <li>
              <strong>Como comparar?</strong>
              <ul>
                <li><code>✓ Existe</code> — o campo foi preenchido?</li>
                <li><code>Contém</code> — o texto inclui uma palavra?</li>
                <li><code>= Igual a</code> — o texto é exatamente este?</li>
              </ul>
            </li>
            <li>
              <strong>Comparar com qual valor?</strong> Só preenche se você
              escolheu = / ≠ / contém / começa com.
            </li>
          </ol>
          <p className="condition-help__examples">
            <strong>Exemplos práticos:</strong>
          </p>
          <ul>
            <li>
              <em>"Cliente tem e-mail cadastrado?"</em> →
              dado: <code>E-mail</code>, comparar: <code>Existe</code>,
              valor: vazio.
            </li>
            <li>
              <em>"Usa Gmail?"</em> → dado: <code>E-mail</code>,
              comparar: <code>Contém</code>, valor: <code>gmail.com</code>.
            </li>
            <li>
              <em>"Empresa é específica?"</em> → dado: <code>Empresa</code>,
              comparar: <code>= Igual a</code>, valor: <code>Petrobras</code>.
            </li>
          </ul>
        </div>
      </details>
    </div>
  );
}

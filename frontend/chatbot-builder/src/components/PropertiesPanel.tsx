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
import { useEffect, useState } from "react";
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
      <div className="field">
        <label htmlFor={id}>{labelize(field)}</label>
        <textarea
          id={id}
          rows={3}
          maxLength={field.max_length ?? 5000}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
        {field.help && <p className="field__help">{field.help}</p>}
      </div>
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
    field: "Variável",
    operator: "Operador",
    value: "Valor de comparação",
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
    eq: "= (igual a)",
    neq: "≠ (diferente de)",
    contains: "contém",
    starts_with: "começa com",
    in: "está em (lista CSV)",
    regex: "regex",
    exists: "existe (campo preenchido)",
    not_exists: "não existe",
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

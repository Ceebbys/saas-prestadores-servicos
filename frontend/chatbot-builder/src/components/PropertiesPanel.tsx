/**
 * Painel direito — propriedades do bloco selecionado.
 *
 * Renderiza campos editáveis dinamicamente baseado no catálogo
 * (`data_fields` de cada NodeCatalogEntry).
 */
import { useBuilderStore } from "../store/builderStore";
import { MenuOptionsEditor } from "./MenuOptionsEditor";
import type { GraphNode, NodeCatalogField } from "../types";

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
              {opt || "(vazio)"}
            </option>
          ))}
        </select>
        {field.help && <p className="field__help">{field.help}</p>}
      </div>
    );
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
  };
  return map[field.name] ?? field.name;
}

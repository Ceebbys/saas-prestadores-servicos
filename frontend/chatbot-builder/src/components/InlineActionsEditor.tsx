/**
 * RV08 — Editor de ações inline em CADA bloco.
 *
 * Cliente pediu: "essa parada de ações tem q ta em todos os blocos tbm".
 * Cada bloco pode ter array de ações executadas automaticamente quando
 * o nó roda (igual ao editor legacy de ChatbotFlow.actions).
 *
 * Cada ação tem:
 * - action_type: dropdown com os 10 tipos (create_lead, update_pipeline,
 *   apply_tag, link_servico, send_email, send_whatsapp, send_proposal,
 *   send_contract, register_event, create_task)
 * - Campos específicos do action_type (mesmos do data_fields_per_action_type
 *   do bloco 'action' dedicado)
 * - is_active: checkbox para desativar individualmente
 *
 * Reusa o catálogo do bloco 'action' para descobrir campos.
 */
import { useState } from "react";
import { useBuilderStore } from "../store/builderStore";

interface InlineAction {
  action_type: string;
  is_active?: boolean;
  [key: string]: unknown;
}

interface Props {
  value: InlineAction[];
  onChange: (v: InlineAction[]) => void;
}

const ACTION_TYPE_LABELS: Record<string, string> = {
  create_lead: "Criar lead",
  update_pipeline: "Atualizar pipeline (etapa)",
  apply_tag: "Aplicar tag",
  link_servico: "Vincular serviço",
  register_event: "Registrar evento",
  send_email: "Enviar e-mail",
  send_whatsapp: "Enviar WhatsApp",
  send_proposal: "Enviar proposta",
  send_contract: "Enviar contrato",
  create_task: "Criar tarefa (em breve)",
};

const ACTION_TYPES_ORDER = [
  "create_lead",
  "update_pipeline",
  "apply_tag",
  "link_servico",
  "register_event",
  "send_email",
  "send_whatsapp",
  "send_proposal",
  "send_contract",
  "create_task",
];

export function InlineActionsEditor({ value, onChange }: Props) {
  const actionEntry = useBuilderStore((s) => s.getCatalogEntry("action"));
  const items: InlineAction[] = Array.isArray(value) ? value : [];

  function update(idx: number, patch: Partial<InlineAction>) {
    const next = items.slice();
    next[idx] = { ...next[idx], ...patch };
    onChange(next);
  }

  function add() {
    onChange([...items, { action_type: "create_lead", is_active: true }]);
  }

  function remove(idx: number) {
    onChange(items.filter((_, i) => i !== idx));
  }

  function move(idx: number, dir: -1 | 1) {
    const next = items.slice();
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= next.length) return;
    [next[idx], next[newIdx]] = [next[newIdx], next[idx]];
    onChange(next);
  }

  // Campos específicos por action_type (do catálogo do bloco action)
  function extraFieldsFor(actionType: string) {
    return (
      actionEntry?.data_fields_per_action_type?.[actionType] || []
    );
  }

  return (
    <div className="inline-actions">
      <p className="field__help">
        Cada bloco pode disparar uma ou mais ações automáticas ao ser
        executado. Ex: ao chegar neste bloco, criar lead + atualizar etapa
        do pipeline + enviar e-mail.
      </p>
      {items.length === 0 && (
        <p className="inline-actions__empty">
          Nenhuma ação configurada. Clique "Adicionar" abaixo.
        </p>
      )}
      <ul className="inline-actions__list">
        {items.map((action, idx) => {
          const extras = extraFieldsFor(action.action_type);
          return (
            <li key={idx} className="inline-actions__item">
              <div className="inline-actions__row">
                <select
                  value={action.action_type}
                  onChange={(e) =>
                    update(idx, { action_type: e.target.value })
                  }
                  className="inline-actions__type-select"
                >
                  {ACTION_TYPES_ORDER.map((at) => (
                    <option key={at} value={at}>
                      {ACTION_TYPE_LABELS[at] || at}
                    </option>
                  ))}
                </select>
                <label
                  className="inline-actions__active"
                  title="Ativa esta ação (desligue para desativar sem remover)"
                >
                  <input
                    type="checkbox"
                    checked={action.is_active !== false}
                    onChange={(e) =>
                      update(idx, { is_active: e.target.checked })
                    }
                  />
                  Ativa
                </label>
                <div className="inline-actions__buttons">
                  <button
                    type="button"
                    onClick={() => move(idx, -1)}
                    disabled={idx === 0}
                    title="Subir"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => move(idx, 1)}
                    disabled={idx === items.length - 1}
                    title="Descer"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(idx)}
                    className="inline-actions__remove"
                    title="Remover"
                  >
                    ×
                  </button>
                </div>
              </div>
              {/* Campos extras (action-type específicos) */}
              {extras.length > 0 && (
                <div className="inline-actions__extras">
                  {extras.map((f: any) => (
                    <InlineFieldEditor
                      key={f.name}
                      field={f}
                      value={action[f.name]}
                      onChange={(v) => update(idx, { [f.name]: v })}
                    />
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <button
        type="button"
        onClick={add}
        className="btn btn--secondary btn--small"
      >
        + Adicionar ação
      </button>
    </div>
  );
}


/**
 * Editor inline simplificado para um único campo do action_type.
 * Versão reduzida do FieldEditor do PropertiesPanel — apenas suporta
 * string/text/integer/boolean/enum (sem select dinâmico por enquanto
 * para evitar acoplar o componente ao fetchOptions).
 */
function InlineFieldEditor({
  field, value, onChange,
}: { field: any; value: unknown; onChange: (v: unknown) => void }) {
  if (field.type === "boolean") {
    return (
      <label className="inline-actions__field-bool">
        <input
          type="checkbox"
          checked={Boolean(value ?? field.default)}
          onChange={(e) => onChange(e.target.checked)}
        />
        {field.label || field.name}
      </label>
    );
  }
  if (field.type === "enum") {
    return (
      <div className="inline-actions__field">
        <label>{field.label || field.name}</label>
        <select
          value={(value as string) ?? (field.default as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
        >
          {(field.options || []).map((opt: string) => (
            <option key={opt} value={opt}>
              {opt || "(vazio)"}
            </option>
          ))}
        </select>
      </div>
    );
  }
  if (field.type === "integer") {
    return (
      <div className="inline-actions__field">
        <label>{field.label || field.name}</label>
        <input
          type="number"
          min={field.min}
          max={field.max}
          value={(value as number) ?? (field.default as number) ?? 0}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </div>
    );
  }
  if (field.type === "select") {
    // Para inline, mostra como text — usuário digita ID. Avançado pode
    // ser melhorado futuramente com fetchOptions.
    return (
      <div className="inline-actions__field">
        <label>{field.label || field.name}</label>
        <input
          type="text"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder={`ID (${field.source})`}
        />
      </div>
    );
  }
  if (field.type === "text") {
    return (
      <div className="inline-actions__field">
        <label>{field.label || field.name}</label>
        <textarea
          rows={2}
          maxLength={field.max_length ?? 1000}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
        {field.help && (
          <p className="inline-actions__field-help">{field.help}</p>
        )}
      </div>
    );
  }
  // string (default)
  return (
    <div className="inline-actions__field">
      <label>{field.label || field.name}</label>
      <input
        type="text"
        maxLength={field.max_length}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
      />
      {field.help && (
        <p className="inline-actions__field-help">{field.help}</p>
      )}
    </div>
  );
}

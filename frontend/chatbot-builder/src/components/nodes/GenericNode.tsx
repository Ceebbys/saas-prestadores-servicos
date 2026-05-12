/**
 * GenericNode — renderer único para start/message/question/collect_data/handoff/end/api_call.
 *
 * Renderiza handles in/out conforme catálogo + label + preview do texto.
 */
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useBuilderStore } from "../../store/builderStore";

const ACTION_TYPE_LABELS: Record<string, string> = {
  create_lead: "Criar lead",
  update_pipeline: "Atualizar pipeline",
  apply_tag: "Aplicar tag",
  link_servico: "Vincular serviço",
  register_event: "Registrar evento",
  send_email: "Enviar e-mail",
  send_whatsapp: "Enviar WhatsApp",
  create_task: "Criar tarefa",
};

function humanizeActionType(t: string): string {
  return ACTION_TYPE_LABELS[t] ?? t;
}

export function GenericNode({ id, data, type, selected }: NodeProps) {
  const entry = useBuilderStore((s) => s.getCatalogEntry(type as string));
  if (!entry) {
    return <div className="rf-node rf-node--error">Tipo desconhecido: {type}</div>;
  }
  const color = entry.color;
  const isComingSoon = entry.status === "coming_soon";

  // Preview do conteúdo principal (texto/prompt/welcome_message ou tipo da ação)
  const previewText =
    (data as any).text ||
    (data as any).prompt ||
    (data as any).welcome_message ||
    (data as any).completion_message ||
    (data as any).message_to_user ||
    (type === "action" && (data as any).action_type
      ? `→ ${humanizeActionType((data as any).action_type)}`
      : "") ||
    "";

  return (
    <div
      className={`rf-node ${selected ? "rf-node--selected" : ""} ${isComingSoon ? "rf-node--coming-soon" : ""}`}
      style={{ borderTopColor: color }}
    >
      {entry.handles.in && (
        <Handle type="target" position={Position.Top} id="in" />
      )}
      <div className="rf-node__header" style={{ background: color }}>
        <span className="rf-node__title">{(data as any).label || entry.label}</span>
        {isComingSoon && <span className="rf-node__soon">em breve</span>}
      </div>
      {previewText && (
        <div className="rf-node__body">
          <p className="rf-node__preview">{String(previewText).slice(0, 100)}</p>
        </div>
      )}
      {entry.handles.out && entry.handles.out.length === 1 && (
        <Handle
          type="source"
          position={Position.Bottom}
          id={entry.handles.out[0]}
        />
      )}
    </div>
  );
}

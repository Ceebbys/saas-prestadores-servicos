/**
 * ConditionNode — 2 handles de saída fixos (true/false).
 */
import { Handle, Position, type NodeProps } from "@xyflow/react";

export function ConditionNode({ data, selected }: NodeProps) {
  const label = (data as any).label || "Condição";
  const field = (data as any).field || "";
  const operator = (data as any).operator || "";
  const value = (data as any).value || "";
  const summary = field ? `${field} ${operator || "?"} ${value}` : "Configurar condição";

  return (
    <div
      className={`rf-node rf-node--condition ${selected ? "rf-node--selected" : ""}`}
      style={{ borderTopColor: "#f59e0b" }}
    >
      <Handle type="target" position={Position.Top} id="in" />
      <div className="rf-node__header" style={{ background: "#f59e0b" }}>
        <span className="rf-node__title">{label}</span>
      </div>
      <div className="rf-node__body">
        <p className="rf-node__preview">{summary}</p>
        <div className="rf-node__branches">
          <div className="rf-node__branch rf-node__branch--true">
            <span>SIM</span>
            <Handle
              type="source"
              position={Position.Right}
              id="true"
              style={{ background: "#10b981", position: "relative", top: 0, transform: "none" }}
            />
          </div>
          <div className="rf-node__branch rf-node__branch--false">
            <span>NÃO</span>
            <Handle
              type="source"
              position={Position.Right}
              id="false"
              style={{ background: "#ef4444", position: "relative", top: 0, transform: "none" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * YesNoNode — pergunta com 2 handles SIM/NÃO. Mais simples que Condition
 * (que exige field+operator+value). Usado para perguntas diretas tipo
 * "Você é pessoa jurídica?" → ramo SIM e ramo NÃO.
 */
import { Handle, Position, type NodeProps } from "@xyflow/react";

export function YesNoNode({ data, selected }: NodeProps) {
  const label = (data as any).label || "SIM/NÃO";
  const prompt: string = (data as any).prompt || "";

  return (
    <div
      className={`rf-node rf-node--yes-no ${selected ? "rf-node--selected" : ""}`}
      style={{ borderTopColor: "#22c55e" }}
    >
      <Handle type="target" position={Position.Top} id="in" />
      <div className="rf-node__header" style={{ background: "#22c55e" }}>
        <span className="rf-node__title">{label}</span>
      </div>
      <div className="rf-node__body">
        {prompt ? (
          <p className="rf-node__preview">{prompt.slice(0, 80)}{prompt.length > 80 ? "…" : ""}</p>
        ) : (
          <p className="rf-node__empty">Configure a pergunta</p>
        )}
        <div className="rf-node__branches">
          <div className="rf-node__branch rf-node__branch--true">
            <span>✓ SIM</span>
            <Handle
              type="source"
              position={Position.Right}
              id="yes"
              style={{ background: "#10b981", position: "relative", top: 0, transform: "none" }}
            />
          </div>
          <div className="rf-node__branch rf-node__branch--false">
            <span>✗ NÃO</span>
            <Handle
              type="source"
              position={Position.Right}
              id="no"
              style={{ background: "#ef4444", position: "relative", top: 0, transform: "none" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

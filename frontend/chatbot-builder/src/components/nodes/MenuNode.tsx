/**
 * MenuNode — renderiza handles dinâmicos (1 por option).
 */
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { MenuOption } from "../../types";

export function MenuNode({ data, selected }: NodeProps) {
  const options: MenuOption[] = ((data as any).options || []) as MenuOption[];
  const prompt: string = (data as any).prompt || "";
  const label: string = (data as any).label || "Menu";

  return (
    <div
      className={`rf-node rf-node--menu ${selected ? "rf-node--selected" : ""}`}
      style={{ borderTopColor: "#0ea5e9" }}
    >
      <Handle type="target" position={Position.Top} id="in" />
      <div className="rf-node__header" style={{ background: "#0ea5e9" }}>
        <span className="rf-node__title">{label}</span>
      </div>
      <div className="rf-node__body">
        {prompt && <p className="rf-node__preview">{prompt.slice(0, 80)}</p>}
        <div className="rf-node__options">
          {options.length === 0 ? (
            <p className="rf-node__empty">Sem opções configuradas</p>
          ) : (
            options.map((opt) => (
              <div key={opt.handle_id} className="rf-node__option">
                <span className="rf-node__option-label">{opt.label}</span>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={opt.handle_id}
                  style={{ position: "relative", top: 0, transform: "none" }}
                />
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

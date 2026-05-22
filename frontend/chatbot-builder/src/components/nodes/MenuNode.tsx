/**
 * MenuNode — renderiza handles dinâmicos (1 por option).
 *
 * RV06 — Cada opção mostra indicador visual quando NÃO está conectada
 * a nenhum próximo bloco (handle órfão). Ajuda o usuário a saber onde
 * arrastar a conexão antes de validar.
 */
import { useMemo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useBuilderStore } from "../../store/builderStore";
import type { MenuOption } from "../../types";

export function MenuNode({ id, data, selected }: NodeProps) {
  const options: MenuOption[] = ((data as any).options || []) as MenuOption[];
  const prompt: string = (data as any).prompt || "";
  const label: string = (data as any).label || "Menu";
  const edges = useBuilderStore((s) => s.edges);

  // RV06 — set de handle_ids que TÊM edge saindo deste menu
  const connectedHandles = useMemo(() => {
    const set = new Set<string>();
    for (const e of edges) {
      if (e.source === id && e.sourceHandle) set.add(e.sourceHandle);
    }
    return set;
  }, [edges, id]);

  const unconnectedCount = options.filter(
    (o) => !connectedHandles.has(o.handle_id),
  ).length;

  return (
    <div
      className={`rf-node rf-node--menu ${selected ? "rf-node--selected" : ""}`}
      style={{ borderTopColor: "#0ea5e9" }}
    >
      <Handle type="target" position={Position.Top} id="in" />
      <div className="rf-node__header" style={{ background: "#0ea5e9" }}>
        <span className="rf-node__title">{label}</span>
        {unconnectedCount > 0 && (
          <span
            className="rf-node__warning-badge"
            title={`${unconnectedCount} opção(ões) sem conexão`}
          >
            ⚠ {unconnectedCount}
          </span>
        )}
      </div>
      <div className="rf-node__body">
        {prompt && <p className="rf-node__preview">{prompt.slice(0, 80)}</p>}
        <div className="rf-node__options">
          {options.length === 0 ? (
            <p className="rf-node__empty">Sem opções configuradas</p>
          ) : (
            options.map((opt) => {
              const isConnected = connectedHandles.has(opt.handle_id);
              return (
                <div
                  key={opt.handle_id}
                  className={`rf-node__option ${
                    !isConnected ? "rf-node__option--unconnected" : ""
                  }`}
                  title={
                    !isConnected
                      ? "⚠ Esta opção não está conectada — arraste do círculo à direita para um bloco"
                      : undefined
                  }
                >
                  {!isConnected && (
                    <span className="rf-node__option-icon" aria-label="sem conexão">
                      ⚠
                    </span>
                  )}
                  <span className="rf-node__option-label">{opt.label}</span>
                  <Handle
                    type="source"
                    position={Position.Right}
                    id={opt.handle_id}
                    className={!isConnected ? "rf-handle--unconnected" : ""}
                    style={{ position: "relative", top: 0, transform: "none" }}
                  />
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

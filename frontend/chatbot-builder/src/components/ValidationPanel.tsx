/**
 * RV06 Hotfix — Painel lateral que LISTA os erros/avisos de validação.
 *
 * Antes desta correção, o alert "X erros — confira o painel" mentia: não
 * existia painel. Os erros só apareciam como borda vermelha nos nodes e
 * dentro do PropertiesPanel do node selecionado. Agora há uma listagem
 * completa, com clique para focar o node correspondente no canvas.
 */
import { useMemo } from "react";
import { useBuilderStore } from "../store/builderStore";
import type { GraphNode, ValidationIssue } from "../types";

interface ValidationPanelProps {
  open: boolean;
  onClose: () => void;
}

export function ValidationPanel({ open, onClose }: ValidationPanelProps) {
  const errors = useBuilderStore((s) => s.validationErrors);
  const warnings = useBuilderStore((s) => s.validationWarnings);
  const nodes = useBuilderStore((s) => s.nodes);
  const requestFocusNode = useBuilderStore((s) => s.requestFocusNode);

  const total = errors.length + warnings.length;

  // Mapa node_id → node, para mostrar label legível
  const nodeMap = useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

  function nodeLabel(nodeId: string | null | undefined): string {
    if (!nodeId) return "Fluxo (geral)";
    const node = nodeMap.get(nodeId);
    if (!node) return nodeId;
    const customLabel = (node.data?.label as string) || "";
    return customLabel ? `${customLabel} (${node.type})` : `${node.type}`;
  }

  function focusNode(nodeId: string | null | undefined) {
    if (!nodeId) return;
    if (!nodeMap.has(nodeId)) return;
    requestFocusNode(nodeId);
  }

  if (!open) return null;

  return (
    <aside className="validation-panel">
      <div className="validation-panel__header">
        <div>
          <h3 className="validation-panel__title">
            {errors.length > 0
              ? "Fluxo inválido"
              : warnings.length > 0
              ? "Fluxo com avisos"
              : "Fluxo válido"}
          </h3>
          <p className="validation-panel__subtitle">
            {errors.length > 0 && (
              <span className="validation-panel__count validation-panel__count--error">
                {errors.length} erro{errors.length === 1 ? "" : "s"}
              </span>
            )}
            {warnings.length > 0 && (
              <span className="validation-panel__count validation-panel__count--warning">
                {warnings.length} aviso{warnings.length === 1 ? "" : "s"}
              </span>
            )}
            {total === 0 && <span>Nenhum problema encontrado.</span>}
          </p>
        </div>
        <button
          className="validation-panel__close"
          onClick={onClose}
          title="Fechar painel"
          aria-label="Fechar"
        >
          ×
        </button>
      </div>

      <div className="validation-panel__body">
        {total === 0 && (
          <div className="validation-panel__empty">
            <div className="validation-panel__empty-icon">✓</div>
            <p>Tudo certo! Clique em Publicar quando quiser ativar.</p>
          </div>
        )}

        {errors.length > 0 && (
          <ValidationSection
            title="Erros — precisam ser corrigidos antes de publicar"
            kind="error"
            issues={errors}
            nodeLabel={nodeLabel}
            onClick={focusNode}
          />
        )}

        {warnings.length > 0 && (
          <ValidationSection
            title="Avisos — não bloqueiam, mas vale revisar"
            kind="warning"
            issues={warnings}
            nodeLabel={nodeLabel}
            onClick={focusNode}
          />
        )}
      </div>
    </aside>
  );
}


interface SectionProps {
  title: string;
  kind: "error" | "warning";
  issues: ValidationIssue[];
  nodeLabel: (nodeId: string | null | undefined) => string;
  onClick: (nodeId: string | null | undefined) => void;
}

function ValidationSection({ title, kind, issues, nodeLabel, onClick }: SectionProps) {
  return (
    <section className={`validation-section validation-section--${kind}`}>
      <h4 className="validation-section__title">{title}</h4>
      <ul className="validation-section__list">
        {issues.map((issue, i) => (
          <li
            key={`${issue.code}-${issue.node_id ?? "_"}-${i}`}
            className={`validation-item validation-item--${kind} ${
              issue.node_id ? "validation-item--clickable" : ""
            }`}
            onClick={() => onClick(issue.node_id)}
            role={issue.node_id ? "button" : undefined}
            tabIndex={issue.node_id ? 0 : undefined}
            onKeyDown={(e) => {
              if (issue.node_id && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                onClick(issue.node_id);
              }
            }}
            title={
              issue.node_id ? "Clique para localizar este bloco no fluxo" : undefined
            }
          >
            <span className="validation-item__icon">{kind === "error" ? "✕" : "!"}</span>
            <div className="validation-item__body">
              <div className="validation-item__node">{nodeLabel(issue.node_id)}</div>
              <div className="validation-item__message">{issue.message}</div>
              {issue.field && (
                <div className="validation-item__field">campo: {issue.field}</div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

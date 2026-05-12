/**
 * V2C — Browser de templates pré-prontos de fluxo.
 *
 * Modal que lista templates do backend. Ao escolher um, aplica ao draft
 * via POST /apply-template/ e recarrega o graph no canvas.
 */
import { useEffect, useState } from "react";
import { useBuilderStore } from "../store/builderStore";
import { useGraphAPI } from "../hooks/useGraphAPI";

interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  color: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export function TemplateBrowser({ open, onClose }: Props) {
  const config = useBuilderStore((s) => s.config);
  const setGraph = useBuilderStore((s) => s.setGraph);
  const markClean = useBuilderStore((s) => s.markClean);
  const { reloadGraph } = useGraphAPI();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !config) return;
    setLoading(true);
    fetch(config.endpoints.flowTemplates, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then((r) => r.json())
      .then((data) => {
        setTemplates(data.templates || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [open, config]);

  async function applyTemplate(template: Template) {
    if (!config) return;
    if (!confirm(
      `Aplicar template "${template.name}"? O conteúdo atual do fluxo será substituído.`,
    )) return;

    setApplying(template.id);
    try {
      const resp = await fetch(config.endpoints.applyTemplate, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": config.csrfToken,
        },
        body: JSON.stringify({ template_id: template.id }),
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      // Recarrega o graph do servidor
      const newGraph = await reloadGraph();
      if (newGraph) {
        setGraph(newGraph);
        markClean();
      }
      onClose();
    } catch (err) {
      alert(`Erro ao aplicar template: ${err}`);
    } finally {
      setApplying(null);
    }
  }

  if (!open) return null;

  return (
    <div className="template-browser__overlay" onClick={onClose}>
      <div className="template-browser" onClick={(e) => e.stopPropagation()}>
        <div className="template-browser__header">
          <div>
            <h2>Templates de fluxo</h2>
            <p>Comece a partir de um modelo pronto. Você pode editar tudo depois.</p>
          </div>
          <button className="btn btn--ghost btn--small" onClick={onClose}>×</button>
        </div>

        <div className="template-browser__body">
          {loading && <p>Carregando templates…</p>}
          {!loading && templates.length === 0 && <p>Nenhum template disponível.</p>}
          <div className="template-grid">
            {templates.map((t) => (
              <div key={t.id} className="template-card" style={{ borderTopColor: t.color }}>
                <div className="template-card__icon" style={{ background: t.color }}>
                  {iconFor(t.icon)}
                </div>
                <h3>{t.name}</h3>
                <p>{t.description}</p>
                <button
                  className="btn btn--primary btn--small"
                  onClick={() => applyTemplate(t)}
                  disabled={applying !== null}
                >
                  {applying === t.id ? "Aplicando…" : "Usar este template"}
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function iconFor(icon: string): string {
  const map: Record<string, string> = {
    users: "👥",
    "list-bullet": "≡",
    funnel: "⊽",
    star: "★",
  };
  return map[icon] ?? "▢";
}

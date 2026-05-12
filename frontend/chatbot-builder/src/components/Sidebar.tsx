/**
 * Sidebar (paleta) — lista de blocos arrastáveis agrupados por categoria.
 *
 * Drag-and-drop usa o evento HTML5 nativo. O Canvas recebe o `drop`
 * com o tipo do bloco em `application/x-chatbot-builder-node`.
 */
import { useBuilderStore } from "../store/builderStore";
import type { NodeCatalogEntry } from "../types";

function BlockCard({ entry }: { entry: NodeCatalogEntry }) {
  const isComingSoon = entry.status === "coming_soon";

  function onDragStart(event: React.DragEvent<HTMLDivElement>) {
    if (isComingSoon) {
      event.preventDefault();
      return;
    }
    event.dataTransfer.setData("application/x-chatbot-builder-node", entry.type);
    event.dataTransfer.effectAllowed = "move";
  }

  return (
    <div
      className={`block-card ${isComingSoon ? "block-card--disabled" : ""}`}
      draggable={!isComingSoon}
      onDragStart={onDragStart}
      title={entry.description}
      style={{ borderLeftColor: entry.color }}
    >
      <div className="block-card__icon" style={{ background: entry.color }}>
        {iconFor(entry.icon)}
      </div>
      <div className="block-card__info">
        <div className="block-card__label">{entry.label}</div>
        <div className="block-card__desc">{entry.description}</div>
      </div>
      {isComingSoon && <div className="block-card__badge">Em breve</div>}
    </div>
  );
}

// Glyphs minimalistas para ícones (sem dependência externa)
function iconFor(icon: string): string {
  const map: Record<string, string> = {
    "play-circle": "▶",
    "chat-bubble-left": "💬",
    "question-mark-circle": "?",
    "list-bullet": "≡",
    "git-branch": "⎇",
    "identification": "ID",
    "bolt": "⚡",
    "user-group": "👥",
    "check-circle": "✓",
  };
  return map[icon] ?? "▢";
}

export function Sidebar() {
  const catalog = useBuilderStore((s) => s.catalog);
  if (!catalog) return null;

  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <h2>Blocos</h2>
        <p className="sidebar__hint">Arraste para o canvas</p>
      </div>
      <div className="sidebar__categories">
        {catalog.categories.map((cat) => {
          const blocks = catalog.nodes.filter((n) => n.category === cat.slug);
          if (blocks.length === 0) return null;
          return (
            <section key={cat.slug} className="sidebar__category">
              <h3 className="sidebar__category-title">{cat.label}</h3>
              <div className="sidebar__blocks">
                {blocks.map((b) => (
                  <BlockCard key={b.type} entry={b} />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </aside>
  );
}

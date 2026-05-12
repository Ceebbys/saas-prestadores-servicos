/**
 * Editor de options de menu — UI especializada para gerenciar lista de
 * {label, value, handle_id}.
 */
import type { MenuOption } from "../types";

interface Props {
  value: MenuOption[];
  onChange: (v: MenuOption[]) => void;
}

let counter = 0;
function nextHandleId() {
  counter += 1;
  return `opt_${Date.now()}_${counter}`;
}

export function MenuOptionsEditor({ value, onChange }: Props) {
  function update(idx: number, patch: Partial<MenuOption>) {
    const next = value.slice();
    next[idx] = { ...next[idx], ...patch };
    onChange(next);
  }

  function add() {
    onChange([...value, { label: "", handle_id: nextHandleId() }]);
  }

  function remove(idx: number) {
    onChange(value.filter((_, i) => i !== idx));
  }

  function move(idx: number, dir: -1 | 1) {
    const next = value.slice();
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= next.length) return;
    [next[idx], next[newIdx]] = [next[newIdx], next[idx]];
    onChange(next);
  }

  return (
    <div className="field">
      <label>Opções do menu</label>
      <p className="field__help">Cada opção gera uma saída. Mínimo 2.</p>
      <div className="menu-options">
        {value.length === 0 && (
          <p className="menu-options__empty">Nenhuma opção. Clique "Adicionar".</p>
        )}
        {value.map((opt, idx) => (
          <div key={opt.handle_id || idx} className="menu-options__row">
            <input
              type="text"
              placeholder="Texto da opção"
              value={opt.label}
              onChange={(e) => update(idx, { label: e.target.value })}
              maxLength={200}
            />
            <div className="menu-options__actions">
              <button
                type="button"
                onClick={() => move(idx, -1)}
                disabled={idx === 0}
                title="Mover para cima"
              >
                ↑
              </button>
              <button
                type="button"
                onClick={() => move(idx, 1)}
                disabled={idx === value.length - 1}
                title="Mover para baixo"
              >
                ↓
              </button>
              <button
                type="button"
                className="menu-options__remove"
                onClick={() => remove(idx)}
                title="Remover"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>
      <button type="button" className="btn btn--secondary btn--small" onClick={add}>
        + Adicionar opção
      </button>
    </div>
  );
}

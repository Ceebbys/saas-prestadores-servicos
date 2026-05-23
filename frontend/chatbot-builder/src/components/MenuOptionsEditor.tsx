/**
 * Editor de options de menu — UI especializada para gerenciar lista de
 * {label, value, handle_id, servico_id}.
 *
 * RV06 — Cada opção pode vincular um Serviço Pré-Fixado. Quando o
 * cliente escolhe essa opção no fluxo, o `lead.servico` é setado
 * automaticamente (igual ao ChatbotChoice.servico do editor legacy).
 */
import { useEffect, useState } from "react";
import { useGraphAPI } from "../hooks/useGraphAPI";
import type { MenuOption, OptionItem } from "../types";

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
  // RV06 — Carrega lista de serviços para o dropdown (cache 30s no hook)
  const { fetchOptions } = useGraphAPI();
  const [services, setServices] = useState<OptionItem[]>([]);
  const [servicesLoading, setServicesLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    fetchOptions("services")
      .then((list) => {
        if (alive) {
          setServices(list);
          setServicesLoading(false);
        }
      })
      .catch(() => {
        if (alive) setServicesLoading(false);
      });
    return () => { alive = false; };
  }, [fetchOptions]);

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
      <p className="field__help">
        Cada opção gera uma saída. Mínimo 2.
        {services.length > 0 && (
          <> Você pode vincular um <strong>serviço</strong> a cada opção —
          quando o cliente escolher, o serviço é atribuído automaticamente
          ao lead.</>
        )}
      </p>
      <div className="menu-options">
        {value.length === 0 && (
          <p className="menu-options__empty">Nenhuma opção. Clique "Adicionar".</p>
        )}
        {value.map((opt, idx) => (
          <div key={opt.handle_id || idx} className="menu-options__row menu-options__row--with-servico">
            <div className="menu-options__main">
              <input
                type="text"
                placeholder="Texto da opção (ex.: Topografia)"
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
            {/* RV06 — Dropdown opcional de serviço vinculado */}
            <div className="menu-options__servico">
              <label className="menu-options__servico-label">
                🔗 Serviço associado
              </label>
              <select
                value={String(opt.servico_id ?? "")}
                onChange={(e) =>
                  update(idx, {
                    servico_id: e.target.value || null,
                  })
                }
                disabled={servicesLoading}
                title="Quando o cliente escolher esta opção, o serviço é atribuído automaticamente"
              >
                <option value="">
                  {servicesLoading
                    ? "Carregando…"
                    : services.length === 0
                    ? "— nenhum serviço cadastrado —"
                    : "— sem serviço —"}
                </option>
                {services.map((s) => {
                  const price = (s.extra as any)?.price;
                  const prazo = (s.extra as any)?.prazo_dias;
                  const suffix = price
                    ? ` (R$ ${price}${prazo ? ` · ${prazo}d` : ""})`
                    : "";
                  return (
                    <option key={s.value} value={s.value}>
                      {s.label}
                      {suffix}
                    </option>
                  );
                })}
              </select>
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

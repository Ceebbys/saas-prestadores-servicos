/**
 * V2B — Simulador inline do chatbot.
 *
 * Drawer lateral à direita (overlay sobre o canvas) com chat fake.
 * Usa endpoints /simulator/start/ e /simulator/step/ que executam o DRAFT
 * graph (não a versão publicada) sem persistir nada.
 */
import { useEffect, useRef, useState } from "react";
import { useBuilderStore } from "../store/builderStore";

interface Message {
  direction: "inbound" | "outbound" | "system";
  content: string;
  node_id?: string;
}

interface SimState {
  session_key?: string;
  current_node_id?: string;
  lead_data?: Record<string, unknown>;
  messages?: Message[];
  is_complete?: boolean;
  step?: {
    id: string;
    type: string;
    prompt: string;
    options?: { label: string; value: string }[] | null;
  } | null;
  completion_reason?: string;
  error?: boolean;
  message?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export function Simulator({ open, onClose }: Props) {
  const config = useBuilderStore((s) => s.config);
  const [state, setState] = useState<SimState>({});
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [allMessages, setAllMessages] = useState<Message[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-start ao abrir
  useEffect(() => {
    if (!open || !config) return;
    setLoading(true);
    setAllMessages([]);
    fetch(config.endpoints.simulatorStart, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": config.csrfToken,
      },
      body: "{}",
    })
      .then((r) => r.json())
      .then((result: SimState) => {
        setState(result);
        if (result.messages) setAllMessages(result.messages);
        setLoading(false);
      })
      .catch((err) => {
        setState({ error: true, message: String(err) });
        setLoading(false);
      });
  }, [open, config]);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [allMessages]);

  function send() {
    if (!config || !input.trim() || loading || state.is_complete) return;
    const userMsg: Message = { direction: "inbound", content: input };
    setAllMessages((prev) => [...prev, userMsg]);
    const responseText = input;
    setInput("");
    setLoading(true);

    fetch(config.endpoints.simulatorStep, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": config.csrfToken,
      },
      body: JSON.stringify({ state, response: responseText }),
    })
      .then((r) => r.json())
      .then((result: SimState) => {
        setState(result);
        // Merge new messages (server retorna o estado completo)
        if (result.messages) {
          // Mensagens novas são as do server menos as que já temos
          setAllMessages(result.messages);
        }
        setLoading(false);
      })
      .catch((err) => {
        setAllMessages((prev) => [
          ...prev,
          { direction: "system", content: `Erro: ${String(err)}` },
        ]);
        setLoading(false);
      });
  }

  function reset() {
    setState({});
    setAllMessages([]);
    setInput("");
    // Re-dispara start
    if (config) {
      setLoading(true);
      fetch(config.endpoints.simulatorStart, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": config.csrfToken,
        },
        body: "{}",
      })
        .then((r) => r.json())
        .then((result: SimState) => {
          setState(result);
          if (result.messages) setAllMessages(result.messages);
          setLoading(false);
        });
    }
  }

  if (!open) return null;

  return (
    <div className="simulator-drawer">
      <div className="simulator-drawer__header">
        <div>
          <h3>Simulador</h3>
          <p className="simulator-drawer__hint">Rodando draft (não publicado)</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn--ghost btn--small" onClick={reset} disabled={loading}>
            Reiniciar
          </button>
          <button className="btn btn--ghost btn--small" onClick={onClose}>
            ×
          </button>
        </div>
      </div>

      <div className="simulator-drawer__messages" ref={scrollRef}>
        {allMessages.length === 0 && !loading && (
          <p className="simulator-drawer__empty">Inicializando…</p>
        )}
        {allMessages.map((m, i) => (
          <div key={i} className={`sim-msg sim-msg--${m.direction}`}>
            <p>{m.content}</p>
            {m.node_id && (
              <span className="sim-msg__node">{m.node_id}</span>
            )}
          </div>
        ))}
        {loading && <p className="simulator-drawer__loading">…</p>}
        {state.is_complete && (
          <div className="sim-msg sim-msg--system">
            <strong>Conversa encerrada</strong>
            {state.completion_reason && (
              <p style={{ fontSize: 11, opacity: 0.7 }}>{state.completion_reason}</p>
            )}
          </div>
        )}
        {state.error && (
          <div className="sim-msg sim-msg--system" style={{ background: "#fee2e2", color: "#991b1b" }}>
            <strong>Erro:</strong> {state.message}
          </div>
        )}
      </div>

      {/* Botões de quick-reply para menu */}
      {state.step?.type === "menu" && state.step.options && !state.is_complete && (
        <div className="simulator-drawer__quick-replies">
          {state.step.options.map((opt) => (
            <button
              key={opt.value}
              className="btn btn--secondary btn--small"
              onClick={() => {
                setInput(opt.label);
                setTimeout(send, 0);
              }}
              disabled={loading}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}

      <div className="simulator-drawer__input">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
          placeholder={state.is_complete ? "Conversa encerrada" : "Sua resposta…"}
          disabled={loading || state.is_complete}
        />
        <button
          className="btn btn--primary btn--small"
          onClick={send}
          disabled={loading || state.is_complete || !input.trim()}
        >
          Enviar
        </button>
      </div>
    </div>
  );
}

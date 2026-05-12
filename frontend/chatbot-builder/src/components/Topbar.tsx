/**
 * Topbar do builder: nome + status + indicador de salvamento + ações.
 */
import { useState } from "react";
import { useBuilderStore } from "../store/builderStore";
import { useGraphAPI } from "../hooks/useGraphAPI";

function SaveIndicator() {
  const saveState = useBuilderStore((s) => s.saveState);
  const lastSavedAt = useBuilderStore((s) => s.lastSavedAt);
  const isDirty = useBuilderStore((s) => s.isDirty);

  if (saveState === "saving") {
    return <span className="save-indicator save-indicator--saving">Salvando…</span>;
  }
  if (saveState === "error") {
    return <span className="save-indicator save-indicator--error">Erro ao salvar</span>;
  }
  if (isDirty) {
    return <span className="save-indicator save-indicator--dirty">Alterações não salvas</span>;
  }
  if (lastSavedAt) {
    const d = new Date(lastSavedAt);
    return <span className="save-indicator save-indicator--saved">Salvo às {d.toLocaleTimeString().slice(0, 5)}</span>;
  }
  return null;
}

export function Topbar() {
  const config = useBuilderStore((s) => s.config);
  const setValidation = useBuilderStore((s) => s.setValidation);
  const setSaveState = useBuilderStore((s) => s.setSaveState);
  const markClean = useBuilderStore((s) => s.markClean);
  const { saveDraft, validate, publish } = useGraphAPI();
  const [busy, setBusy] = useState<string | null>(null);
  const [publishMsg, setPublishMsg] = useState<string | null>(null);
  const useVisualBuilder = useBuilderStore((s) => s.config?.useVisualBuilder);

  async function handleSave() {
    setBusy("save");
    setSaveState("saving");
    const r = await saveDraft();
    setSaveState(r.ok ? "saved" : "error", r.saved_at);
    if (r.ok) markClean();
    setBusy(null);
  }

  async function handleValidate() {
    setBusy("validate");
    // Garante que o draft está salvo antes
    await saveDraft();
    markClean();
    const result = await validate();
    if (result) {
      setValidation(result.errors, result.warnings);
      if (result.valid && result.warnings.length === 0) {
        alert("✓ Fluxo válido — sem erros nem avisos.");
      } else if (result.valid) {
        alert(`✓ Fluxo válido (${result.warnings.length} aviso(s)).`);
      } else {
        alert(`✗ Fluxo inválido — ${result.errors.length} erro(s). Confira o painel.`);
      }
    }
    setBusy(null);
  }

  async function handlePublish() {
    if (!confirm("Publicar este fluxo? Ele será usado pelo motor de execução do chatbot.")) return;
    setBusy("publish");
    // Salva antes
    await saveDraft();
    markClean();
    const r = await publish();
    if (r.ok) {
      setPublishMsg(`Publicado! Versão #${r.data.numero}`);
      setTimeout(() => setPublishMsg(null), 4000);
    } else if (r.status === 422 && r.data.errors) {
      setValidation(r.data.errors, r.data.warnings ?? []);
      alert(`Fluxo inválido — ${r.data.errors.length} erro(s). Corrija antes de publicar.`);
    } else {
      alert(`Erro ao publicar: ${r.data.error ?? "desconhecido"}`);
    }
    setBusy(null);
  }

  return (
    <header className="topbar">
      <div className="topbar__left">
        <a href={config?.flowListUrl} className="topbar__back" title="Voltar para lista">
          ← Fluxos
        </a>
        <div className="topbar__title-block">
          <h1 className="topbar__title">{config?.flowName ?? "Fluxo"}</h1>
          <div className="topbar__meta">
            {useVisualBuilder ? (
              <span className="badge badge--primary">Visual</span>
            ) : (
              <span className="badge badge--neutral">Rascunho</span>
            )}
            <SaveIndicator />
          </div>
        </div>
      </div>
      <div className="topbar__right">
        {publishMsg && <span className="topbar__published-msg">{publishMsg}</span>}
        <button
          className="btn btn--ghost"
          onClick={handleValidate}
          disabled={busy !== null}
        >
          Validar
        </button>
        <button
          className="btn btn--secondary"
          onClick={handleSave}
          disabled={busy !== null}
        >
          {busy === "save" ? "Salvando…" : "Salvar"}
        </button>
        <button
          className="btn btn--primary"
          onClick={handlePublish}
          disabled={busy !== null}
        >
          {busy === "publish" ? "Publicando…" : "Publicar"}
        </button>
      </div>
    </header>
  );
}

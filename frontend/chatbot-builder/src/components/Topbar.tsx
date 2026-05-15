/**
 * Topbar do builder: nome + status + indicador de salvamento + ações.
 */
import { useState } from "react";
import { useBuilderStore } from "../store/builderStore";
import { useGraphAPI } from "../hooks/useGraphAPI";

function SimulatorToggle() {
  const open = useBuilderStore((s) => s.simulatorOpen);
  const setOpen = useBuilderStore((s) => s.setSimulatorOpen);
  return (
    <button
      className={`btn ${open ? "btn--secondary" : "btn--ghost"}`}
      onClick={() => setOpen(!open)}
      title="Testar fluxo (draft, sem persistir)"
    >
      {open ? "Fechar simulador" : "Testar"}
    </button>
  );
}


function TemplatesButton() {
  const setOpen = useBuilderStore((s) => s.setTemplateBrowserOpen);
  return (
    <button
      className="btn btn--ghost"
      onClick={() => setOpen(true)}
      title="Aplicar template pronto"
    >
      Templates
    </button>
  );
}


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
  const setValidationPanelOpen = useBuilderStore((s) => s.setValidationPanelOpen);
  const validationErrors = useBuilderStore((s) => s.validationErrors);
  const validationWarnings = useBuilderStore((s) => s.validationWarnings);
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
      // RV06 Hotfix — abre o painel SEMPRE que houver algo a mostrar.
      // Antes só mostrava um alert genérico ("X erros — confira o painel")
      // sem que o painel realmente existisse.
      if (result.errors.length > 0 || result.warnings.length > 0) {
        setValidationPanelOpen(true);
      } else {
        setValidationPanelOpen(true);
        // mantém aberto também no caso de sucesso para feedback positivo
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
      setValidationPanelOpen(true);
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
        <TemplatesButton />
        <SimulatorToggle />
        <button
          className={`btn btn--ghost validation-trigger ${
            validationErrors.length > 0 ? "validation-trigger--has-errors" : ""
          } ${
            validationErrors.length === 0 && validationWarnings.length > 0
              ? "validation-trigger--has-warnings"
              : ""
          }`}
          onClick={handleValidate}
          disabled={busy !== null}
          title={
            validationErrors.length > 0
              ? `${validationErrors.length} erro(s) pendente(s) — clique para revalidar`
              : validationWarnings.length > 0
              ? `${validationWarnings.length} aviso(s) — clique para revalidar`
              : "Validar fluxo"
          }
        >
          {busy === "validate" ? "Validando…" : "Validar"}
          {validationErrors.length > 0 && (
            <span className="validation-trigger__badge validation-trigger__badge--error">
              {validationErrors.length}
            </span>
          )}
          {validationErrors.length === 0 && validationWarnings.length > 0 && (
            <span className="validation-trigger__badge validation-trigger__badge--warning">
              {validationWarnings.length}
            </span>
          )}
        </button>
        {(validationErrors.length > 0 || validationWarnings.length > 0) && (
          <button
            className="btn btn--ghost"
            onClick={() => setValidationPanelOpen(true)}
            disabled={busy !== null}
            title="Reabrir painel de problemas"
          >
            Ver problemas
          </button>
        )}
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

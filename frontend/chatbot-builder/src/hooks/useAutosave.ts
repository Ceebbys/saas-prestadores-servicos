/**
 * Autosave debounced. Após mudança no graph, aguarda `delayMs` sem novas
 * mudanças e dispara saveDraft. Atualiza saveState no store.
 */
import { useEffect, useRef } from "react";
import { useBuilderStore } from "../store/builderStore";
import { useGraphAPI } from "./useGraphAPI";

export function useAutosave(delayMs: number = 1500) {
  const isDirty = useBuilderStore((s) => s.isDirty);
  const setSaveState = useBuilderStore((s) => s.setSaveState);
  const markClean = useBuilderStore((s) => s.markClean);
  const { saveDraft } = useGraphAPI();
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!isDirty) return;
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(async () => {
      setSaveState("saving");
      const result = await saveDraft();
      if (result.ok) {
        setSaveState("saved", result.saved_at);
        markClean();
      } else {
        setSaveState("error");
      }
    }, delayMs);

    return () => {
      if (timerRef.current) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, [isDirty, saveDraft, setSaveState, markClean, delayMs]);

  // Aviso antes de fechar com alterações não salvas
  useEffect(() => {
    function beforeUnload(e: BeforeUnloadEvent) {
      if (useBuilderStore.getState().isDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    }
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, []);
}

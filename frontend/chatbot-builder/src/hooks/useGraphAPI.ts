/**
 * Hook que expõe operações sobre o graph: save, validate, publish, init.
 *
 * Auth = cookie de sessão (same-origin). CSRF via header X-CSRFToken
 * lido do data-csrf-token attribute (no main.tsx).
 */
import { useCallback } from "react";
import { useBuilderStore } from "../store/builderStore";
import type { GraphJson, ValidationResult } from "../types";

interface PublishResult {
  published_version_id: number;
  numero: number;
  published_at: string;
}

export function useGraphAPI() {
  const config = useBuilderStore((s) => s.config);
  const toGraphJson = useBuilderStore((s) => s.toGraphJson);

  const headers = useCallback(
    () => ({
      "Content-Type": "application/json",
      "X-CSRFToken": config?.csrfToken ?? "",
      Accept: "application/json",
    }),
    [config?.csrfToken],
  );

  const saveDraft = useCallback(async (): Promise<{ ok: boolean; saved_at?: string; error?: string }> => {
    if (!config) return { ok: false, error: "no_config" };
    const graph = toGraphJson();
    const resp = await fetch(config.endpoints.save, {
      method: "POST",
      credentials: "same-origin",
      headers: headers(),
      body: JSON.stringify({ graph }),
    });
    if (resp.status === 429) {
      return { ok: false, error: "rate_limited" };
    }
    if (!resp.ok) {
      return { ok: false, error: `HTTP ${resp.status}` };
    }
    const data = await resp.json();
    return { ok: true, saved_at: data.saved_at };
  }, [config, headers, toGraphJson]);

  const validate = useCallback(async (): Promise<ValidationResult | null> => {
    if (!config) return null;
    const resp = await fetch(config.endpoints.validate, {
      method: "POST",
      credentials: "same-origin",
      headers: headers(),
      body: JSON.stringify({}),
    });
    if (!resp.ok) return null;
    return resp.json();
  }, [config, headers]);

  const publish = useCallback(async (): Promise<
    { ok: true; data: PublishResult } | { ok: false; status: number; data: any }
  > => {
    if (!config) return { ok: false, status: 0, data: { error: "no_config" } };
    const resp = await fetch(config.endpoints.publish, {
      method: "POST",
      credentials: "same-origin",
      headers: headers(),
      body: JSON.stringify({}),
    });
    const data = await resp.json();
    if (!resp.ok) {
      return { ok: false, status: resp.status, data };
    }
    return { ok: true, data };
  }, [config, headers]);

  const reloadGraph = useCallback(async (): Promise<GraphJson | null> => {
    if (!config) return null;
    const resp = await fetch(config.endpoints.graph, {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.graph as GraphJson;
  }, [config]);

  return { saveDraft, validate, publish, reloadGraph };
}

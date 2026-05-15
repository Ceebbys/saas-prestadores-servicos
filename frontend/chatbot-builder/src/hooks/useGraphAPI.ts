/**
 * Hook que expõe operações sobre o graph: save, validate, publish, init.
 *
 * Auth = cookie de sessão (same-origin). CSRF via header X-CSRFToken
 * lido do data-csrf-token attribute (no main.tsx).
 */
import { useCallback } from "react";
import { useBuilderStore } from "../store/builderStore";
import type { GraphJson, OptionItem, ValidationResult } from "../types";

// Cache simples por key (in-memory) para reduzir chamadas — invalidado no reload do builder.
const _optionsCache: Record<string, { ts: number; options: OptionItem[] }> = {};
const _OPTIONS_TTL_MS = 30_000; // 30s — refresca em F5/reload da página

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

  /**
   * RV06 — Carrega options para selects dinâmicos do PropertiesPanel.
   *
   * Keys: services, pipeline_stages, proposal_templates, contract_templates, tags.
   * Cache in-memory de 30s para evitar refetch a cada render.
   */
  const fetchOptions = useCallback(async (key: string): Promise<OptionItem[]> => {
    if (!config) return [];
    const cached = _optionsCache[key];
    if (cached && Date.now() - cached.ts < _OPTIONS_TTL_MS) {
      return cached.options;
    }
    // Reusa o prefix da rota de graph para derivar /api/chatbot/options/<key>/
    // Endpoint exemplo: /api/chatbot/flows/N/graph/ → /api/chatbot/options/<key>/
    const optionsUrl = config.endpoints.graph
      .replace(/\/flows\/\d+\/graph\/?$/, `/options/${encodeURIComponent(key)}/`);
    try {
      const resp = await fetch(optionsUrl, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!resp.ok) {
        // eslint-disable-next-line no-console
        console.warn(`[builder] fetchOptions(${key}) HTTP ${resp.status}`);
        return [];
      }
      const data = (await resp.json()) as { options: OptionItem[] };
      _optionsCache[key] = { ts: Date.now(), options: data.options || [] };
      return data.options || [];
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn(`[builder] fetchOptions(${key}) failed`, err);
      return [];
    }
  }, [config]);

  return { saveDraft, validate, publish, reloadGraph, fetchOptions };
}

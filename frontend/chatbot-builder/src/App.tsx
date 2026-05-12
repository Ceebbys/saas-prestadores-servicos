/**
 * App principal do Chatbot Builder.
 *
 * Layout em 3 colunas: Sidebar (paleta) | Canvas (React Flow) | PropertiesPanel.
 * Topbar fixa com nome do flow + ações (Salvar, Validar, Publicar).
 */
import { useEffect, useState } from "react";
import { Topbar } from "./components/Topbar";
import { Sidebar } from "./components/Sidebar";
import { Canvas } from "./components/Canvas";
import { PropertiesPanel } from "./components/PropertiesPanel";
import { useBuilderStore } from "./store/builderStore";
import type { BuilderConfig, GraphJson, NodeCatalog } from "./types";

interface AppProps {
  config: BuilderConfig;
  initialGraph: unknown;
}

export function App({ config, initialGraph }: AppProps) {
  const setConfig = useBuilderStore((s) => s.setConfig);
  const setCatalog = useBuilderStore((s) => s.setCatalog);
  const setGraph = useBuilderStore((s) => s.setGraph);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  useEffect(() => {
    setConfig(config);
    if (initialGraph && typeof initialGraph === "object") {
      setGraph(initialGraph as GraphJson);
    }
  }, [config, initialGraph, setConfig, setGraph]);

  useEffect(() => {
    if (!config.endpoints.catalog) {
      setCatalogError("Endpoint do catálogo não configurado.");
      return;
    }
    fetch(config.endpoints.catalog, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((cat: NodeCatalog) => {
        setCatalog(cat);
        setCatalogLoaded(true);
      })
      .catch((err) => {
        setCatalogError(String(err));
      });
  }, [config.endpoints.catalog, setCatalog]);

  if (catalogError) {
    return (
      <div className="builder-error">
        <strong>Erro ao carregar catálogo:</strong>
        <p>{catalogError}</p>
      </div>
    );
  }
  if (!catalogLoaded) {
    return (
      <div className="builder-loading">
        <div className="spinner" />
        <p>Carregando catálogo de blocos…</p>
      </div>
    );
  }

  return (
    <div className="builder-shell">
      <Topbar />
      <div className="builder-body">
        <Sidebar />
        <Canvas />
        <PropertiesPanel />
      </div>
    </div>
  );
}

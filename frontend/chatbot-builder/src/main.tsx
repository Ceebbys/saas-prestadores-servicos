/**
 * RV06 — Entry point do Chatbot Builder (React Flow island).
 *
 * Lê dataset do <div id="chatbot-builder-root"> (endpoints, CSRF, flow id)
 * e monta o App React. Inicial graph vem embebido em <script type="application/json"
 * id="chatbot-initial-graph"> para evitar segundo round-trip.
 */
import React from "react";
import ReactDOM from "react-dom/client";
import "@xyflow/react/dist/style.css";
import "./styles/builder.css";
import { App } from "./App";
import type { BuilderConfig } from "./types";

function readConfig(root: HTMLElement): BuilderConfig {
  const ds = root.dataset;
  return {
    flowId: Number(ds.flowId ?? "0"),
    flowName: ds.flowName ?? "Fluxo",
    csrfToken: ds.csrfToken ?? "",
    endpoints: {
      graph: ds.graphEndpoint ?? "",
      save: ds.saveEndpoint ?? "",
      validate: ds.validateEndpoint ?? "",
      publish: ds.publishEndpoint ?? "",
      init: ds.initEndpoint ?? "",
      catalog: ds.catalogEndpoint ?? "",
      simulatorStart: ds.simulatorStartEndpoint ?? "",
      simulatorStep: ds.simulatorStepEndpoint ?? "",
      flowTemplates: ds.flowTemplatesEndpoint ?? "",
      applyTemplate: ds.applyTemplateEndpoint ?? "",
    },
    flowListUrl: ds.flowListUrl ?? "/",
    flowEditUrl: ds.flowEditUrl ?? "",
    hasPublished: ds.hasPublished === "true",
    useVisualBuilder: ds.useVisualBuilder === "true",
  };
}

function readInitialGraph(): unknown {
  const el = document.getElementById("chatbot-initial-graph");
  if (!el || !el.textContent) return null;
  try {
    return JSON.parse(el.textContent);
  } catch {
    return null;
  }
}

const rootEl = document.getElementById("chatbot-builder-root");
if (!rootEl) {
  // Em dev, index.html já provê o root. Em prod, template Django provê.
  console.warn("[chatbot-builder] Root element não encontrado.");
} else {
  const config = readConfig(rootEl);
  const initialGraph = readInitialGraph();
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      <App config={config} initialGraph={initialGraph} />
    </React.StrictMode>,
  );
}

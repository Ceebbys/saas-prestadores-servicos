/**
 * Store zustand do builder.
 *
 * Mantém: configuração, catálogo de blocos, graph atual (nodes/edges),
 * seleção, erros de validação, estado de salvamento.
 *
 * O React Flow tem sua própria state interna (useNodesState/useEdgesState);
 * sincronizamos via onNodesChange/onEdgesChange neste store.
 */
import { create } from "zustand";
import type {
  BuilderConfig,
  GraphEdge,
  GraphJson,
  GraphNode,
  NodeCatalog,
  NodeCatalogEntry,
  ValidationIssue,
} from "../types";

interface BuilderState {
  config: BuilderConfig | null;
  catalog: NodeCatalog | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  viewport: { x: number; y: number; zoom: number };
  selectedNodeId: string | null;
  validationErrors: ValidationIssue[];
  validationWarnings: ValidationIssue[];
  saveState: "idle" | "saving" | "saved" | "error";
  lastSavedAt: string | null;
  isDirty: boolean;
  // V2B — Simulador inline
  simulatorOpen: boolean;
  setSimulatorOpen: (open: boolean) => void;
  // V2C — Browser de templates
  templateBrowserOpen: boolean;
  setTemplateBrowserOpen: (open: boolean) => void;

  // Setters
  setConfig: (c: BuilderConfig) => void;
  setCatalog: (c: NodeCatalog) => void;
  setGraph: (g: GraphJson) => void;
  setNodes: (nodes: GraphNode[]) => void;
  setEdges: (edges: GraphEdge[]) => void;
  setViewport: (v: { x: number; y: number; zoom: number }) => void;
  setSelectedNodeId: (id: string | null) => void;
  setValidation: (errors: ValidationIssue[], warnings: ValidationIssue[]) => void;
  setSaveState: (s: "idle" | "saving" | "saved" | "error", savedAt?: string) => void;
  markDirty: () => void;
  markClean: () => void;

  // Helpers
  getCatalogEntry: (type: string) => NodeCatalogEntry | undefined;
  updateNodeData: (nodeId: string, dataPatch: Record<string, unknown>) => void;
  deleteNode: (nodeId: string) => void;
  addNode: (type: string, position: { x: number; y: number }) => GraphNode | null;
  toGraphJson: () => GraphJson;
}

let _nodeCounter = 0;

export const useBuilderStore = create<BuilderState>((set, get) => ({
  config: null,
  catalog: null,
  nodes: [],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  selectedNodeId: null,
  validationErrors: [],
  validationWarnings: [],
  saveState: "idle",
  lastSavedAt: null,
  isDirty: false,
  simulatorOpen: false,
  setSimulatorOpen: (simulatorOpen) => set({ simulatorOpen }),
  templateBrowserOpen: false,
  setTemplateBrowserOpen: (templateBrowserOpen) => set({ templateBrowserOpen }),

  setConfig: (config) => set({ config }),
  setCatalog: (catalog) => set({ catalog }),
  setGraph: (graph) => {
    set({
      nodes: graph.nodes ?? [],
      edges: graph.edges ?? [],
      viewport: graph.viewport ?? { x: 0, y: 0, zoom: 1 },
      isDirty: false,
    });
  },
  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),
  setViewport: (viewport) => set({ viewport }),
  setSelectedNodeId: (selectedNodeId) => set({ selectedNodeId }),
  setValidation: (validationErrors, validationWarnings) =>
    set({ validationErrors, validationWarnings }),
  setSaveState: (saveState, savedAt) =>
    set({
      saveState,
      lastSavedAt: savedAt ?? get().lastSavedAt,
    }),
  markDirty: () => set({ isDirty: true, saveState: "idle" }),
  markClean: () => set({ isDirty: false }),

  getCatalogEntry: (type) => {
    const cat = get().catalog;
    if (!cat) return undefined;
    return cat.nodes.find((n) => n.type === type);
  },

  updateNodeData: (nodeId, dataPatch) => {
    set((state) => {
      const newNodes = state.nodes.map((n) =>
        n.id === nodeId ? { ...n, data: { ...n.data, ...dataPatch } } : n,
      );
      // RV06 Item 3 — Sanitiza edges órfãs quando options de menu mudam.
      // Quando user reordena/deleta opções, handle_ids antigos ficam órfãos
      // (edges apontando para handle_id que não existe mais no node).
      let newEdges = state.edges;
      const updatedNode = newNodes.find((n) => n.id === nodeId);
      if (
        updatedNode &&
        updatedNode.type === "menu" &&
        "options" in dataPatch
      ) {
        const validHandleIds = new Set<string>(
          ((updatedNode.data.options as any[]) || [])
            .map((o) => o?.handle_id)
            .filter(Boolean),
        );
        const before = state.edges.length;
        newEdges = state.edges.filter((e) => {
          // Mantém edges cujo source != este menu (não afetadas)
          if (e.source !== nodeId) return true;
          // Edges deste menu precisam ter sourceHandle válido
          const h = e.sourceHandle || "";
          return validHandleIds.has(h);
        });
        if (newEdges.length < before) {
          // eslint-disable-next-line no-console
          console.warn(
            `[builder] cleanOrphanEdges: removidas ${before - newEdges.length} ` +
            `edge(s) órfã(s) do menu ${nodeId} (handle_ids inválidos).`,
          );
        }
      }
      return {
        nodes: newNodes,
        edges: newEdges,
        isDirty: true,
        saveState: "idle",
      };
    });
  },

  deleteNode: (nodeId) => {
    set((state) => ({
      nodes: state.nodes.filter((n) => n.id !== nodeId),
      edges: state.edges.filter((e) => e.source !== nodeId && e.target !== nodeId),
      selectedNodeId: state.selectedNodeId === nodeId ? null : state.selectedNodeId,
      isDirty: true,
      saveState: "idle",
    }));
  },

  addNode: (type, position) => {
    const entry = get().getCatalogEntry(type);
    if (!entry) return null;
    if (entry.status === "coming_soon") return null;
    if (entry.max_per_graph !== undefined) {
      const count = get().nodes.filter((n) => n.type === type).length;
      if (count >= entry.max_per_graph) {
        return null;
      }
    }
    _nodeCounter += 1;
    const id = `n_${type}_${Date.now()}_${_nodeCounter}`;
    const defaultData: Record<string, unknown> = {};
    for (const f of entry.data_fields) {
      if (f.default !== undefined) defaultData[f.name] = f.default;
    }
    const newNode: GraphNode = {
      id,
      type: type as any,
      position,
      data: { label: entry.label, ...defaultData },
    };
    set((state) => ({
      nodes: [...state.nodes, newNode],
      isDirty: true,
      saveState: "idle",
    }));
    return newNode;
  },

  toGraphJson: () => {
    const state = get();
    return {
      schema_version: 1,
      viewport: state.viewport,
      metadata: {
        exported_at: new Date().toISOString(),
      },
      nodes: state.nodes,
      edges: state.edges,
    };
  },
}));

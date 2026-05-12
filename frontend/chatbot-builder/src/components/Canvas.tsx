/**
 * Canvas central — React Flow wrapper.
 *
 * Recebe nodes/edges do store, sincroniza mudanças (move/connect/delete)
 * de volta, registra tipos customizados de nó.
 */
import { useCallback, useMemo, useRef } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type EdgeChange,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  useReactFlow,
} from "@xyflow/react";
import { useBuilderStore } from "../store/builderStore";
import { useAutosave } from "../hooks/useAutosave";
import { GenericNode } from "./nodes/GenericNode";
import { MenuNode } from "./nodes/MenuNode";
import { ConditionNode } from "./nodes/ConditionNode";
import type { GraphEdge, GraphNode } from "../types";

// Tipos customizados de node registrados no React Flow
const nodeTypes = {
  start: GenericNode,
  message: GenericNode,
  question: GenericNode,
  menu: MenuNode,
  condition: ConditionNode,
  collect_data: GenericNode,
  api_call: GenericNode,
  handoff: GenericNode,
  end: GenericNode,
};

function CanvasInner() {
  const nodes = useBuilderStore((s) => s.nodes);
  const edges = useBuilderStore((s) => s.edges);
  const setNodes = useBuilderStore((s) => s.setNodes);
  const setEdges = useBuilderStore((s) => s.setEdges);
  const setSelectedNodeId = useBuilderStore((s) => s.setSelectedNodeId);
  const setViewport = useBuilderStore((s) => s.setViewport);
  const markDirty = useBuilderStore((s) => s.markDirty);
  const addNode = useBuilderStore((s) => s.addNode);
  const validationErrors = useBuilderStore((s) => s.validationErrors);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition } = useReactFlow();

  useAutosave();

  // Nodes com classe de erro injetada
  const errorNodeIds = useMemo(
    () => new Set(validationErrors.filter((e) => e.node_id).map((e) => e.node_id as string)),
    [validationErrors],
  );

  const rfNodes: Node[] = useMemo(
    () =>
      nodes.map((n) => ({
        ...(n as unknown as Node),
        className: errorNodeIds.has(n.id) ? "rf-node-error" : "",
      })),
    [nodes, errorNodeIds],
  );

  const rfEdges: Edge[] = useMemo(() => edges as unknown as Edge[], [edges]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const updated = applyNodeChanges(changes, rfNodes) as unknown as GraphNode[];
      setNodes(updated);
      // Detecta mudanças não-cosméticas para marcar dirty
      const dirty = changes.some(
        (c) => c.type === "position" || c.type === "remove" || c.type === "add",
      );
      if (dirty) markDirty();
    },
    [rfNodes, setNodes, markDirty],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const updated = applyEdgeChanges(changes, rfEdges) as unknown as GraphEdge[];
      setEdges(updated);
      const dirty = changes.some((c) => c.type === "remove" || c.type === "add");
      if (dirty) markDirty();
    },
    [rfEdges, setEdges, markDirty],
  );

  const onConnect = useCallback(
    (params: Connection) => {
      const newEdges = addEdge(
        { ...params, type: "default" },
        rfEdges,
      ) as unknown as GraphEdge[];
      setEdges(newEdges);
      markDirty();
    },
    [rfEdges, setEdges, markDirty],
  );

  const onSelectionChange = useCallback(
    ({ nodes: selected }: { nodes: Node[] }) => {
      setSelectedNodeId(selected.length > 0 ? selected[0].id : null);
    },
    [setSelectedNodeId],
  );

  const onMove = useCallback(
    (_event: any, viewport: { x: number; y: number; zoom: number }) => {
      setViewport(viewport);
    },
    [setViewport],
  );

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/x-chatbot-builder-node");
      if (!type) return;
      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const node = addNode(type, position);
      if (!node) {
        // ex.: tentou adicionar segundo 'start' (max_per_graph=1)
        console.warn("[Canvas] Não foi possível adicionar node tipo", type);
      }
    },
    [addNode, screenToFlowPosition],
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  return (
    <div className="canvas" ref={wrapperRef} onDrop={onDrop} onDragOver={onDragOver}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onSelectionChange={onSelectionChange}
        onMove={onMove}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        deleteKeyCode={["Delete", "Backspace"]}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#cbd5e1" />
        <Controls />
        <MiniMap pannable zoomable nodeColor={(n) => (n.data as any)?.color ?? "#94a3b8"} />
      </ReactFlow>
    </div>
  );
}

export function Canvas() {
  return (
    <ReactFlowProvider>
      <CanvasInner />
    </ReactFlowProvider>
  );
}

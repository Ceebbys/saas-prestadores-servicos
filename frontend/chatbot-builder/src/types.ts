/**
 * Tipos compartilhados do Chatbot Builder.
 *
 * `GraphJson`, `NodeData`, `EdgeData` espelham o JSON Schema em
 * `apps/chatbot/builder/schemas/graph_v1.json`. Mantenha sincronizado.
 */

export type NodeType =
  | "start"
  | "message"
  | "question"
  | "menu"
  | "condition"
  | "collect_data"
  | "api_call"
  | "handoff"
  | "end";

export interface MenuOption {
  label: string;
  value?: string;
  handle_id: string;
}

export interface NodeData {
  label?: string;
  text?: string;
  prompt?: string;
  lead_field?: string;
  validator?: string;
  validator_strict?: boolean;
  options?: MenuOption[];
  field?: string;
  operator?: string;
  value?: string;
  delay_ms?: number;
  welcome_message?: string;
  completion_message?: string;
  message_to_user?: string;
  queue?: string;
  internal_note?: string;
  secret_ref?: string;
  method?: string;
  path_template?: string;
  payload_template?: string;
  response_var?: string;
  [key: string]: unknown;
}

export interface GraphNode {
  id: string;
  type: NodeType;
  position: { x: number; y: number };
  data: NodeData;
  width?: number;
  height?: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  label?: string | null;
}

export interface GraphJson {
  schema_version: number;
  viewport?: { x: number; y: number; zoom: number };
  metadata?: Record<string, unknown>;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ValidationIssue {
  node_id: string | null;
  field: string | null;
  message: string;
  code: string;
  severity: "error" | "warning";
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface BuilderConfig {
  flowId: number;
  flowName: string;
  csrfToken: string;
  endpoints: {
    graph: string;
    save: string;
    validate: string;
    publish: string;
    init: string;
    catalog: string;
  };
  flowListUrl: string;
  flowEditUrl: string;
  hasPublished: boolean;
  useVisualBuilder: boolean;
}

// Catálogo de tipos de bloco (mirror de node_catalog.json)
export interface NodeCatalogField {
  name: string;
  type: "string" | "text" | "integer" | "boolean" | "enum" | "array";
  required?: boolean;
  default?: unknown;
  max_length?: number;
  max?: number;
  min?: number;
  min_items?: number;
  max_items?: number;
  options?: string[];
  help?: string;
  label?: string;
  item_schema?: Record<string, unknown>;
}

export interface NodeCatalogEntry {
  type: NodeType;
  label: string;
  description: string;
  category: string;
  icon: string;
  color: string;
  status: "active" | "coming_soon";
  handles: {
    in?: boolean;
    out?: string[];
    out_dynamic?: string;
  };
  max_per_graph?: number;
  min_per_graph?: number;
  data_fields: NodeCatalogField[];
}

export interface NodeCatalog {
  schema_version: number;
  categories: { slug: string; label: string }[];
  nodes: NodeCatalogEntry[];
}

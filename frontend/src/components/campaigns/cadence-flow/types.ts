import type { CampaignNode, CampaignNodeType } from "@/lib/types";

// ─── Palette ───────────────────────────────────────────────────────────────────
export type PaletteItem = { type: CampaignNodeType; subtype: string; icon: string; label: string; desc: string };

// ─── API data types for Inspector dropdowns ────────────────────────────────────
export interface FlowTemplate {
  id: string;
  name: string;
  status: string;
  language: string;
  body?: string;
  params?: { index: number; paramName: string; example: string }[];
  paramsType?: "positional" | "named" | "none";
}
export interface FlowStage    { id: string; label: string; pipeline_name: string; key: string | null }
export interface FlowTag      { id: string; name: string }
export interface FlowUser     { id: string; name: string; email: string }

export interface FlowBuilderData {
  templates: FlowTemplate[];
  allStages: FlowStage[];
  tags: FlowTag[];
  users: FlowUser[];
  channels: { id: string; name: string; is_active: boolean; provider: string }[];
}

// ─── Test mode types ───────────────────────────────────────────────────────────
export type TestNodeState = "running" | "done" | "failed";

export interface TestEvent {
  node_id: string | null;
  status: "running" | "done" | "failed" | "finished";
  log?: string;
  duration_ms?: number;
}

export interface TestLogEntry extends TestEvent {
  node_label: string;
}

// ─── Inspector ─────────────────────────────────────────────────────────────────
export interface InspectorProps {
  node: CampaignNode;
  saving: boolean;
  data: FlowBuilderData;
  onSave: (nodeId: string, config: Record<string, unknown>) => Promise<void>;
  onDelete: (nodeId: string) => Promise<void>;
  onClose: () => void;
}

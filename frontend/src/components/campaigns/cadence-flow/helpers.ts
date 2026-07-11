import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { CampaignNode, CampaignNodeType } from "@/lib/types";
import { NODE_META, TRIGGER_LABELS, ACTION_LABELS, TRIGGER_ICONS, ACTION_ICONS } from "./constants";

// ─── Helpers ──────────────────────────────────────────────────────────────────
export function getDefaultConfig(type: CampaignNodeType, subtype = ""): Record<string, unknown> {
  switch (type) {
    case "trigger":
      if (subtype === "keyword_received") return { trigger_type: "keyword_received", keywords: [] };
      return { trigger_type: subtype || "no_message", days: 30 };
    case "send":      return { template_name: "", template_language: "pt_BR", template_variables: {}, on_reply: "pause" };
    case "send_text": return { message_text: "", on_reply: "pause" };
    case "wait":      return { days: 3, hours: 0, send_start_hour: 7, send_end_hour: 18 };
    case "condition": return { condition_type: subtype || "replied_recently", days: 5 };
    case "action": {
      const at = subtype || "move_stage";
      const base: Record<string, unknown> = { action_type: at };
      if (at === "move_stage") base.stage = "";
      if (at === "mark_deal_won" || at === "mark_deal_lost" || at === "move_deal_stage") base.stage_id = "";
      if (at === "add_tag" || at === "remove_tag") base.tag_name = "";
      if (at === "add_note") base.note_template = "";
      if (at === "create_deal") base.title_template = "";
      if (at === "assign_to") base.user_id = "";
      if (at === "assign_round_robin") base.user_ids = [];
      return base;
    }
    case "end":       return { label: "Concluído", final_actions: [] };
    default:          return {};
  }
}

export function resolveNodeIcon(type: CampaignNodeType, config: Record<string, unknown>): string {
  if (type === "trigger") return TRIGGER_ICONS[(config.trigger_type as string) ?? ""] ?? NODE_META.trigger.icon;
  if (type === "action")  return ACTION_ICONS[(config.action_type as string) ?? ""]   ?? NODE_META.action.icon;
  return NODE_META[type]?.icon ?? "⚡";
}

export function nodeDetail(type: CampaignNodeType, config: Record<string, unknown>): string {
  switch (type) {
    case "trigger":   return TRIGGER_LABELS[config.trigger_type as string] ?? (config.trigger_type as string) ?? "";
    case "send":      return (config.template_name as string) || "template não definido";
    case "send_text": return (config.message_text as string)?.slice(0, 40) || "texto não definido";
    case "wait": {
      const d = Number(config.days ?? 1);
      const h = Number(config.hours ?? 0);
      if (d && h) return `${d} dia(s) + ${h}h`;
      if (!d && h) return `${h} hora(s)`;
      return `${d} dia(s)`;
    }
    case "condition": return (config.condition_type as string) ?? "";
    case "action":    return ACTION_LABELS[config.action_type as string] ?? (config.action_type as string) ?? "";
    case "end":       return (config.label as string) || "Encerrar";
    default:          return "";
  }
}

// Convert DB node → React Flow node
export function toRFNode(node: CampaignNode): Node {
  return {
    id: node.id,
    type: "campaignNode",
    position: { x: node.position_x, y: node.position_y },
    data: { ...node } as Record<string, unknown>,
    draggable: true,
    selectable: true,
  };
}

// Convert DB nodes → React Flow edges
export function toRFEdges(nodes: CampaignNode[]): Edge[] {
  const edges: Edge[] = [];
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  for (const n of nodes) {
    if (n.next_node_id && byId[n.next_node_id]) {
      edges.push({
        id: `${n.id}→${n.next_node_id}`,
        source: n.id, sourceHandle: "out",
        target: n.next_node_id, targetHandle: "in",
        style: { stroke: "#c8c2bb", strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#c8c2bb", width: 14, height: 14 },
        type: "deletable",
      });
    }
    if (n.yes_node_id && byId[n.yes_node_id]) {
      edges.push({
        id: `${n.id}→yes→${n.yes_node_id}`,
        source: n.id, sourceHandle: "yes",
        target: n.yes_node_id, targetHandle: "in",
        style: { stroke: "#1A9B6C", strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#1A9B6C", width: 14, height: 14 },
        label: "SIM", labelStyle: { fill: "#1A9B6C", fontSize: 9, fontWeight: 700 },
        type: "deletable",
      });
    }
    if (n.no_node_id && byId[n.no_node_id]) {
      edges.push({
        id: `${n.id}→no→${n.no_node_id}`,
        source: n.id, sourceHandle: "no",
        target: n.no_node_id, targetHandle: "in",
        style: { stroke: "#ef4444", strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#ef4444", width: 14, height: 14 },
        label: "NÃO", labelStyle: { fill: "#ef4444", fontSize: 9, fontWeight: 700 },
        type: "deletable",
      });
    }
  }
  return edges;
}

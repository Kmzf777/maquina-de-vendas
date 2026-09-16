import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { CampaignNode, CampaignNodeType } from "@/lib/types";
import {
  NODE_META, TRIGGER_LABELS, ACTION_LABELS, CONDITION_LABELS,
  TRIGGER_ICONS, ACTION_ICONS, CONDITION_ICONS,
} from "./constants";
import { getCachedNodeSchema, schemaDefaults, type NodeSchema } from "@/lib/node-schema";

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** A chave de config que guarda o subtipo, e o subtipo que a paleta assume quando
 *  o chamador não escolhe um. Não é campo do registro: é como a TELA sabe qual
 *  variante do tipo está editando. */
const DISCRIMINADOR: Partial<Record<CampaignNodeType, { chave: string; padrao: string }>> = {
  trigger:   { chave: "trigger_type",   padrao: "no_message" },
  condition: { chave: "condition_type", padrao: "replied_recently" },
  action:    { chave: "action_type",    padrao: "move_stage" },
};

/**
 * O config com que um nó NOVO nasce — derivado do contrato, não de uma tabela
 * paralela mantida à mão.
 *
 * A tabela paralela (um `switch` com 20 linhas de `if`) divergia do motor em dois
 * pontos que custavam caro e não davam erro nenhum:
 *   • `send`/`send_text` nasciam com `on_reply: "pause"`. Como `_apply_reply_policy`
 *     dá precedência ao NÓ sobre o GATILHO, toda campanha montada na tela sequestrava
 *     em silêncio um gatilho `on_reply='reset'`.
 *   • `wait` nascia com a janela de envio explícita, e `_wait_target` faz
 *     `cfg.get("send_start_hour", camp.get(...))` — o nó vencia a campanha sempre.
 * Nos dois casos o registro declara `default=None`: ausente TEM sentido próprio.
 *
 * Sem o contrato carregado o nó nasce só com o discriminador. É de propósito: config
 * vazia é visível e corrigível no inspector; config errada é invisível até a campanha
 * rodar em silêncio.
 */
export function getDefaultConfig(
  type: CampaignNodeType,
  subtype = "",
  schema: NodeSchema | null = getCachedNodeSchema(),
): Record<string, unknown> {
  const disc = DISCRIMINADOR[type];
  const sub = subtype || disc?.padrao || "";

  const config: Record<string, unknown> = {};
  if (disc) config[disc.chave] = sub;
  // `final_actions` não existe no registro porque o motor não faz `cfg.get` nele: é a
  // lista de configs de ação que a própria tela monta dentro do nó de encerramento.
  if (type === "end") config.final_actions = [];

  return { ...config, ...schemaDefaults(schema, type, sub || null) };
}

export function resolveNodeIcon(type: CampaignNodeType, config: Record<string, unknown>): string {
  if (type === "trigger")   return TRIGGER_ICONS[(config.trigger_type as string) ?? ""]     ?? NODE_META.trigger.icon;
  if (type === "action")    return ACTION_ICONS[(config.action_type as string) ?? ""]       ?? NODE_META.action.icon;
  if (type === "condition") return CONDITION_ICONS[(config.condition_type as string) ?? ""] ?? NODE_META.condition.icon;
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
    case "condition": return CONDITION_LABELS[config.condition_type as string] ?? (config.condition_type as string) ?? "";
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

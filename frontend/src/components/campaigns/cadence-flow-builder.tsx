"use client";

import { useState, useEffect, useCallback, useRef, DragEvent, memo } from "react";
import { useRouter } from "next/navigation";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Edge,
  Node,
  Handle,
  Position,
  BackgroundVariant,
  NodeProps,
  useReactFlow,
  ReactFlowProvider,
  OnConnect,
  Panel,
  MarkerType,
  OnNodeDrag,
  PanOnScrollMode,
  ConnectionLineType,
  EdgeProps,
  BaseEdge,
  getSmoothStepPath,
  EdgeLabelRenderer,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion, AnimatePresence } from "framer-motion";
import type { Campaign, CampaignNode, CampaignNodeType } from "@/lib/types";

// ─── Fonts ────────────────────────────────────────────────────────────────────
const FONT_STYLE = `@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
.react-flow__handle { transition: transform .15s, box-shadow .15s; }
.react-flow__handle:hover { transform: scale(1.5) !important; }
.react-flow__node { cursor: grab; }
.react-flow__node:active { cursor: grabbing; }
.react-flow__node.selected > div { box-shadow: 0 0 0 2px #fff, 0 0 0 4px #E85D26, 0 8px 28px rgba(0,0,0,.14) !important; border-color: transparent !important; }
.react-flow__edge-path { transition: stroke .15s; }
.react-flow__controls { box-shadow: 0 2px 8px rgba(0,0,0,.1); border-radius: 8px; border: 1px solid #e8e4df; overflow: hidden; }
.react-flow__controls-button { background: #fff; border-bottom: 1px solid #e8e4df; color: #555; }
.react-flow__controls-button:hover { background: #f5f2ed; }
@keyframes cfb-pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
`;

// ─── Design constants ──────────────────────────────────────────────────────────
const NODE_W = 220;

const NODE_META: Record<CampaignNodeType, { label: string; kicker: string; icon: string; color: string; iconBg: string }> = {
  trigger:   { label: "Gatilho",         kicker: "GATILHO",  icon: "⚡", color: "#1a1a1a", iconBg: "rgba(26,26,26,.07)" },
  send:      { label: "Enviar template", kicker: "ENVIAR",   icon: "📨", color: "#E85D26", iconBg: "rgba(232,93,38,.1)" },
  send_text: { label: "Enviar texto",    kicker: "TEXTO LIVRE", icon: "💬", color: "#0F766E", iconBg: "rgba(15,118,110,.1)" },
  wait:      { label: "Aguardar",        kicker: "ESPERA",   icon: "⏱", color: "#3B7DD8", iconBg: "rgba(59,125,216,.1)" },
  condition: { label: "Condição",        kicker: "CONDIÇÃO", icon: "🔀", color: "#C4920C", iconBg: "rgba(196,146,12,.1)" },
  action:    { label: "Ação",            kicker: "AÇÃO",     icon: "📋", color: "#7C4DB8", iconBg: "rgba(124,77,184,.1)" },
  end:       { label: "Encerrar",        kicker: "FIM",      icon: "🏁", color: "#1A9B6C", iconBg: "rgba(26,155,108,.1)" },
};

const STATUS_LABELS: Record<string, string> = {
  draft: "Rascunho", active: "Ativa", paused: "Pausada", archived: "Arquivada",
};
const STATUS_COLORS: Record<string, { bg: string; color: string; border: string }> = {
  draft:    { bg: "#f5f2ed", color: "#888",    border: "#e0dbd4" },
  active:   { bg: "#edfaf5", color: "#1A9B6C", border: "#a7f0d4" },
  paused:   { bg: "#fff7ed", color: "#C4920C", border: "#fde68a" },
  archived: { bg: "#f5f2ed", color: "#888",    border: "#e0dbd4" },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
function getDefaultConfig(type: CampaignNodeType, subtype = ""): Record<string, unknown> {
  switch (type) {
    case "trigger":
      if (subtype === "keyword_received") return { trigger_type: "keyword_received", keywords: [] };
      return { trigger_type: subtype || "no_message", days: 30 };
    case "send":      return { template_name: "", template_language: "pt_BR", template_variables: {}, on_reply: "pause" };
    case "send_text": return { message_text: "", on_reply: "pause" };
    case "wait":      return { days: 3, send_start_hour: 7, send_end_hour: 18 };
    case "condition": return { condition_type: subtype || "replied_recently", days: 5 };
    case "action":    return { action_type: subtype || "move_stage", stage_id: "" };
    case "end":       return { label: "Concluído", final_actions: [] };
    default:          return {};
  }
}

const TRIGGER_LABELS: Record<string, string> = {
  no_message: "Sem mensagem", stage_stagnation: "Estagnação", stage_enter: "Entrada em stage", post_broadcast: "Pós-disparo",
  sale_created: "Venda criada", repurchase_window: "Janela de recompra", no_sale_in_stage: "Sem venda no stage",
  tag_added: "Tag adicionada", deal_stage_enter: "Entrou em stage (deal)", deal_closed_lost: "Deal perdido",
  keyword_received: "Palavra-chave recebida",
};
const ACTION_LABELS: Record<string, string> = {
  move_stage: "Mover stage do lead",
  activate_agent: "Ativar agente",
  deactivate_agent: "Desativar agente",
  add_tag: "Adicionar tag",
  remove_tag: "Remover tag",
  mark_deal_won: "Marcar deal como ganho",
  mark_deal_lost: "Marcar deal como perdido",
  move_deal_stage: "Mover deal de estágio",
  add_note: "Adicionar nota",
  assign_round_robin: "Atribuir (round-robin)",
  create_deal: "Criar deal",
  assign_to: "Atribuir a vendedor",
};

// Ícones por subtype — os nós no canvas mostram o ícone do subtipo, não o genérico
const TRIGGER_ICONS: Record<string, string> = {
  stage_enter: "⚡", stage_stagnation: "🕐", no_message: "💤", post_broadcast: "📡",
  sale_created: "💰", repurchase_window: "🔄", no_sale_in_stage: "📉",
  tag_added: "🏷️", deal_stage_enter: "🤝", deal_closed_lost: "❌",
  keyword_received: "🔍",
};
const ACTION_ICONS: Record<string, string> = {
  move_stage: "📋",
  activate_agent: "🤖",
  deactivate_agent: "🤖",
  add_tag: "🏷️",
  remove_tag: "🏷️",
  mark_deal_won: "🏆",
  mark_deal_lost: "💔",
  move_deal_stage: "🔀",
  add_note: "📝",
  assign_round_robin: "🎯",
  create_deal: "💼",
  assign_to: "👤",
};

function resolveNodeIcon(type: CampaignNodeType, config: Record<string, unknown>): string {
  if (type === "trigger") return TRIGGER_ICONS[(config.trigger_type as string) ?? ""] ?? NODE_META.trigger.icon;
  if (type === "action")  return ACTION_ICONS[(config.action_type as string) ?? ""]   ?? NODE_META.action.icon;
  return NODE_META[type]?.icon ?? "⚡";
}

function nodeDetail(type: CampaignNodeType, config: Record<string, unknown>): string {
  switch (type) {
    case "trigger":   return TRIGGER_LABELS[config.trigger_type as string] ?? (config.trigger_type as string) ?? "";
    case "send":      return (config.template_name as string) || "template não definido";
    case "send_text": return (config.message_text as string)?.slice(0, 40) || "texto não definido";
    case "wait":      return `${config.days ?? 1} dia(s)`;
    case "condition": return (config.condition_type as string) ?? "";
    case "action":    return ACTION_LABELS[config.action_type as string] ?? (config.action_type as string) ?? "";
    case "end":       return (config.label as string) || "Encerrar";
    default:          return "";
  }
}

// Convert DB node → React Flow node
function toRFNode(node: CampaignNode): Node {
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
function toRFEdges(nodes: CampaignNode[]): Edge[] {
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

// ─── DeletableEdge — custom edge with hover delete button ───────────────────
function DeletableEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition,
  style, markerEnd, label,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
  });
  const labelColor = String(label) === "SIM" ? "#1A9B6C" : String(label) === "NÃO" ? "#ef4444" : "#555";
  const [hovered, setHovered] = useState(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showBtn = () => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    setHovered(true);
  };
  const hideBtn = () => {
    hideTimer.current = setTimeout(() => setHovered(false), 120);
  };

  return (
    <g onMouseEnter={showBtn} onMouseLeave={hideBtn}>
      <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />
      <EdgeLabelRenderer>
        {label && (
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "none",
              fontSize: 9, fontWeight: 700,
              color: labelColor,
            }}
            className="nodrag nopan"
          >
            {String(label)}
          </div>
        )}
        <div
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY + (label ? 14 : 0)}px)`,
            pointerEvents: hovered ? "all" : "none",
            opacity: hovered ? 1 : 0,
            transition: "opacity .15s",
          }}
          className="nodrag nopan"
          onMouseEnter={showBtn}
          onMouseLeave={hideBtn}
        >
          <button
            onClick={(e) => { e.stopPropagation(); _deleteEdge?.(id); }}
            title="Deletar conexão"
            style={{
              width: 22, height: 22, borderRadius: "50%",
              background: "#fff",
              border: "1.5px solid #fca5a5",
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", fontSize: 11, color: "#ef4444",
              boxShadow: "0 1px 4px rgba(0,0,0,.15)",
              padding: 0, lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>
      </EdgeLabelRenderer>
    </g>
  );
}

const EDGE_TYPES = { deletable: DeletableEdge };

// ─── QuickAddButton — appears on hover below each non-end node ────────────────
function QuickAddButton({ nodeId }: { nodeId: string }) {
  const [open, setOpen] = useState(false);

  const handleAdd = (e: React.MouseEvent<HTMLButtonElement>, type: CampaignNodeType, subtype: string) => {
    e.stopPropagation();
    _addNodeBelow?.(nodeId, type, subtype);
    setOpen(false);
  };

  return (
    <div
      style={{
        position: "absolute",
        left: "100%",
        top: "50%",
        transform: "translateY(-50%)",
        paddingLeft: 8,
        zIndex: 20,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
      }}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
        style={{
          width: 26, height: 26, borderRadius: "50%",
          background: "#fff",
          border: "1.5px solid #c8c2bb",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer", fontSize: 16, color: "#888",
          boxShadow: "0 1px 4px rgba(0,0,0,.12)",
          lineHeight: 1, padding: 0,
          transition: "border-color .12s, color .12s, box-shadow .12s",
        }}
        onMouseEnter={e => {
          e.currentTarget.style.borderColor = "#E85D26";
          e.currentTarget.style.color = "#E85D26";
          e.currentTarget.style.boxShadow = "0 2px 8px rgba(232,93,38,.25)";
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = "#c8c2bb";
          e.currentTarget.style.color = "#888";
          e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,.12)";
        }}
      >
        +
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            key="quick-add-picker"
            initial={{ opacity: 0, y: -8, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.95 }}
            transition={{ duration: 0.13, ease: "easeOut" }}
            style={{
              position: "absolute",
              top: 34,
              left: 8,
              background: "#fff",
              border: "1px solid #e8e4df",
              borderRadius: 10,
              boxShadow: "0 8px 24px rgba(0,0,0,.12), 0 2px 6px rgba(0,0,0,.06)",
              padding: "5px 4px",
              minWidth: 152,
              zIndex: 30,
            }}
            onClick={e => e.stopPropagation()}
          >
            {QUICK_ADD_ITEMS.map(item => (
              <button
                key={`${item.type}-${item.subtype}`}
                onClick={e => handleAdd(e, item.type, item.subtype)}
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  width: "100%", padding: "7px 10px",
                  border: "none", background: "transparent",
                  cursor: "pointer", borderRadius: 7,
                  fontFamily: "'Outfit', sans-serif",
                  fontSize: 12, color: "#222", textAlign: "left",
                  transition: "background .1s",
                }}
                onMouseEnter={e => { e.currentTarget.style.background = "#f5f2ed"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
              >
                <span style={{ fontSize: 14 }}>{item.icon}</span>
                <span style={{ fontWeight: 500 }}>{item.label}</span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Custom Node component (registered at module level — MUST stay outside render) ──
const CampaignFlowNode = memo(function CampaignFlowNode({ data }: NodeProps) {
  const node = data as unknown as CampaignNode;
  const cfg = (node.config ?? {}) as Record<string, unknown>;
  const meta = NODE_META[node.type] ?? NODE_META.trigger;
  const isCondition = node.type === "condition";
  const isEnd = node.type === "end";
  const isTrigger = node.type === "trigger";
  const [showAdd, setShowAdd] = useState(false);
  const color = meta.color === "#1a1a1a" ? "#aaa" : meta.color;
  const displayIcon = resolveNodeIcon(node.type, cfg);
  const testState = ((data as Record<string, unknown>).testState as TestNodeState | null) ?? null;

  const handleStyle: React.CSSProperties = {
    width: 10, height: 10,
    background: "#fff",
    border: `2px solid ${color}`,
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.86 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      onClick={(e) => { e.stopPropagation(); _selectNode?.(node.id); }}
      onMouseEnter={() => setShowAdd(true)}
      onMouseLeave={() => setShowAdd(false)}
      style={{
        width: NODE_W,
        background: "#ffffff",
        borderRadius: 10,
        boxShadow: testState === "running"
          ? "0 0 0 2px #E85D26, 0 4px 14px rgba(232,93,38,.3)"
          : testState === "done"
          ? "0 0 0 2px #1A9B6C, 0 4px 14px rgba(26,155,108,.2)"
          : testState === "failed"
          ? "0 0 0 2px #ef4444, 0 4px 14px rgba(239,68,68,.2)"
          : "0 1px 3px rgba(0,0,0,.07), 0 4px 14px rgba(0,0,0,.08)",
        border: "1px solid rgba(0,0,0,.06)",
        fontFamily: "'Outfit', sans-serif",
        overflow: "visible",
        position: "relative",
        transition: "box-shadow .2s",
      }}
    >
      {/* Top stripe */}
      <div style={{ height: 3, background: meta.color, borderRadius: "10px 10px 0 0" }} />

      {/* Input handle (top) — not on trigger */}
      {!isTrigger && (
        <Handle
          type="target"
          position={Position.Top}
          id="in"
          style={{ ...handleStyle, top: -5, borderColor: color }}
        />
      )}

      {/* Body */}
      <div style={{ padding: "12px 14px 16px", display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div style={{
          width: 34, height: 34, borderRadius: 8,
          background: meta.iconBg,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 16, flexShrink: 0, marginTop: 1,
        }}>
          {displayIcon}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 9, fontWeight: 700, letterSpacing: ".8px",
            textTransform: "uppercase", marginBottom: 2,
            color: meta.color === "#1a1a1a" ? "#888" : meta.color,
          }}>
            {meta.kicker}
          </div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#111", letterSpacing: "-.2px", lineHeight: 1.3 }}>
            {meta.label}
          </div>
          <div style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10, color: "#9b9590", marginTop: 4,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            maxWidth: NODE_W - 80,
          }}>
            {nodeDetail(node.type, node.config as Record<string, unknown>)}
          </div>
        </div>
      </div>

      {/* Test state badge */}
      {testState && (
        <div style={{
          position: "absolute", top: -8, right: -8,
          width: 22, height: 22, borderRadius: "50%",
          background: testState === "running" ? "#E85D26" : testState === "done" ? "#1A9B6C" : "#ef4444",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 11, color: "#fff",
          boxShadow: "0 2px 6px rgba(0,0,0,.2)",
          animation: testState === "running" ? "cfb-pulse 1s infinite" : "none",
          zIndex: 10,
        }}>
          {testState === "running" ? "⟳" : testState === "done" ? "✓" : "✗"}
        </div>
      )}

      {/* Output handle(s) (bottom) — not on end */}
      {!isEnd && (
        isCondition ? (
          <>
            <Handle type="source" position={Position.Bottom} id="yes" style={{ ...handleStyle, left: "27%", borderColor: "#1A9B6C", bottom: -5 }} />
            <div style={{ position: "absolute", bottom: -22, left: "27%", transform: "translateX(-50%)", fontSize: 9, fontWeight: 700, color: "#1A9B6C", letterSpacing: ".4px", textTransform: "uppercase", pointerEvents: "none" }}>SIM</div>
            <Handle type="source" position={Position.Bottom} id="no" style={{ ...handleStyle, left: "73%", borderColor: "#ef4444", bottom: -5 }} />
            <div style={{ position: "absolute", bottom: -22, left: "73%", transform: "translateX(-50%)", fontSize: 9, fontWeight: 700, color: "#ef4444", letterSpacing: ".4px", textTransform: "uppercase", pointerEvents: "none" }}>NÃO</div>
          </>
        ) : (
          <Handle type="source" position={Position.Bottom} id="out" style={{ ...handleStyle, bottom: -5, borderColor: color }} />
        )
      )}
      {!isEnd && showAdd && <QuickAddButton nodeId={node.id} />}
    </motion.div>
  );
});

// Register ONCE at module scope so React Flow doesn't re-register on every render
const NODE_TYPES = { campaignNode: CampaignFlowNode };

// ─── Drag payload (module-level, bypasses unreliable dataTransfer in React Flow) ─
type PaletteItem = { type: CampaignNodeType; subtype: string; icon: string; label: string; desc: string };
let _dragPayload: PaletteItem | null = null;
let _addNodeBelow: ((sourceId: string, type: CampaignNodeType, subtype: string) => void) | null = null;
let _deleteEdge: ((edgeId: string) => void) | null = null;
let _selectNode: ((nodeId: string) => void) | null = null;

const QUICK_ADD_ITEMS: { type: CampaignNodeType; subtype: string; icon: string; label: string }[] = [
  { type: "send",      subtype: "",                  icon: "📨", label: "Enviar template" },
  { type: "send_text", subtype: "",                  icon: "💬", label: "Enviar texto" },
  { type: "wait",      subtype: "",                  icon: "⏱",  label: "Aguardar" },
  { type: "condition", subtype: "replied_recently",  icon: "🔀", label: "Condição" },
  { type: "action",    subtype: "move_stage",        icon: "📋", label: "Ação CRM" },
  { type: "action",    subtype: "mark_deal_won",     icon: "🏆", label: "Marcar deal ganho" },
  { type: "action",    subtype: "mark_deal_lost",    icon: "💔", label: "Marcar deal perdido" },
  { type: "action",    subtype: "add_note",          icon: "📝", label: "Adicionar nota" },
  { type: "action",    subtype: "assign_round_robin",  icon: "🎯", label: "Atribuir round-robin" },
  { type: "trigger",   subtype: "keyword_received",   icon: "🔍", label: "Palavra-chave" },
  { type: "end",       subtype: "",                   icon: "🏁", label: "Encerrar" },
];

const PALETTE_TRIGGERS: PaletteItem[] = [
  { type: "trigger", subtype: "stage_enter",       icon: "⚡", label: "Entrada em stage",       desc: "Lead entra em stage" },
  { type: "trigger", subtype: "stage_stagnation",  icon: "🕐", label: "Estagnação",              desc: "Parado X dias" },
  { type: "trigger", subtype: "no_message",        icon: "💤", label: "Sem mensagem",            desc: "Silêncio X dias" },
  { type: "trigger", subtype: "post_broadcast",    icon: "📡", label: "Pós-disparo",             desc: "Após broadcast" },
  { type: "trigger", subtype: "sale_created",      icon: "💰", label: "Venda criada",            desc: "Nova venda registrada" },
  { type: "trigger", subtype: "repurchase_window", icon: "🔄", label: "Janela de recompra",      desc: "X dias desde última compra" },
  { type: "trigger", subtype: "no_sale_in_stage",  icon: "📉", label: "Sem venda no stage",      desc: "Stage avançado sem venda" },
  { type: "trigger", subtype: "tag_added",         icon: "🏷️", label: "Tag adicionada",          desc: "Lead recebeu uma tag" },
  { type: "trigger", subtype: "deal_stage_enter",  icon: "🤝", label: "Entrou em stage (deal)",  desc: "Deal mudou de stage" },
  { type: "trigger", subtype: "deal_closed_lost",  icon: "❌", label: "Deal perdido",             desc: "Deal marcado como perdido" },
  { type: "trigger", subtype: "keyword_received",  icon: "🔍", label: "Palavra-chave",            desc: "Lead enviou palavra-chave" },
];
const PALETTE_ACTIONS: PaletteItem[] = [
  { type: "send",      subtype: "",                icon: "📨", label: "Enviar template", desc: "Mensagem HSM Meta" },
  { type: "send_text", subtype: "",                icon: "💬", label: "Enviar texto",    desc: "Texto livre (24h)" },
  { type: "wait",      subtype: "",                icon: "⏱", label: "Aguardar",        desc: "Delay em dias" },
  { type: "condition", subtype: "replied_recently", icon: "🔀", label: "Condição",       desc: "Ramificação lógica" },
  { type: "action",    subtype: "move_stage",      icon: "📋", label: "Mover stage",     desc: "Kanban move" },
  { type: "action",    subtype: "activate_agent",  icon: "🤖", label: "Ativar agente",   desc: "Assign ValerIA" },
  { type: "end",       subtype: "",                icon: "🏁", label: "Encerrar",        desc: "Fim da campanha" },
];

function PaletteItemComp({ item, onAdd }: { item: PaletteItem; onAdd: (item: PaletteItem) => void }) {
  const meta = NODE_META[item.type];
  const iconBg = meta.iconBg;

  const onDragStart = (e: DragEvent) => {
    _dragPayload = item;
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onClick={() => onAdd(item)}
      style={{
        display: "flex", alignItems: "center", gap: 9,
        padding: "8px 10px", borderRadius: 8,
        border: "1px solid #ede9e3", marginBottom: 5,
        cursor: "pointer", background: "#faf9f6",
        transition: "all .14s",
        userSelect: "none",
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = "#c0b9b0"; e.currentTarget.style.background = "#f0ede8"; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = "#ede9e3"; e.currentTarget.style.background = "#faf9f6"; }}
    >
      <div style={{
        width: 28, height: 28, borderRadius: 7,
        background: iconBg,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 14, flexShrink: 0,
      }}>
        {item.icon}
      </div>
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: "#1a1a1a", lineHeight: 1.2 }}>{item.label}</div>
        <div style={{ fontSize: 10, color: "#9b9590", marginTop: 1 }}>{item.desc}</div>
      </div>
    </div>
  );
}

// ─── API data types for Inspector dropdowns ────────────────────────────────────
interface FlowTemplate { id: string; name: string; status: string; language: string }
interface FlowStage    { id: string; label: string; pipeline_name: string; key: string | null }
interface FlowTag      { id: string; name: string }
interface FlowUser     { id: string; name: string; email: string }

interface FlowBuilderData {
  templates: FlowTemplate[];
  allStages: FlowStage[];
  tags: FlowTag[];
  users: FlowUser[];
  channels: { id: string; name: string; is_active: boolean; provider: string }[];
}

// ─── Test mode types ───────────────────────────────────────────────────────────
type TestNodeState = "running" | "done" | "failed";

interface TestEvent {
  node_id: string | null;
  status: "running" | "done" | "failed" | "finished";
  log?: string;
  duration_ms?: number;
}

interface TestLogEntry extends TestEvent {
  node_label: string;
}

// ─── Inspector ─────────────────────────────────────────────────────────────────
interface InspectorProps {
  node: CampaignNode;
  saving: boolean;
  data: FlowBuilderData;
  onSave: (nodeId: string, config: Record<string, unknown>) => Promise<void>;
  onDelete: (nodeId: string) => Promise<void>;
  onClose: () => void;
}

function Inspector({ node, saving, data, onSave, onDelete, onClose }: InspectorProps) {
  const { templates, allStages, tags, users } = data;
  const [draft, setDraft] = useState<Record<string, unknown>>(node.config as Record<string, unknown>);
  const meta = NODE_META[node.type];

  useEffect(() => {
    setDraft(node.config as Record<string, unknown>);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.id]);

  const set = (key: string, value: unknown) => setDraft(prev => ({ ...prev, [key]: value }));
  const c = draft;

  const input: React.CSSProperties = {
    width: "100%", padding: "8px 11px",
    border: "1px solid #e0dbd4", borderRadius: 7,
    fontFamily: "'Outfit', sans-serif", fontSize: 13, color: "#111",
    background: "#faf9f6", outline: "none",
  };
  const label: React.CSSProperties = {
    display: "block", fontSize: 10, fontWeight: 700, letterSpacing: ".5px",
    textTransform: "uppercase", color: "#b0a8a0", marginBottom: 5,
  };
  const field: React.CSSProperties = { marginBottom: 14 };

  return (
    <div style={{
      width: 256, flexShrink: 0,
      background: "#fff", borderLeft: "1px solid #e8e4df",
      display: "flex", flexDirection: "column",
      fontFamily: "'Outfit', sans-serif",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{ padding: "14px 16px 12px", borderBottom: "1px solid #ede9e3", display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ width: 30, height: 30, borderRadius: 7, background: meta.iconBg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15 }}>{meta.icon}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#111" }}>{meta.label}</div>
          <div style={{ fontSize: 11, color: "#9b9590", marginTop: 1 }}>{meta.kicker}</div>
        </div>
        <button onClick={onClose} style={{ width: 24, height: 24, borderRadius: 6, border: "1px solid #e0dbd4", background: "#faf9f6", cursor: "pointer", fontSize: 13, color: "#888" }}>✕</button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
        {node.type === "trigger" && (
          <>
            <div style={field}>
              <label style={label}>Tipo de gatilho</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.trigger_type as string) ?? ""} onChange={e => set("trigger_type", e.target.value)}>
                <option value="no_message">Sem mensagem</option>
                <option value="stage_stagnation">Estagnação de stage</option>
                <option value="stage_enter">Entrou em stage</option>
                <option value="post_broadcast">Pós-disparo</option>
                <option value="sale_created">Venda criada</option>
                <option value="repurchase_window">Janela de recompra</option>
                <option value="no_sale_in_stage">Sem venda no stage</option>
                <option value="tag_added">Tag adicionada</option>
                <option value="deal_stage_enter">Entrou em stage (deal)</option>
                <option value="deal_closed_lost">Deal perdido</option>
                <option value="keyword_received">Palavra-chave recebida</option>
              </select>
            </div>
            {(c.trigger_type === "no_message" || c.trigger_type === "stage_stagnation") && (
              <div style={field}><label style={label}>Dias</label><input type="number" style={input} value={(c.days as number) ?? 0} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
            )}
            {(c.trigger_type === "stage_stagnation" || c.trigger_type === "stage_enter") && (
              <div style={field}>
                <label style={label}>Filtro de stage</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage_filter as string) ?? ""} onChange={e => set("stage_filter", e.target.value)}>
                  <option value="">— Qualquer stage —</option>
                  {allStages.map(s => <option key={s.id} value={s.label}>{s.pipeline_name} › {s.label}</option>)}
                </select>
              </div>
            )}
            {c.trigger_type === "sale_created" && (
              <>
                <div style={field}><label style={label}>Valor mínimo (R$, opcional)</label>
                  <input type="number" style={input} value={(c.min_value as number) ?? ""} onChange={e => set("min_value", e.target.value ? Number(e.target.value) : null)} placeholder="Ex: 500" /></div>
                <div style={field}><label style={label}>Filtro de produto (opcional)</label>
                  <input type="text" style={input} value={(c.product_filter as string) ?? ""} onChange={e => set("product_filter", e.target.value || null)} placeholder="Ex: café" /></div>
              </>
            )}
            {(c.trigger_type === "repurchase_window" || c.trigger_type === "no_sale_in_stage") && (
              <div style={field}><label style={label}>Dias</label>
                <input type="number" style={input} value={(c.days as number) ?? 30} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
            )}
            {(c.trigger_type === "no_sale_in_stage" || c.trigger_type === "deal_stage_enter") && (
              <div style={field}>
                <label style={label}>Filtro de stage</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage_filter as string) ?? ""} onChange={e => set("stage_filter", e.target.value)}>
                  <option value="">— Qualquer stage —</option>
                  {allStages.map(s => <option key={s.id} value={s.label}>{s.pipeline_name} › {s.label}</option>)}
                </select>
              </div>
            )}
            {c.trigger_type === "tag_added" && (
              <div style={field}>
                <label style={label}>Tag</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.tag_name as string) ?? ""} onChange={e => set("tag_name", e.target.value)}>
                  <option value="">— Selecione uma tag —</option>
                  {tags.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
                </select>
              </div>
            )}
            {c.trigger_type === "post_broadcast" && (
              <div style={field}>
                <label style={label}>Apenas quem respondeu?</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.replied_only as boolean) ? "true" : "false"} onChange={e => set("replied_only", e.target.value === "true")}>
                  <option value="false">Todos os leads do disparo</option>
                  <option value="true">Apenas quem respondeu</option>
                </select>
              </div>
            )}
            {(c.trigger_type as string) === "keyword_received" && (
              <div style={field}>
                <label style={label}>Palavras-chave (separadas por vírgula)</label>
                <input
                  style={input as React.CSSProperties}
                  type="text"
                  value={((c.keywords as string[]) ?? []).join(", ")}
                  onChange={e =>
                    set(
                      "keywords",
                      e.target.value
                        .split(",")
                        .map(s => s.trim())
                        .filter(Boolean)
                    )
                  }
                  placeholder="Ex: preço, valor, quanto custa"
                />
                <p style={{ fontSize: 11, color: "#9b9590", marginTop: 4 }}>
                  Quando o lead enviar uma mensagem contendo qualquer uma destas palavras (case-insensitive), a cadência será disparada.
                </p>
              </div>
            )}
          </>
        )}
        {node.type === "send" && (
          <>
            <div style={field}>
              <label style={label}>Template</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.template_name as string) ?? ""} onChange={e => set("template_name", e.target.value)}>
                <option value="">— Selecione um template —</option>
                {templates.filter(t => t.status === "approved" || t.status === "APPROVED").map(t => (
                  <option key={t.id} value={t.name}>{t.name} ({t.language})</option>
                ))}
                {templates.filter(t => t.status !== "approved" && t.status !== "APPROVED").length > 0 && (
                  <optgroup label="Aguardando aprovação">
                    {templates.filter(t => t.status !== "approved" && t.status !== "APPROVED").map(t => (
                      <option key={t.id} value={t.name} disabled>{t.name} ({t.status})</option>
                    ))}
                  </optgroup>
                )}
              </select>
              {templates.length === 0 && <p style={{ fontSize: 11, color: "#9b9590", marginTop: 4 }}>Nenhum template cadastrado</p>}
            </div>
            <div style={field}>
              <label style={label}>Ao responder</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.on_reply as string) ?? "pause"} onChange={e => set("on_reply", e.target.value)}>
                <option value="pause">Pausar campanha</option>
                <option value="cancel">Cancelar campanha</option>
                <option value="continue">Continuar campanha</option>
              </select>
            </div>
            <div style={field}>
              <label style={label}>Canal (override)</label>
              <select
                style={{ ...input, appearance: "none" } as React.CSSProperties}
                value={(c.channel_id as string) ?? ""}
                onChange={e => set("channel_id", e.target.value || null)}
              >
                <option value="">— Usar padrão da cadência —</option>
                {data.channels.map(ch => <option key={ch.id} value={ch.id}>{ch.name}</option>)}
              </select>
            </div>
          </>
        )}
        {node.type === "send_text" && (
          <>
            <div style={field}>
              <label style={label}>Mensagem (vars: {"{{nome}}, {{empresa}}, {{produto}}"})</label>
              <textarea
                style={{ ...input, minHeight: 80, resize: "vertical" }}
                value={(c.message_text as string) ?? ""}
                onChange={e => set("message_text", e.target.value)}
                placeholder="Olá {{nome}}, tudo bem?"
              />
            </div>
            <div style={field}>
              <label style={label}>Ao responder</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.on_reply as string) ?? "pause"} onChange={e => set("on_reply", e.target.value)}>
                <option value="pause">Pausar campanha</option>
                <option value="cancel">Cancelar campanha</option>
                <option value="continue">Continuar campanha</option>
              </select>
            </div>
            <div style={field}>
              <label style={label}>Canal (override)</label>
              <select
                style={{ ...input, appearance: "none" } as React.CSSProperties}
                value={(c.channel_id as string) ?? ""}
                onChange={e => set("channel_id", e.target.value || null)}
              >
                <option value="">— Usar padrão da cadência —</option>
                {data.channels.map(ch => <option key={ch.id} value={ch.id}>{ch.name}</option>)}
              </select>
            </div>
            <div style={{ ...field, padding: "8px 10px", background: "#fef9ed", borderRadius: 6, border: "1px solid #fde68a" }}>
              <p style={{ fontSize: 11, color: "#92400e", lineHeight: 1.5 }}>
                ⚠️ Texto livre — só enviado dentro da janela de 24h após o cliente responder. Se a janela estiver expirada, o nó é pulado automaticamente.
              </p>
            </div>
          </>
        )}
        {node.type === "wait" && (
          <div style={field}><label style={label}>Dias de espera</label><input type="number" style={input} value={(c.days as number) ?? 1} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
        )}
        {node.type === "condition" && (
          <>
            <div style={field}>
              <label style={label}>Condição</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.condition_type as string) ?? ""} onChange={e => set("condition_type", e.target.value)}>
                <option value="replied_recently">Respondeu recentemente</option>
                <option value="in_stage">Está em stage</option>
                <option value="has_deal">Tem deal ativo</option>
                <option value="sale_count">Número de vendas</option>
                <option value="total_spend">Gasto total (R$)</option>
                <option value="last_sale_value">Valor da última venda</option>
                <option value="deal_value">Valor do deal</option>
                <option value="has_tag">Possui tag</option>
                <option value="repurchase_days">Dias desde última compra</option>
              </select>
            </div>
            {c.condition_type === "replied_recently" && (
              <div style={field}><label style={label}>Dias</label><input type="number" style={input} value={(c.days as number) ?? 5} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
            )}
            {c.condition_type === "in_stage" && (
              <div style={field}>
                <label style={label}>Stage</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage as string) ?? ""} onChange={e => set("stage", e.target.value)}>
                  <option value="">— Selecione um stage —</option>
                  {allStages.map(s => <option key={s.id} value={s.label}>{s.pipeline_name} › {s.label}</option>)}
                </select>
              </div>
            )}
            {["sale_count","total_spend","last_sale_value","deal_value","repurchase_days"].includes(c.condition_type as string) && (
              <>
                <div style={field}>
                  <label style={label}>Operador</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.operator as string) ?? "gte"} onChange={e => set("operator", e.target.value)}>
                    <option value="gte">≥ (maior ou igual)</option>
                    <option value="lte">≤ (menor ou igual)</option>
                    <option value="gt">&gt; (maior)</option>
                    <option value="lt">&lt; (menor)</option>
                    <option value="eq">= (igual)</option>
                  </select>
                </div>
                <div style={field}><label style={label}>Valor</label>
                  <input type="number" style={input} value={(c.value as number) ?? 0} onChange={e => set("value", Number(e.target.value))} min={0} /></div>
              </>
            )}
            {c.condition_type === "has_tag" && (
              <div style={field}>
                <label style={label}>Tag</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.tag_name as string) ?? ""} onChange={e => set("tag_name", e.target.value)}>
                  <option value="">— Selecione uma tag —</option>
                  {tags.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
                </select>
              </div>
            )}
          </>
        )}
        {node.type === "action" && (() => {
          const at = c.action_type as string;
          return (
            <>
              <div style={field}>
                <label style={label}>Tipo de ação</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={at ?? ""} onChange={e => set("action_type", e.target.value)}>
                  {Object.entries(ACTION_LABELS).map(([key, val]) => (
                    <option key={key} value={key}>{val}</option>
                  ))}
                </select>
              </div>

              {at === "move_stage" && (
                <div style={field}>
                  <label style={label}>Stage de destino (lead)</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage_id as string) ?? ""} onChange={e => set("stage_id", e.target.value)}>
                    <option value="">— selecione —</option>
                    {allStages.map(s => <option key={s.id} value={s.id}>{s.pipeline_name} › {s.label}</option>)}
                  </select>
                </div>
              )}

              {(at === "mark_deal_won" || at === "mark_deal_lost" || at === "move_deal_stage") && (
                <div style={field}>
                  <label style={label}>Estágio do deal (pipeline)</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage_id as string) ?? ""} onChange={e => set("stage_id", e.target.value)}>
                    <option value="">— selecione —</option>
                    {allStages.map(s => <option key={s.id} value={s.id}>{s.pipeline_name} › {s.label}</option>)}
                  </select>
                </div>
              )}

              {(at === "add_tag" || at === "remove_tag") && (
                <div style={field}>
                  <label style={label}>Nome da tag</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.tag_name as string) ?? ""} onChange={e => set("tag_name", e.target.value)}>
                    <option value="">— selecione —</option>
                    {tags.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
                  </select>
                </div>
              )}

              {at === "add_note" && (
                <div style={field}>
                  <label style={label}>Texto da nota (suporta {`{{lead.name}}`})</label>
                  <textarea
                    style={{ ...input, minHeight: 70, resize: "vertical" } as React.CSSProperties}
                    value={(c.note_template as string) ?? ""}
                    onChange={e => set("note_template", e.target.value)}
                    placeholder="Ex: Lead {{lead.name}} chegou no nó X"
                  />
                </div>
              )}

              {at === "create_deal" && (
                <div style={field}>
                  <label style={label}>Título do deal (suporta {`{{nome}}`})</label>
                  <input type="text" style={input} value={(c.title_template as string) ?? ""} onChange={e => set("title_template", e.target.value)} placeholder="Deal automático — {{empresa}}" />
                </div>
              )}

              {at === "assign_to" && (
                <div style={field}>
                  <label style={label}>Vendedor</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.user_id as string) ?? ""} onChange={e => set("user_id", e.target.value)}>
                    <option value="">— selecione —</option>
                    {users.map(u => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
                  </select>
                </div>
              )}

              {at === "assign_round_robin" && (
                <div style={field}>
                  <label style={label}>Vendedores no rodízio</label>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {users.map(u => {
                      const selected = ((c.user_ids as string[]) ?? []).includes(u.id);
                      return (
                        <button
                          key={u.id}
                          type="button"
                          onClick={() => {
                            const arr = ((c.user_ids as string[]) ?? []).slice();
                            const idx = arr.indexOf(u.id);
                            if (idx >= 0) arr.splice(idx, 1); else arr.push(u.id);
                            set("user_ids", arr);
                          }}
                          style={{
                            padding: "5px 10px",
                            borderRadius: 6,
                            border: `1px solid ${selected ? "#E85D26" : "#e0dbd4"}`,
                            background: selected ? "rgba(232,93,38,.08)" : "#fff",
                            color: selected ? "#E85D26" : "#555",
                            fontSize: 12,
                            cursor: "pointer",
                          }}
                        >
                          {u.name || u.email}
                        </button>
                      );
                    })}
                    {users.length === 0 && <p style={{ fontSize: 11, color: "#9b9590" }}>Nenhum usuário disponível</p>}
                  </div>
                </div>
              )}
            </>
          );
        })()}
        {node.type === "end" && (
          <div style={field}><label style={label}>Rótulo final</label><input type="text" style={input} value={(c.label as string) ?? ""} onChange={e => set("label", e.target.value)} placeholder="ex: Concluído" /></div>
        )}
      </div>

      {/* Footer */}
      <div style={{ padding: "12px 16px", borderTop: "1px solid #ede9e3", display: "flex", gap: 6 }}>
        <button
          onClick={() => onSave(node.id, draft)}
          disabled={saving}
          style={{
            flex: 1, height: 34, borderRadius: 7, border: "none",
            background: saving ? "#ccc" : "#111", color: "#fff",
            fontFamily: "'Outfit', sans-serif", fontSize: 12, fontWeight: 500,
            cursor: saving ? "default" : "pointer",
          }}
        >
          {saving ? "Salvando..." : "Salvar"}
        </button>
        <button
          onClick={() => onDelete(node.id)}
          style={{
            height: 34, padding: "0 12px", borderRadius: 7,
            border: "1px solid #fecaca", background: "#fff5f5",
            color: "#dc2626", fontFamily: "'Outfit', sans-serif",
            fontSize: 12, cursor: "pointer",
          }}
        >
          Remover
        </button>
      </div>
    </div>
  );
}

// ─── Inner builder (needs useReactFlow, so must be inside ReactFlowProvider) ───
function FlowBuilderInner({ campaignId }: { campaignId: string }) {
  const router = useRouter();
  const { screenToFlowPosition, zoomIn, zoomOut, fitView } = useReactFlow();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [dbNodes, setDbNodes] = useState<CampaignNode[]>([]);
  const [rfNodes, setRFNodes, onNodesChange] = useNodesState<Node>([]);
  const [rfEdges, setRFEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [edgeContextMenu, setEdgeContextMenu] = useState<{ x: number; y: number; edgeId: string } | null>(null);
  const edgeContextMenuRef = useRef<HTMLDivElement>(null);

  const [flowData, setFlowData] = useState<FlowBuilderData>({ templates: [], allStages: [], tags: [], users: [], channels: [] });

  // ── Test mode state ───────────────────────────────────────────────────────
  const [testNodeStates, setTestNodeStates] = useState<Record<string, TestNodeState>>({});
  const [testLog, setTestLog] = useState<TestLogEntry[]>([]);
  const [testRunning, setTestRunning] = useState(false);
  const [testFinished, setTestFinished] = useState(false);
  const [showTestModal, setShowTestModal] = useState(false);
  const [testPhone, setTestPhone] = useState("");
  const [testSkipDelays, setTestSkipDelays] = useState(true);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Cleanup EventSource on unmount
  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  // Load campaign + nodes
  useEffect(() => {
    fetch(`/api/campaigns/${campaignId}`)
      .then(r => r.json())
      .then(data => {
        setCampaign(data);
        const nodes: CampaignNode[] = data.nodes ?? [];
        setDbNodes(nodes);
        setRFNodes(nodes.map(toRFNode));
        setRFEdges(toRFEdges(nodes));
      });
  }, [campaignId, setRFNodes, setRFEdges]);

  // Load auxiliary data for Inspector dropdowns
  useEffect(() => {
    async function loadFlowData() {
      const [templatesRes, pipelinesRes, tagsRes, usersRes, channelsRes] = await Promise.all([
        fetch("/api/templates"),
        fetch("/api/pipelines"),
        fetch("/api/tags"),
        fetch("/api/users"),
        fetch("/api/channels"),
      ]);
      const [templatesData, pipelinesData, tagsData, usersData, channelsData] = await Promise.all([
        templatesRes.ok ? templatesRes.json() : [],
        pipelinesRes.ok ? pipelinesRes.json() : [],
        tagsRes.ok ? tagsRes.json() : [],
        usersRes.ok ? usersRes.json() : [],
        channelsRes.ok ? channelsRes.json() : [],
      ]);

      // Fetch stages for every pipeline in parallel
      const stageResults = await Promise.all(
        (pipelinesData as { id: string; name: string }[]).map(async (p) => {
          const res = await fetch(`/api/pipelines/${p.id}/stages`);
          const stages = res.ok ? await res.json() : [];
          return (stages as { id: string; label: string; key: string | null }[]).map(s => ({
            id: s.id,
            label: s.label,
            pipeline_name: p.name,
            key: s.key,
          }));
        })
      );

      const connectedChannels = (channelsData as { id: string; name: string; is_active: boolean; provider: string }[]).filter(
        ch => ch.is_active
      );

      setFlowData({
        templates: templatesData as FlowTemplate[],
        allStages: stageResults.flat(),
        tags: tagsData as FlowTag[],
        users: usersData as FlowUser[],
        channels: connectedChannels,
      });
    }
    loadFlowData();
  }, []);

  // Keyboard zoom: =|+ zoom in, - zoom out, 0 fit view
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "=" || e.key === "+") { e.preventDefault(); zoomIn({ duration: 200 }); }
      else if (e.key === "-")             { e.preventDefault(); zoomOut({ duration: 200 }); }
      else if (e.key === "0")             { e.preventDefault(); fitView({ padding: 0.3, duration: 400 }); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomIn, zoomOut, fitView]);

  // Add node below + auto-connect (Quick-Add button)
  const addNodeBelow = useCallback(async (sourceId: string, type: CampaignNodeType, subtype: string) => {
    const sourceRF = rfNodes.find(n => n.id === sourceId);
    if (!sourceRF) return;

    const res = await fetch(`/api/campaigns/${campaignId}/nodes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type,
        config: getDefaultConfig(type, subtype),
        position_x: Math.round(sourceRF.position.x),
        position_y: Math.round(sourceRF.position.y + 200),
      }),
    });
    if (!res.ok) return;
    const newNode: CampaignNode = await res.json();

    // Persist edge: PATCH source node next_node_id
    await fetch(`/api/campaigns/${campaignId}/nodes/${sourceId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ next_node_id: newNode.id }),
    });

    // Update local state
    setDbNodes(prev => [
      ...prev.map(n => n.id === sourceId ? { ...n, next_node_id: newNode.id } : n),
      newNode,
    ]);
    setRFNodes(prev => [...prev, toRFNode(newNode)]);
    setRFEdges(prev => [
      ...prev.filter(e => !(e.source === sourceId && e.sourceHandle === "out")),
      {
        id: `${sourceId}→${newNode.id}`,
        source: sourceId,
        sourceHandle: "out",
        target: newNode.id,
        targetHandle: "in",
        style: { stroke: "#c8c2bb", strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#c8c2bb", width: 14, height: 14 },
        type: "deletable",
      } as Edge,
    ]);
  }, [campaignId, rfNodes, setRFNodes, setRFEdges, setDbNodes]);

  // Keep module-level ref updated so QuickAddButton can call it
  useEffect(() => {
    _addNodeBelow = addNodeBelow;
    return () => { _addNodeBelow = null; };
  }, [addNodeBelow]);

  // ── deleteEdge callback ───────────────────────────────────────────────────────
  const deleteEdge = useCallback(async (edgeId: string) => {
    const edge = rfEdges.find(e => e.id === edgeId);
    if (!edge) return;
    const linkField = edge.sourceHandle === "yes" ? "yes_node_id"
      : edge.sourceHandle === "no" ? "no_node_id"
      : "next_node_id";
    await fetch(`/api/campaigns/${campaignId}/nodes/${edge.source}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [linkField]: null }),
    });
    setDbNodes(prev => prev.map(n => n.id === edge.source ? { ...n, [linkField]: null } : n));
    setRFEdges(prev => prev.filter(e => e.id !== edgeId));
    setEdgeContextMenu(null);
  }, [campaignId, rfEdges, setRFEdges, setDbNodes]);

  useEffect(() => {
    _deleteEdge = deleteEdge;
    return () => { _deleteEdge = null; };
  }, [deleteEdge]);

  // Manter _selectNode atualizado para CampaignFlowNode acessar sem closure stale
  useEffect(() => {
    _selectNode = (nodeId: string) => setSelectedNodeId(nodeId);
    return () => { _selectNode = null; };
  }, []);

  // ── Edge right-click → context menu ──────────────────────────────────────────
  const onEdgeContextMenu = useCallback((e: React.MouseEvent, edge: Edge) => {
    e.preventDefault();
    e.stopPropagation();
    setEdgeContextMenu({ x: e.clientX, y: e.clientY, edgeId: edge.id });
  }, []);

  // Close edge context menu on outside click
  useEffect(() => {
    if (!edgeContextMenu) return;
    const handler = (e: MouseEvent) => {
      if (edgeContextMenuRef.current && !edgeContextMenuRef.current.contains(e.target as unknown as globalThis.Node)) {
        setEdgeContextMenu(null);
      }
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [edgeContextMenu]);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setEdgeContextMenu(null);
  }, []);

  // ── Save position after drag ───────────────────────────────────────────────
  const onNodeDragStop: OnNodeDrag = useCallback((_e, node) => {
    fetch(`/api/campaigns/${campaignId}/nodes/${node.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_x: Math.round(node.position.x), position_y: Math.round(node.position.y) }),
    });
    setDbNodes(prev => prev.map(n => n.id === node.id ? { ...n, position_x: node.position.x, position_y: node.position.y } : n));
  }, [campaignId]);

  // ── Connect two handles → PATCH source node ───────────────────────────────
  const onConnect: OnConnect = useCallback(async (connection: Connection) => {
    const { source, target, sourceHandle } = connection;
    if (!source || !target) return;
    const linkField = sourceHandle === "yes" ? "yes_node_id" : sourceHandle === "no" ? "no_node_id" : "next_node_id";
    await fetch(`/api/campaigns/${campaignId}/nodes/${source}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [linkField]: target }),
    });
    setDbNodes(prev => prev.map(n => n.id === source ? { ...n, [linkField]: target } : n));
    const edgeColor = sourceHandle === "yes" ? "#1A9B6C" : sourceHandle === "no" ? "#ef4444" : "#c8c2bb";
    setRFEdges(eds => addEdge({
      ...connection,
      style: { stroke: edgeColor, strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor, width: 14, height: 14 },
      type: "deletable",
      label: sourceHandle === "yes" ? "SIM" : sourceHandle === "no" ? "NÃO" : undefined,
      labelStyle: sourceHandle === "yes" ? { fill: "#1A9B6C", fontSize: 9, fontWeight: 700 } : sourceHandle === "no" ? { fill: "#ef4444", fontSize: 9, fontWeight: 700 } : undefined,
    } as Edge, eds));
  }, [campaignId, setRFEdges]);

  // ── Drag from palette → drop on canvas ────────────────────────────────────
  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  // ── Add a node to canvas (shared by click and drop) ───────────────────────
  const addNodeToCanvas = useCallback(async (item: PaletteItem, clientPos?: { x: number; y: number }) => {
    const { type, subtype } = item;

    // Position: use dropped position if provided, otherwise auto-stack
    let position: { x: number; y: number };
    if (clientPos && reactFlowWrapper.current) {
      position = screenToFlowPosition({ x: clientPos.x, y: clientPos.y });
    } else {
      // Stack nodes: find lowest Y among existing nodes, place below with offset
      const baseX = 300;
      const baseY = rfNodes.length > 0
        ? Math.max(...rfNodes.map(n => n.position.y)) + 160
        : 100;
      position = { x: baseX, y: baseY };
    }

    const res = await fetch(`/api/campaigns/${campaignId}/nodes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type,
        config: getDefaultConfig(type, subtype),
        position_x: Math.round(position.x),
        position_y: Math.round(position.y),
      }),
    });
    if (!res.ok) return;
    const newNode: CampaignNode = await res.json();
    setDbNodes(prev => [...prev, newNode]);
    setRFNodes(prev => [...prev, toRFNode(newNode)]);
  }, [campaignId, screenToFlowPosition, setRFNodes, rfNodes]);

  const onDrop = useCallback(async (e: DragEvent) => {
    e.preventDefault();
    const payload = _dragPayload;
    _dragPayload = null;
    if (!payload) return;
    await addNodeToCanvas(payload, { x: e.clientX, y: e.clientY });
  }, [addNodeToCanvas]);

  // ── Save inspector config ─────────────────────────────────────────────────
  const saveNode = useCallback(async (nodeId: string, config: Record<string, unknown>) => {
    setSaving(true);
    await fetch(`/api/campaigns/${campaignId}/nodes/${nodeId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    });
    setDbNodes(prev => prev.map(n => n.id === nodeId ? { ...n, config } : n));
    setRFNodes(prev => prev.map(n => n.id === nodeId ? { ...n, data: { ...n.data, config } } : n));
    setSaving(false);
  }, [campaignId, setRFNodes]);

  // ── Delete node ───────────────────────────────────────────────────────────
  const deleteNode = useCallback(async (nodeId: string) => {
    await fetch(`/api/campaigns/${campaignId}/nodes/${nodeId}`, { method: "DELETE" });
    setDbNodes(prev => prev.filter(n => n.id !== nodeId).map(n => ({
      ...n,
      next_node_id: n.next_node_id === nodeId ? null : n.next_node_id,
      yes_node_id:  n.yes_node_id  === nodeId ? null : n.yes_node_id,
      no_node_id:   n.no_node_id   === nodeId ? null : n.no_node_id,
    })));
    setRFNodes(prev => prev.filter(n => n.id !== nodeId));
    setRFEdges(prev => prev.filter(e => e.source !== nodeId && e.target !== nodeId));
    setSelectedNodeId(null);
  }, [campaignId, setRFNodes, setRFEdges]);

  // ── Activate / pause campaign ─────────────────────────────────────────────
  const toggleActivation = useCallback(async () => {
    if (!campaign) return;
    const endpoint = campaign.status === "active" ? "pause" : "activate";
    const res = await fetch(`/api/campaigns/${campaignId}/${endpoint}`, { method: "POST" });
    const data = await res.json();
    if (data.error) { alert(data.error); return; }
    setCampaign(prev => prev ? { ...prev, status: data.status } : prev);
  }, [campaign, campaignId]);

  // ── Test mode: start SSE test run ────────────────────────────────────────
  const startTest = useCallback(() => {
    if (!testPhone.trim()) return;
    setShowTestModal(false);
    setTestNodeStates({});
    setTestLog([]);
    setTestRunning(true);
    setTestFinished(false);
    setSelectedNodeId(null);

    const url = `/api/campaigns/${campaignId}/test?phone=${encodeURIComponent(testPhone)}&skip_delays=${testSkipDelays}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (e) => {
      const evt: TestEvent = JSON.parse(e.data);
      if (evt.status === "finished") {
        setTestRunning(false);
        setTestFinished(true);
        es.close();
        return;
      }
      if (!evt.node_id) return;
      setTestNodeStates(prev => ({ ...prev, [evt.node_id!]: evt.status as TestNodeState }));
      if (evt.status !== "running") {
        const node = dbNodes.find(n => n.id === evt.node_id);
        const meta = node ? NODE_META[node.type] : null;
        setTestLog(prev => [...prev, {
          ...evt,
          node_label: meta ? `${meta.icon} ${meta.label}` : (evt.node_id ?? ""),
        }]);
      }
    };
    es.onerror = () => {
      setTestRunning(false);
      setTestFinished(true);
      es.close();
    };
  }, [testPhone, testSkipDelays, campaignId, dbNodes]);

  const closeTest = useCallback(() => {
    eventSourceRef.current?.close();
    setTestNodeStates({});
    setTestLog([]);
    setTestRunning(false);
    setTestFinished(false);
  }, []);

  // ── Propagate test states to RF nodes ────────────────────────────────────
  useEffect(() => {
    setRFNodes(prev => prev.map(n => ({
      ...n,
      data: { ...n.data, testState: testNodeStates[n.id] ?? null },
    })));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [testNodeStates, setRFNodes]);

  const selectedDbNode = selectedNodeId ? dbNodes.find(n => n.id === selectedNodeId) ?? null : null;
  const st = campaign ? (STATUS_COLORS[campaign.status] ?? STATUS_COLORS.draft) : STATUS_COLORS.draft;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", fontFamily: "'Outfit', sans-serif" }}>
      <style>{FONT_STYLE}</style>

      {/* ── Topbar ──────────────────────────────────────────────────── */}
      <div style={{
        display: "flex", alignItems: "center", gap: 14,
        background: "#fff", borderBottom: "1px solid #e8e4df",
        padding: "0 20px", height: 52, flexShrink: 0, zIndex: 10,
      }}>
        <button
          onClick={() => router.push("/campanhas?tab=cadencias")}
          style={{
            width: 30, height: 30, borderRadius: 7,
            border: "1px solid #e8e4df", background: "transparent",
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", color: "#555", fontSize: 14,
          }}
          onMouseEnter={e => (e.currentTarget.style.background = "#f5f2ed")}
          onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
        >←</button>

        <span style={{ fontSize: 14, fontWeight: 600, color: "#111", letterSpacing: "-.2px" }}>
          {campaign?.name ?? "…"}
        </span>

        {campaign && (
          <span style={{
            padding: "3px 9px", borderRadius: 5,
            background: st.bg, border: `1px solid ${st.border}`,
            fontSize: 11, fontWeight: 500, color: st.color,
            letterSpacing: ".2px", textTransform: "uppercase",
          }}>
            {STATUS_LABELS[campaign.status] ?? campaign.status}
          </span>
        )}

        <div style={{ flex: 1 }} />

        <button
          onClick={() => setShowTestModal(true)}
          style={{
            height: 34, padding: "0 16px", borderRadius: 7,
            background: "#fff", border: "1px solid #e0dbd4",
            color: "#555", fontFamily: "'Outfit', sans-serif",
            fontSize: 13, fontWeight: 500, cursor: "pointer",
            display: "flex", alignItems: "center", gap: 6,
          }}
        >
          ⚡ Testar
        </button>

        <button
          onClick={toggleActivation}
          style={{
            height: 34, padding: "0 16px", borderRadius: 7,
            background: campaign?.status === "active" ? "#f5f2ed" : "#111",
            color: campaign?.status === "active" ? "#555" : "#fff",
            border: campaign?.status === "active" ? "1px solid #e0dbd4" : "none",
            fontFamily: "'Outfit', sans-serif", fontSize: 13, fontWeight: 500,
            cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
          }}
        >
          {campaign?.status === "active" ? "⏸ Pausar" : "▶ Ativar campanha"}
        </button>
      </div>

      {/* ── Workspace ────────────────────────────────────────────────── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ── Palette ──────────────────────────────────────────────── */}
        <div style={{
          width: 196, flexShrink: 0,
          background: "#fff", borderRight: "1px solid #e8e4df",
          padding: "16px 12px", overflowY: "auto",
          display: "flex", flexDirection: "column", gap: 18,
        }}>
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: "#b8b2aa", padding: "0 4px", marginBottom: 8 }}>
              Gatilhos
            </div>
            {PALETTE_TRIGGERS.map((item, i) => <PaletteItemComp key={i} item={item} onAdd={addNodeToCanvas} />)}
          </div>
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: "#b8b2aa", padding: "0 4px", marginBottom: 8 }}>
              Ações
            </div>
            {PALETTE_ACTIONS.map((item, i) => <PaletteItemComp key={i} item={item} onAdd={addNodeToCanvas} />)}
          </div>
        </div>

        {/* ── Canvas (React Flow) ───────────────────────────────────── */}
        <div
          ref={reactFlowWrapper}
          style={{ flex: 1, position: "relative" }}
          onDrop={onDrop}
          onDragOver={onDragOver}
          onContextMenu={(e) => e.preventDefault()}
        >
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onPaneClick={onPaneClick}
            onNodeDragStop={onNodeDragStop}
            nodeTypes={NODE_TYPES}
            edgeTypes={EDGE_TYPES}
            onEdgeContextMenu={onEdgeContextMenu}
            fitView={rfNodes.length > 0}
            fitViewOptions={{ padding: 0.3 }}
            deleteKeyCode={null}
            minZoom={0.2}
            maxZoom={2.5}
            panOnScroll={true}
            panOnScrollMode={PanOnScrollMode.Free}
            zoomOnScroll={true}
            snapToGrid={true}
            snapGrid={[20, 20]}
            nodeDragThreshold={8}
            connectionLineStyle={{ stroke: "#E85D26", strokeWidth: 1.5, strokeDasharray: "5,4" }}
            connectionLineType={ConnectionLineType.SmoothStep}
            style={{ background: "#f5f2ed" }}
            proOptions={{ hideAttribution: true }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={22}
              size={1}
              color="rgba(0,0,0,.12)"
            />
            <MiniMap
              position="bottom-right"
              style={{
                bottom: 90,
                border: "1px solid #e8e4df",
                borderRadius: 8,
                overflow: "hidden",
                background: "#f5f2ed",
              }}
              nodeColor={(n) => {
                const t = (n.data as Record<string, unknown>).type as string;
                return (NODE_META as Record<string, { color: string }>)[t]?.color ?? "#888";
              }}
              maskColor="rgba(245,242,237,0.75)"
            />
            <Controls position="bottom-right" showInteractive={false} />

            {/* Empty state */}
            {rfNodes.length === 0 && (
              <Panel position="top-center" style={{ marginTop: "30vh" }}>
                <div style={{ textAlign: "center", fontFamily: "'Outfit', sans-serif" }}>
                  <div style={{ fontSize: 40, marginBottom: 12 }}>⚡</div>
                  <p style={{ fontSize: 15, fontWeight: 600, color: "#333", marginBottom: 6 }}>Nenhum nó no fluxo</p>
                  <p style={{ fontSize: 13, color: "#9b9590" }}>Clique em um item da paleta esquerda para adicionar</p>
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>

        {/* Edge context menu */}
        {edgeContextMenu && (
          <div
            ref={edgeContextMenuRef}
            style={{
              position: "fixed",
              top: edgeContextMenu.y,
              left: edgeContextMenu.x,
              zIndex: 9999,
              background: "#fff",
              border: "1px solid #e8e4df",
              borderRadius: 8,
              boxShadow: "0 8px 24px rgba(0,0,0,.14), 0 2px 6px rgba(0,0,0,.08)",
              padding: "4px",
              minWidth: 160,
            }}
          >
            <button
              onClick={() => deleteEdge(edgeContextMenu.edgeId)}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                width: "100%", padding: "8px 12px",
                border: "none", background: "transparent",
                cursor: "pointer", borderRadius: 6,
                fontFamily: "'Outfit', sans-serif",
                fontSize: 13, color: "#dc2626", textAlign: "left",
              }}
              onMouseEnter={e => { e.currentTarget.style.background = "#fff5f5"; }}
              onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
            >
              <span>✕</span>
              <span>Deletar conexão</span>
            </button>
          </div>
        )}

        {/* ── Inspector / Execution Panel ───────────────────────────── */}
        {(testRunning || testFinished) ? (
          <div style={{ width: 256, flexShrink: 0, background: "#fff", borderLeft: "1px solid #e8e4df", display: "flex", flexDirection: "column", fontFamily: "'Outfit', sans-serif" }}>
            <div style={{ padding: "14px 16px 12px", borderBottom: "1px solid #ede9e3", display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#111", flex: 1 }}>⚡ Execução de Teste</div>
              <button onClick={closeTest} style={{ width: 24, height: 24, borderRadius: 6, border: "1px solid #e0dbd4", background: "#faf9f6", cursor: "pointer", fontSize: 13, color: "#888" }}>✕</button>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
              {testLog.length === 0 && testRunning && (
                <div style={{ fontSize: 13, color: "#9b9590", textAlign: "center", paddingTop: 24 }}>Iniciando execução...</div>
              )}
              {testLog.map((entry, i) => (
                <div key={i} style={{ marginBottom: 10, padding: "8px 10px", borderRadius: 7, background: entry.status === "failed" ? "#fff5f5" : "#f5faf7", border: `1px solid ${entry.status === "failed" ? "#fecaca" : "#d1fae5"}` }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
                    <span style={{ fontSize: 12 }}>{entry.status === "done" ? "✅" : "❌"}</span>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "#111" }}>{entry.node_label}</span>
                    {entry.duration_ms !== undefined && (
                      <span style={{ fontSize: 10, color: "#9b9590", marginLeft: "auto" }}>{entry.duration_ms}ms</span>
                    )}
                  </div>
                  {entry.log && (
                    <div style={{ fontSize: 11, color: entry.status === "failed" ? "#dc2626" : "#555", lineHeight: 1.5, wordBreak: "break-word" }}>
                      {entry.log}
                    </div>
                  )}
                </div>
              ))}
              {testFinished && (
                <div style={{ textAlign: "center", paddingTop: 8 }}>
                  <button
                    onClick={() => { setShowTestModal(true); setTestFinished(false); setTestNodeStates({}); setTestLog([]); }}
                    style={{ height: 30, padding: "0 14px", borderRadius: 7, border: "1px solid #e0dbd4", background: "#fff", color: "#555", fontFamily: "'Outfit', sans-serif", fontSize: 12, cursor: "pointer" }}
                  >
                    ↺ Testar novamente
                  </button>
                </div>
              )}
            </div>
          </div>
        ) : selectedDbNode ? (
          <Inspector
            key={selectedDbNode.id}
            node={selectedDbNode}
            saving={saving}
            data={flowData}
            onSave={saveNode}
            onDelete={deleteNode}
            onClose={() => setSelectedNodeId(null)}
          />
        ) : null}
      </div>

      {/* ── Test Modal ──────────────────────────────────────────────── */}
      {showTestModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(17,17,17,.45)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "#fff", borderRadius: 12, padding: 28, width: 380, boxShadow: "0 8px 32px rgba(0,0,0,.2)" }}>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 18, color: "#111", fontFamily: "'Outfit', sans-serif" }}>⚡ Testar cadência</div>
            <div style={{ marginBottom: 14 }}>
              <label style={{ display: "block", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".5px", color: "#b0a8a0", marginBottom: 5, fontFamily: "'Outfit', sans-serif" }}>
                Número de teste (com DDI, ex: 5511999990000)
              </label>
              <input
                type="text"
                value={testPhone}
                onChange={e => setTestPhone(e.target.value)}
                placeholder="5511999990000"
                style={{ width: "100%", padding: "8px 11px", border: "1px solid #e0dbd4", borderRadius: 7, fontFamily: "'Outfit', sans-serif", fontSize: 13, color: "#111", background: "#faf9f6", outline: "none", boxSizing: "border-box" }}
              />
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", marginBottom: 20, fontFamily: "'Outfit', sans-serif" }}>
              <input
                type="checkbox"
                checked={testSkipDelays}
                onChange={e => setTestSkipDelays(e.target.checked)}
              />
              <span style={{ fontSize: 13, color: "#444" }}>Pular delays ⏱ (recomendado)</span>
            </label>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button
                onClick={() => setShowTestModal(false)}
                style={{ height: 34, padding: "0 14px", borderRadius: 7, border: "1px solid #e0dbd4", background: "#fff", color: "#555", fontFamily: "'Outfit', sans-serif", fontSize: 13, cursor: "pointer" }}
              >
                Cancelar
              </button>
              <button
                onClick={startTest}
                disabled={!testPhone.trim()}
                style={{ height: 34, padding: "0 16px", borderRadius: 7, border: "none", background: testPhone.trim() ? "#111" : "#ccc", color: "#fff", fontFamily: "'Outfit', sans-serif", fontSize: 13, cursor: testPhone.trim() ? "pointer" : "default" }}
              >
                ▶ Executar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Public export (wraps with ReactFlowProvider) ─────────────────────────────
export function CadenceFlowBuilder({ campaignId }: { campaignId: string }) {
  return (
    <ReactFlowProvider>
      <FlowBuilderInner campaignId={campaignId} />
    </ReactFlowProvider>
  );
}

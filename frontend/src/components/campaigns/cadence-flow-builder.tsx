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
.react-flow__edge:hover .edge-delete-btn { opacity: 1 !important; }
.react-flow__edge .edge-delete-btn { opacity: 0; transition: opacity .15s; }
`;

// ─── Design constants ──────────────────────────────────────────────────────────
const NODE_W = 220;

const NODE_META: Record<CampaignNodeType, { label: string; kicker: string; icon: string; color: string; iconBg: string }> = {
  trigger:   { label: "Gatilho",         kicker: "GATILHO",  icon: "⚡", color: "#1a1a1a", iconBg: "rgba(26,26,26,.07)" },
  send:      { label: "Enviar template", kicker: "ENVIAR",   icon: "📨", color: "#E85D26", iconBg: "rgba(232,93,38,.1)" },
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
    case "trigger":   return { trigger_type: subtype || "no_message", days: 30 };
    case "send":      return { template_name: "", template_language: "pt_BR", template_variables: {}, on_reply: "pause" };
    case "wait":      return { days: 3, send_start_hour: 7, send_end_hour: 18 };
    case "condition": return { condition_type: subtype || "replied_recently", days: 5 };
    case "action":    return { action_type: subtype || "move_stage", stage_id: "" };
    case "end":       return { label: "Concluído", final_actions: [] };
    default:          return {};
  }
}

const TRIGGER_LABELS: Record<string, string> = {
  no_message: "Sem mensagem", stage_stagnation: "Estagnação", stage_enter: "Entrada em stage", post_broadcast: "Pós-disparo",
};
const ACTION_LABELS: Record<string, string> = {
  move_stage: "Mover stage", activate_agent: "Ativar agente", deactivate_agent: "Desativar agente", add_tag: "Adicionar tag",
};

// Ícones por subtype — os nós no canvas mostram o ícone do subtipo, não o genérico
const TRIGGER_ICONS: Record<string, string> = {
  stage_enter: "⚡", stage_stagnation: "🕐", no_message: "💤", post_broadcast: "📡",
};
const ACTION_ICONS: Record<string, string> = {
  move_stage: "📋", activate_agent: "🤖", deactivate_agent: "🤖", add_tag: "🏷️",
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

  return (
    <>
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
            pointerEvents: "all",
          }}
          className="nodrag nopan edge-delete-btn"
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
    </>
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
        top: "100%",
        left: "50%",
        transform: "translateX(-50%)",
        paddingTop: 8,
        zIndex: 20,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 4,
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
              top: 32,
              left: "50%",
              transform: "translateX(-50%)",
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
        boxShadow: "0 1px 3px rgba(0,0,0,.07), 0 4px 14px rgba(0,0,0,.08)",
        border: "1px solid rgba(0,0,0,.06)",
        fontFamily: "'Outfit', sans-serif",
        overflow: "visible",
        position: "relative",
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
  { type: "send",      subtype: "",                 icon: "📨", label: "Enviar template" },
  { type: "wait",      subtype: "",                 icon: "⏱",  label: "Aguardar" },
  { type: "condition", subtype: "replied_recently", icon: "🔀", label: "Condição" },
  { type: "action",    subtype: "move_stage",       icon: "📋", label: "Ação CRM" },
  { type: "end",       subtype: "",                 icon: "🏁", label: "Encerrar" },
];

const PALETTE_TRIGGERS: PaletteItem[] = [
  { type: "trigger", subtype: "stage_enter",      icon: "⚡", label: "Entrada em stage", desc: "Lead entra em stage" },
  { type: "trigger", subtype: "stage_stagnation", icon: "🕐", label: "Estagnação",        desc: "Parado X dias" },
  { type: "trigger", subtype: "no_message",       icon: "💤", label: "Sem mensagem",      desc: "Silêncio X dias" },
  { type: "trigger", subtype: "post_broadcast",   icon: "📡", label: "Pós-disparo",       desc: "Após broadcast" },
];
const PALETTE_ACTIONS: PaletteItem[] = [
  { type: "send",      subtype: "",                icon: "📨", label: "Enviar template", desc: "Mensagem HSM Meta" },
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

// ─── Inspector ─────────────────────────────────────────────────────────────────
interface InspectorProps {
  node: CampaignNode;
  saving: boolean;
  onSave: (nodeId: string, config: Record<string, unknown>) => Promise<void>;
  onDelete: (nodeId: string) => Promise<void>;
  onClose: () => void;
}

function Inspector({ node, saving, onSave, onDelete, onClose }: InspectorProps) {
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
              <select style={{ ...input, appearance: "none" }} value={(c.trigger_type as string) ?? ""} onChange={e => set("trigger_type", e.target.value)}>
                <option value="no_message">Sem mensagem</option>
                <option value="stage_stagnation">Estagnação de stage</option>
                <option value="stage_enter">Entrou em stage</option>
                <option value="post_broadcast">Pós-disparo</option>
              </select>
            </div>
            {(c.trigger_type === "no_message" || c.trigger_type === "stage_stagnation") && (
              <div style={field}><label style={label}>Dias</label><input type="number" style={input} value={(c.days as number) ?? 0} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
            )}
            {(c.trigger_type === "stage_stagnation" || c.trigger_type === "stage_enter") && (
              <div style={field}><label style={label}>Filtro de stage</label><input type="text" style={input} value={(c.stage_filter as string) ?? ""} onChange={e => set("stage_filter", e.target.value)} placeholder="ex: Negociação" /></div>
            )}
          </>
        )}
        {node.type === "send" && (
          <>
            <div style={field}><label style={label}>Nome do template</label><input type="text" style={input} value={(c.template_name as string) ?? ""} onChange={e => set("template_name", e.target.value)} placeholder="ex: reativacao_30d" /></div>
            <div style={field}>
              <label style={label}>Ao responder</label>
              <select style={{ ...input, appearance: "none" }} value={(c.on_reply as string) ?? "pause"} onChange={e => set("on_reply", e.target.value)}>
                <option value="pause">Pausar campanha</option>
                <option value="cancel">Cancelar campanha</option>
                <option value="continue">Continuar campanha</option>
              </select>
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
              <select style={{ ...input, appearance: "none" }} value={(c.condition_type as string) ?? ""} onChange={e => set("condition_type", e.target.value)}>
                <option value="replied_recently">Respondeu recentemente</option>
                <option value="in_stage">Está em stage</option>
                <option value="has_deal">Tem deal ativo</option>
              </select>
            </div>
            {c.condition_type === "replied_recently" && (
              <div style={field}><label style={label}>Dias</label><input type="number" style={input} value={(c.days as number) ?? 5} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
            )}
          </>
        )}
        {node.type === "action" && (
          <div style={field}>
            <label style={label}>Tipo de ação</label>
            <select style={{ ...input, appearance: "none" }} value={(c.action_type as string) ?? ""} onChange={e => set("action_type", e.target.value)}>
              <option value="move_stage">Mover stage</option>
              <option value="activate_agent">Ativar agente</option>
              <option value="deactivate_agent">Desativar agente</option>
            </select>
          </div>
        )}
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

        {/* ── Inspector ─────────────────────────────────────────────── */}
        {selectedDbNode && (
          <Inspector
            key={selectedDbNode.id}
            node={selectedDbNode}
            saving={saving}
            onSave={saveNode}
            onDelete={deleteNode}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </div>
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

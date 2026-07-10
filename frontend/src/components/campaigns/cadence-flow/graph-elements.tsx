"use client";

import { useState, useRef, memo, DragEvent } from "react";
import {
  Handle,
  Position,
  NodeProps,
  EdgeProps,
  BaseEdge,
  getSmoothStepPath,
  EdgeLabelRenderer,
} from "@xyflow/react";
import { motion, AnimatePresence } from "framer-motion";
import type { CampaignNode, CampaignNodeType } from "@/lib/types";
import type { PaletteItem, TestNodeState } from "./types";
import { NODE_META, NODE_W, QUICK_ADD_ITEMS } from "./constants";
import { resolveNodeIcon, nodeDetail } from "./helpers";

// ─── Flow bridge (module-private, bypasses unreliable dataTransfer / node props in React Flow) ─
interface FlowHandlers {
  addNodeBelow: ((sourceId: string, type: CampaignNodeType, subtype: string) => void) | null;
  deleteEdge: ((edgeId: string) => void) | null;
  selectNode: ((nodeId: string) => void) | null;
}

const flowBridge: FlowHandlers & { dragPayload: PaletteItem | null } = {
  addNodeBelow: null,
  deleteEdge: null,
  selectNode: null,
  dragPayload: null,
};

export function setFlowHandlers(handlers: Partial<FlowHandlers>) {
  Object.assign(flowBridge, handlers);
}

export function setDragPayload(payload: PaletteItem | null) {
  flowBridge.dragPayload = payload;
}

export function takeDragPayload(): PaletteItem | null {
  const payload = flowBridge.dragPayload;
  flowBridge.dragPayload = null;
  return payload;
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
            onClick={(e) => { e.stopPropagation(); flowBridge.deleteEdge?.(id); }}
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

export const EDGE_TYPES = { deletable: DeletableEdge };

// ─── QuickAddButton — appears on hover below each non-end node ────────────────
function QuickAddButton({ nodeId }: { nodeId: string }) {
  const [open, setOpen] = useState(false);

  const handleAdd = (e: React.MouseEvent<HTMLButtonElement>, type: CampaignNodeType, subtype: string) => {
    e.stopPropagation();
    flowBridge.addNodeBelow?.(nodeId, type, subtype);
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
      onClick={(e) => { e.stopPropagation(); flowBridge.selectNode?.(node.id); }}
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
export const NODE_TYPES = { campaignNode: CampaignFlowNode };

export function PaletteItemComp({ item, onAdd }: { item: PaletteItem; onAdd: (item: PaletteItem) => void }) {
  const meta = NODE_META[item.type];
  const iconBg = meta.iconBg;

  const onDragStart = (e: DragEvent) => {
    setDragPayload(item);
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

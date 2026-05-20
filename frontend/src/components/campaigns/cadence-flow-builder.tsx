"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import type { Campaign, CampaignNode, CampaignNodeType } from "@/lib/types";

// ─── Fonts via style tag ───────────────────────────────────────────────────────
const FONT_STYLE = `
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
`;

// ─── Design constants ──────────────────────────────────────────────────────────
const NODE_W = 210;
const NODE_H = 90;

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
  draft:    { bg: "#f5f2ed", color: "#888",     border: "#e0dbd4" },
  active:   { bg: "#edfaf5", color: "#1A9B6C",  border: "#a7f0d4" },
  paused:   { bg: "#fff7ed", color: "#C4920C",  border: "#fde68a" },
  archived: { bg: "#f5f2ed", color: "#888",     border: "#e0dbd4" },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
function getDefaultConfig(type: CampaignNodeType): Record<string, unknown> {
  switch (type) {
    case "trigger":   return { trigger_type: "no_message", days: 30 };
    case "send":      return { template_name: "", template_language: "pt_BR", template_variables: {}, on_reply: "pause" };
    case "wait":      return { days: 3, send_start_hour: 7, send_end_hour: 18 };
    case "condition": return { condition_type: "replied_recently", days: 5 };
    case "action":    return { action_type: "move_stage", stage_id: "" };
    case "end":       return { label: "Concluído", final_actions: [] };
    default:          return {};
  }
}

function nodeDetail(node: CampaignNode): string {
  const c = node.config as Record<string, unknown>;
  switch (node.type) {
    case "trigger":   return (c.trigger_type as string) ?? "";
    case "send":      return (c.template_name as string) || "template não definido";
    case "wait":      return `${c.days ?? 1} dia(s)`;
    case "condition": return (c.condition_type as string) ?? "";
    case "action":    return (c.action_type as string) ?? "";
    case "end":       return (c.label as string) || "Encerrar";
    default:          return "";
  }
}

function buildEdges(nodes: CampaignNode[]) {
  const edges: { from: CampaignNode; to: CampaignNode; branch?: "yes" | "no" }[] = [];
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  for (const n of nodes) {
    if (n.next_node_id && byId[n.next_node_id]) edges.push({ from: n, to: byId[n.next_node_id] });
    if (n.yes_node_id  && byId[n.yes_node_id])  edges.push({ from: n, to: byId[n.yes_node_id],  branch: "yes" });
    if (n.no_node_id   && byId[n.no_node_id])   edges.push({ from: n, to: byId[n.no_node_id],   branch: "no" });
  }
  return edges;
}

function bezierPath(from: CampaignNode, to: CampaignNode, branch?: "yes" | "no"): string {
  let x1 = from.position_x + NODE_W / 2;
  if (branch === "yes") x1 = from.position_x + NODE_W * 0.27;
  if (branch === "no")  x1 = from.position_x + NODE_W * 0.73;
  const y1 = from.position_y + NODE_H;
  const x2 = to.position_x + NODE_W / 2;
  const y2 = to.position_y;
  const cy = (y1 + y2) / 2;
  return `M ${x1} ${y1} C ${x1} ${cy} ${x2} ${cy} ${x2} ${y2}`;
}

// ─── FlowNode sub-component ────────────────────────────────────────────────────
interface FlowNodeProps {
  node: CampaignNode;
  selected: boolean;
  onClick: (e: React.MouseEvent) => void;
  onAddClick: (e: React.MouseEvent, branch?: "yes" | "no") => void;
}

function FlowNode({ node, selected, onClick, onAddClick }: FlowNodeProps) {
  const meta = NODE_META[node.type];
  const isCondition = node.type === "condition";
  const isEnd = node.type === "end";

  const shadow = selected
    ? "0 0 0 2px #fff, 0 0 0 4px #E85D26, 0 8px 28px rgba(0,0,0,.14)"
    : "0 1px 3px rgba(0,0,0,.07), 0 4px 14px rgba(0,0,0,.08)";

  return (
    <div
      onClick={onClick}
      style={{
        position: "absolute",
        left: node.position_x,
        top: node.position_y,
        width: NODE_W,
        background: "#fff",
        borderRadius: 10,
        boxShadow: shadow,
        cursor: "pointer",
        border: selected ? "1px solid transparent" : "1px solid rgba(0,0,0,.06)",
        userSelect: "none",
        transition: "box-shadow .15s ease, transform .15s cubic-bezier(.2,0,.2,1)",
        fontFamily: "'Outfit', sans-serif",
      }}
    >
      {/* Top stripe */}
      <div style={{ height: 3, background: meta.color, borderRadius: "10px 10px 0 0" }} />

      {/* Body */}
      <div style={{ padding: "12px 14px 14px", display: "flex", alignItems: "flex-start", gap: 10 }}>
        {/* Icon */}
        <div style={{
          width: 34, height: 34, borderRadius: 8,
          background: meta.iconBg,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 16, flexShrink: 0, marginTop: 1,
        }}>
          {meta.icon}
        </div>

        {/* Text */}
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
          }}>
            {nodeDetail(node)}
          </div>
        </div>
      </div>

      {/* Port-in dot */}
      <div style={{
        position: "absolute", top: -5, left: "50%", marginLeft: -5,
        width: 10, height: 10, borderRadius: "50%",
        background: "#fff", border: `2px solid ${meta.color === "#1a1a1a" ? "#aaa" : meta.color}`,
      }} />

      {/* Port-out / YES / NO */}
      {!isEnd && (
        <>
          {isCondition ? (
            <>
              {/* YES port */}
              <button
                onClick={e => onAddClick(e, "yes")}
                title="Adicionar nó (SIM)"
                style={{
                  position: "absolute", bottom: -5, left: "27%", marginLeft: -5,
                  width: 10, height: 10, borderRadius: "50%",
                  background: "#fff", border: "2px solid #1A9B6C",
                  cursor: "pointer", padding: 0,
                }}
              />
              <div style={{
                position: "absolute", bottom: -20, left: "27%",
                transform: "translateX(-50%)",
                fontSize: 9, fontWeight: 700, letterSpacing: ".4px",
                textTransform: "uppercase", color: "#1A9B6C", pointerEvents: "none",
              }}>SIM</div>
              {/* NO port */}
              <button
                onClick={e => onAddClick(e, "no")}
                title="Adicionar nó (NÃO)"
                style={{
                  position: "absolute", bottom: -5, left: "73%", marginLeft: -5,
                  width: 10, height: 10, borderRadius: "50%",
                  background: "#fff", border: "2px solid #ef4444",
                  cursor: "pointer", padding: 0,
                }}
              />
              <div style={{
                position: "absolute", bottom: -20, left: "73%",
                transform: "translateX(-50%)",
                fontSize: 9, fontWeight: 700, letterSpacing: ".4px",
                textTransform: "uppercase", color: "#ef4444", pointerEvents: "none",
              }}>NÃO</div>
            </>
          ) : (
            /* Default port-out */
            <button
              onClick={onAddClick}
              title="Adicionar próximo nó"
              style={{
                position: "absolute", bottom: -5, left: "50%", marginLeft: -5,
                width: 10, height: 10, borderRadius: "50%",
                background: "#fff", border: `2px solid ${meta.color === "#1a1a1a" ? "#aaa" : meta.color}`,
                cursor: "pointer", padding: 0,
              }}
            />
          )}
        </>
      )}
    </div>
  );
}

// ─── AddNodeMenu sub-component ─────────────────────────────────────────────────
interface AddNodeMenuProps {
  x: number;
  y: number;
  onSelect: (type: CampaignNodeType) => void;
}

const ADD_NODE_OPTIONS: { type: CampaignNodeType; icon: string; label: string; desc: string }[] = [
  { type: "send",      icon: "📨", label: "Enviar template", desc: "Mensagem HSM Meta" },
  { type: "wait",      icon: "⏱", label: "Aguardar",        desc: "Delay em dias" },
  { type: "condition", icon: "🔀", label: "Condição",        desc: "Ramificação lógica" },
  { type: "action",    icon: "📋", label: "Ação",            desc: "Mover stage / agente" },
  { type: "end",       icon: "🏁", label: "Encerrar",        desc: "Fim da campanha" },
];

function AddNodeMenu({ x, y, onSelect }: AddNodeMenuProps) {
  return (
    <div
      onClick={e => e.stopPropagation()}
      style={{
        position: "absolute",
        left: x,
        top: y + 20,
        width: 200,
        background: "#fff",
        borderRadius: 10,
        boxShadow: "0 4px 24px rgba(0,0,0,.14), 0 1px 4px rgba(0,0,0,.08)",
        border: "1px solid #e8e4df",
        overflow: "hidden",
        zIndex: 50,
        fontFamily: "'Outfit', sans-serif",
      }}
    >
      <div style={{ padding: "8px 12px 4px", fontSize: 9, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: "#b8b2aa" }}>
        Adicionar nó
      </div>
      {ADD_NODE_OPTIONS.map(opt => {
        const color = NODE_META[opt.type].color;
        const iconBg = NODE_META[opt.type].iconBg;
        return (
          <button
            key={opt.type}
            onClick={() => onSelect(opt.type)}
            style={{
              display: "flex", alignItems: "center", gap: 9,
              width: "100%", padding: "7px 12px",
              background: "transparent", border: "none", cursor: "pointer",
              textAlign: "left", transition: "background .1s",
            }}
            onMouseEnter={e => (e.currentTarget.style.background = "#f5f2ed")}
            onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
          >
            <div style={{
              width: 26, height: 26, borderRadius: 6,
              background: iconBg,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 13, flexShrink: 0,
            }}>
              {opt.icon}
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: color === "#1a1a1a" ? "#111" : color, lineHeight: 1.2 }}>
                {opt.label}
              </div>
              <div style={{ fontSize: 10, color: "#9b9590", marginTop: 1 }}>
                {opt.desc}
              </div>
            </div>
          </button>
        );
      })}
      <div style={{ height: 6 }} />
    </div>
  );
}

// ─── Inspector sub-component ───────────────────────────────────────────────────
interface InspectorProps {
  node: CampaignNode;
  saving: boolean;
  onSave: (nodeId: string, config: Record<string, unknown>) => Promise<void>;
  onDelete: (nodeId: string) => Promise<void>;
  onClose: () => void;
}

function Inspector({ node, saving, onSave, onDelete, onClose }: InspectorProps) {
  const [draftConfig, setDraftConfig] = useState<Record<string, unknown>>(node.config);
  const meta = NODE_META[node.type];

  // Reset draft when node changes
  useEffect(() => {
    setDraftConfig(node.config);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.id]);

  const set = (key: string, value: unknown) =>
    setDraftConfig(prev => ({ ...prev, [key]: value }));

  const fieldStyle: React.CSSProperties = {
    marginBottom: 14,
  };
  const labelStyle: React.CSSProperties = {
    display: "block",
    fontSize: 10, fontWeight: 700, letterSpacing: ".5px",
    textTransform: "uppercase", color: "#b0a8a0", marginBottom: 5,
  };
  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "8px 11px",
    border: "1px solid #e0dbd4", borderRadius: 7,
    fontFamily: "'Outfit', sans-serif", fontSize: 13, color: "#111",
    background: "#faf9f6", outline: "none",
  };
  const selectStyle: React.CSSProperties = { ...inputStyle, appearance: "none" as const };

  const c = draftConfig as Record<string, unknown>;

  return (
    <div style={{
      width: 256, flexShrink: 0,
      background: "#fff",
      borderLeft: "1px solid #e8e4df",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
      fontFamily: "'Outfit', sans-serif",
    }}>
      {/* Header */}
      <div style={{
        padding: "14px 16px 12px",
        borderBottom: "1px solid #ede9e3",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <div style={{
          width: 30, height: 30, borderRadius: 7,
          background: meta.iconBg,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 15,
        }}>
          {meta.icon}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#111" }}>{meta.label}</div>
          <div style={{ fontSize: 11, color: "#9b9590", marginTop: 1 }}>{meta.kicker}</div>
        </div>
        <button
          onClick={onClose}
          style={{
            width: 24, height: 24, borderRadius: 6,
            border: "1px solid #e0dbd4", background: "#faf9f6",
            cursor: "pointer", fontSize: 13, color: "#888",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
        >
          ✕
        </button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>

        {/* TRIGGER */}
        {node.type === "trigger" && (
          <>
            <div style={fieldStyle}>
              <label style={labelStyle}>Tipo de gatilho</label>
              <select style={selectStyle} value={(c.trigger_type as string) ?? ""} onChange={e => set("trigger_type", e.target.value)}>
                <option value="no_message">Sem mensagem</option>
                <option value="stage_stagnation">Estagnação de stage</option>
                <option value="stage_enter">Entrou em stage</option>
                <option value="post_broadcast">Pós-disparo</option>
              </select>
            </div>
            {(c.trigger_type === "no_message" || c.trigger_type === "stage_stagnation") && (
              <div style={fieldStyle}>
                <label style={labelStyle}>Dias</label>
                <input type="number" style={inputStyle} value={(c.days as number) ?? 0} onChange={e => set("days", Number(e.target.value))} min={1} />
              </div>
            )}
            {(c.trigger_type === "stage_stagnation" || c.trigger_type === "stage_enter") && (
              <div style={fieldStyle}>
                <label style={labelStyle}>Filtro de stage</label>
                <input type="text" style={inputStyle} value={(c.stage_filter as string) ?? ""} onChange={e => set("stage_filter", e.target.value)} placeholder="ex: Negociação" />
              </div>
            )}
          </>
        )}

        {/* SEND */}
        {node.type === "send" && (
          <>
            <div style={fieldStyle}>
              <label style={labelStyle}>Nome do template</label>
              <input type="text" style={inputStyle} value={(c.template_name as string) ?? ""} onChange={e => set("template_name", e.target.value)} placeholder="ex: reativacao_30d" />
            </div>
            <div style={fieldStyle}>
              <label style={labelStyle}>Ao responder</label>
              <select style={selectStyle} value={(c.on_reply as string) ?? "pause"} onChange={e => set("on_reply", e.target.value)}>
                <option value="pause">Pausar campanha</option>
                <option value="cancel">Cancelar campanha</option>
                <option value="continue">Continuar campanha</option>
              </select>
            </div>
          </>
        )}

        {/* WAIT */}
        {node.type === "wait" && (
          <div style={fieldStyle}>
            <label style={labelStyle}>Dias de espera</label>
            <input type="number" style={inputStyle} value={(c.days as number) ?? 1} onChange={e => set("days", Number(e.target.value))} min={1} />
          </div>
        )}

        {/* CONDITION */}
        {node.type === "condition" && (
          <>
            <div style={fieldStyle}>
              <label style={labelStyle}>Condição</label>
              <select style={selectStyle} value={(c.condition_type as string) ?? ""} onChange={e => set("condition_type", e.target.value)}>
                <option value="replied_recently">Respondeu recentemente</option>
                <option value="in_stage">Está em stage</option>
                <option value="has_deal">Tem deal ativo</option>
              </select>
            </div>
            {c.condition_type === "replied_recently" && (
              <div style={fieldStyle}>
                <label style={labelStyle}>Dias</label>
                <input type="number" style={inputStyle} value={(c.days as number) ?? 5} onChange={e => set("days", Number(e.target.value))} min={1} />
              </div>
            )}
          </>
        )}

        {/* ACTION */}
        {node.type === "action" && (
          <div style={fieldStyle}>
            <label style={labelStyle}>Tipo de ação</label>
            <select style={selectStyle} value={(c.action_type as string) ?? ""} onChange={e => set("action_type", e.target.value)}>
              <option value="move_stage">Mover stage</option>
              <option value="activate_agent">Ativar agente</option>
              <option value="deactivate_agent">Desativar agente</option>
            </select>
          </div>
        )}

        {/* END */}
        {node.type === "end" && (
          <div style={fieldStyle}>
            <label style={labelStyle}>Rótulo final</label>
            <input type="text" style={inputStyle} value={(c.label as string) ?? ""} onChange={e => set("label", e.target.value)} placeholder="ex: Concluído" />
          </div>
        )}

      </div>

      {/* Footer */}
      <div style={{ padding: "12px 16px", borderTop: "1px solid #ede9e3", display: "flex", gap: 6 }}>
        <button
          onClick={() => onSave(node.id, draftConfig)}
          disabled={saving}
          style={{
            flex: 1, height: 34, borderRadius: 7,
            background: "#111", color: "#fff",
            border: "none", cursor: saving ? "not-allowed" : "pointer",
            fontFamily: "'Outfit', sans-serif", fontSize: 12, fontWeight: 500,
            opacity: saving ? 0.7 : 1,
          }}
        >
          {saving ? "Salvando…" : "Salvar"}
        </button>
        <button
          onClick={() => onDelete(node.id)}
          style={{
            flex: 1, height: 34, borderRadius: 7,
            background: "#fff5f5", border: "1px solid #fecaca", color: "#dc2626",
            cursor: "pointer",
            fontFamily: "'Outfit', sans-serif", fontSize: 12, fontWeight: 500,
          }}
        >
          Remover
        </button>
      </div>
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────
interface CadenceFlowBuilderProps {
  campaignId: string;
}

export function CadenceFlowBuilder({ campaignId }: CadenceFlowBuilderProps) {
  const router = useRouter();

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [nodes, setNodes] = useState<CampaignNode[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [addNodeMenu, setAddNodeMenu] = useState<{ afterNodeId: string; x: number; y: number; branch?: "yes" | "no" } | null>(null);

  // Load campaign + nodes
  useEffect(() => {
    fetch(`/api/campaigns/${campaignId}`)
      .then(r => r.json())
      .then(data => {
        setCampaign(data);
        setNodes(data.nodes ?? []);
      });
  }, [campaignId]);

  // ── API actions ──────────────────────────────────────────────────────────────
  const addNode = async (afterNodeId: string, type: CampaignNodeType, posX: number, posY: number, branch?: "yes" | "no") => {
    const res = await fetch(`/api/campaigns/${campaignId}/nodes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, config: getDefaultConfig(type), position_x: posX, position_y: posY }),
    });
    if (!res.ok) return;
    const newNode: CampaignNode = await res.json();
    const linkField = branch === "yes" ? "yes_node_id" : branch === "no" ? "no_node_id" : "next_node_id";
    // Link afterNode.[linkField] → newNode.id
    await fetch(`/api/campaigns/${campaignId}/nodes/${afterNodeId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [linkField]: newNode.id }),
    });
    setNodes(prev => [
      ...prev.map(n => n.id === afterNodeId ? { ...n, [linkField]: newNode.id } : n),
      newNode,
    ]);
    setAddNodeMenu(null);
  };

  const saveNode = async (nodeId: string, config: Record<string, unknown>) => {
    setSaving(true);
    await fetch(`/api/campaigns/${campaignId}/nodes/${nodeId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    });
    setNodes(prev => prev.map(n => n.id === nodeId ? { ...n, config } : n));
    setSaving(false);
  };

  const deleteNode = async (nodeId: string) => {
    await fetch(`/api/campaigns/${campaignId}/nodes/${nodeId}`, { method: "DELETE" });
    setNodes(prev =>
      prev.filter(n => n.id !== nodeId).map(n => ({
        ...n,
        next_node_id: n.next_node_id === nodeId ? null : n.next_node_id,
        yes_node_id:  n.yes_node_id  === nodeId ? null : n.yes_node_id,
        no_node_id:   n.no_node_id   === nodeId ? null : n.no_node_id,
      }))
    );
    if (selectedNodeId === nodeId) setSelectedNodeId(null);
  };

  const toggleActivation = async () => {
    if (!campaign) return;
    const endpoint = campaign.status === "active" ? "pause" : "activate";
    const res = await fetch(`/api/campaigns/${campaignId}/${endpoint}`, { method: "POST" });
    const data = await res.json();
    if (data.error) { alert(data.error); return; }
    setCampaign(prev => prev ? { ...prev, status: data.status } : prev);
  };

  // ── Derived ──────────────────────────────────────────────────────────────────
  const selectedNode = selectedNodeId ? nodes.find(n => n.id === selectedNodeId) ?? null : null;
  const edges = buildEdges(nodes);

  const statusStyle = STATUS_COLORS[campaign?.status ?? "draft"];

  // ── Palette items ────────────────────────────────────────────────────────────
  const paletteItems = [
    { section: "Gatilhos", items: [
      { icon: "⚡", name: "Stage move",    desc: "Lead entra em stage" },
      { icon: "🕐", name: "Estagnação",    desc: "Parado X dias" },
      { icon: "💤", name: "Sem mensagem",  desc: "Silêncio X dias" },
      { icon: "📡", name: "Pós-disparo",   desc: "Após broadcast" },
    ]},
    { section: "Ações", items: [
      { icon: "📨", name: "Enviar template", desc: "Mensagem HSM Meta",  bg: "rgba(232,93,38,.1)" },
      { icon: "⏱", name: "Aguardar",        desc: "Delay em dias",       bg: "rgba(59,125,216,.1)" },
      { icon: "🔀", name: "Condição",        desc: "Ramificação lógica",  bg: "rgba(196,146,12,.1)" },
      { icon: "📋", name: "Mover stage",     desc: "Kanban move",         bg: "rgba(124,77,184,.1)" },
      { icon: "🤖", name: "Ativar agente",   desc: "Assign ValerIA",      bg: "rgba(124,77,184,.1)" },
      { icon: "🏁", name: "Encerrar",        desc: "Fim da campanha",     bg: "rgba(26,155,108,.1)" },
    ]},
  ];

  return (
    <>
      {/* Google Fonts */}
      <style>{FONT_STYLE}</style>

      <div style={{ display: "flex", flexDirection: "column", height: "100vh", fontFamily: "'Outfit', sans-serif" }}>

        {/* ── TOPBAR ─────────────────────────────────────────────────────────── */}
        <div style={{
          display: "flex", alignItems: "center", gap: 14,
          background: "#fff", borderBottom: "1px solid #e8e4df",
          padding: "0 20px", height: 52, flexShrink: 0, zIndex: 100,
        }}>
          <button
            onClick={() => router.push("/campanhas?tab=cadencias")}
            style={{
              width: 30, height: 30, borderRadius: 7,
              border: "1px solid #e8e4df", background: "transparent",
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", color: "#555", fontSize: 14,
            }}
          >
            ←
          </button>

          <span style={{ fontSize: 14, fontWeight: 600, color: "#111", letterSpacing: "-.2px" }}>
            {campaign?.name ?? "…"}
          </span>

          {campaign && (
            <span style={{
              padding: "3px 9px", borderRadius: 5,
              background: statusStyle.bg, border: `1px solid ${statusStyle.border}`,
              fontSize: 11, fontWeight: 500, color: statusStyle.color,
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
              background: campaign?.status === "active" ? "#fff7ed" : "#111",
              color: campaign?.status === "active" ? "#C4920C" : "#fff",
              border: campaign?.status === "active" ? "1px solid #fde68a" : "none",
              cursor: "pointer",
              fontFamily: "'Outfit', sans-serif", fontSize: 13, fontWeight: 500,
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            {campaign?.status === "active" ? "⏸ Pausar" : "▶ Ativar campanha"}
          </button>
        </div>

        {/* ── WORKSPACE ──────────────────────────────────────────────────────── */}
        <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

          {/* ── PALETTE ──────────────────────────────────────────────────────── */}
          <div style={{
            width: 196, flexShrink: 0,
            background: "#fff", borderRight: "1px solid #e8e4df",
            padding: "16px 12px", overflowY: "auto",
            display: "flex", flexDirection: "column", gap: 18,
          }}>
            {paletteItems.map(section => (
              <div key={section.section}>
                <div style={{
                  fontSize: 9, fontWeight: 700, letterSpacing: "1px",
                  textTransform: "uppercase", color: "#b8b2aa",
                  padding: "0 4px", marginBottom: 8,
                }}>
                  {section.section}
                </div>
                {section.items.map(item => (
                  <div
                    key={item.name}
                    style={{
                      display: "flex", alignItems: "center", gap: 9,
                      padding: "8px 10px", borderRadius: 8,
                      border: "1px solid #ede9e3", marginBottom: 5,
                      cursor: "default", background: "#faf9f6",
                    }}
                  >
                    <div style={{
                      width: 28, height: 28, borderRadius: 7,
                      background: (item as { bg?: string }).bg ?? "rgba(26,26,26,.07)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 14, flexShrink: 0,
                    }}>
                      {item.icon}
                    </div>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#1a1a1a", lineHeight: 1.2 }}>{item.name}</div>
                      <div style={{ fontSize: 10, color: "#9b9590", marginTop: 1 }}>{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>

          {/* ── CANVAS ───────────────────────────────────────────────────────── */}
          <div
            style={{
              flex: 1, overflow: "auto",
              background: "#f5f2ed",
              backgroundImage: "radial-gradient(circle, rgba(0,0,0,.1) 1px, transparent 1px)",
              backgroundSize: "22px 22px",
              position: "relative",
            }}
            onClick={() => { setSelectedNodeId(null); setAddNodeMenu(null); }}
          >
            <div style={{ position: "relative", width: 1280, height: 960 }}>

              {/* SVG edges */}
              <svg style={{
                position: "absolute", top: 0, left: 0,
                width: "100%", height: "100%",
                pointerEvents: "none", overflow: "visible",
              }}>
                {edges.map((edge, i) => (
                  <path
                    key={i}
                    d={bezierPath(edge.from, edge.to, edge.branch)}
                    stroke={edge.branch === "yes" ? "#1A9B6C" : edge.branch === "no" ? "#ef4444" : "#c8c2bb"}
                    strokeWidth={1.5}
                    fill="none"
                    strokeLinecap="round"
                  />
                ))}
              </svg>

              {/* Nodes */}
              {nodes.map(node => (
                <FlowNode
                  key={node.id}
                  node={node}
                  selected={selectedNodeId === node.id}
                  onClick={e => { e.stopPropagation(); setSelectedNodeId(node.id); setAddNodeMenu(null); }}
                  onAddClick={(e, branch) => {
                    e.stopPropagation();
                    setAddNodeMenu({ afterNodeId: node.id, x: node.position_x, y: node.position_y + 120, branch });
                  }}
                />
              ))}

              {/* Add node dropdown */}
              {addNodeMenu && (
                <AddNodeMenu
                  x={addNodeMenu.x}
                  y={addNodeMenu.y}
                  onSelect={type => addNode(addNodeMenu.afterNodeId, type, addNodeMenu.x, addNodeMenu.y + 140, addNodeMenu.branch)}
                />
              )}

              {/* Empty state */}
              {nodes.length === 0 && (
                <div style={{
                  position: "absolute", top: "50%", left: "50%",
                  transform: "translate(-50%, -50%)",
                  textAlign: "center", pointerEvents: "none",
                }}>
                  <div style={{ fontSize: 40, marginBottom: 12 }}>⚡</div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: "#555", marginBottom: 4 }}>
                    Nenhum nó no fluxo
                  </div>
                  <div style={{ fontSize: 13, color: "#9b9590" }}>
                    Os nós aparecerão aqui quando criados via API
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* ── INSPECTOR ────────────────────────────────────────────────────── */}
          {selectedNode && (
            <Inspector
              key={selectedNode.id}
              node={selectedNode}
              saving={saving}
              onSave={saveNode}
              onDelete={deleteNode}
              onClose={() => setSelectedNodeId(null)}
            />
          )}
        </div>
      </div>
    </>
  );
}

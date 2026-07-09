"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { createClient } from "@/lib/supabase/client";

// ─── Types ─────────────────────────────────────────────────────────────────────
interface ExecutionLogRow {
  id: string;
  enrollment_id: string;
  campaign_id: string;
  lead_id: string | null;
  node_id: string | null;
  node_type: string | null;
  status: "done" | "failed" | "skipped";
  log: string | null;
  created_at: string;
}

interface Props {
  campaignId: string;
}

// ─── Design constants — mirrors cadence-flow-builder palette ──────────────────
const STATUS_CONFIG: Record<string, { label: string; dot: string; bg: string; border: string; text: string }> = {
  done:    { label: "OK",      dot: "#1A9B6C", bg: "#edfaf5", border: "#a7f0d4", text: "#14633d" },
  failed:  { label: "FALHOU",  dot: "#ef4444", bg: "#fff5f5", border: "#fecaca", text: "#dc2626" },
  skipped: { label: "PULADO",  dot: "#C4920C", bg: "#fff9ed", border: "#fde68a", text: "#92400e" },
};

const NODE_TYPE_ICONS: Record<string, string> = {
  trigger:   "⚡",
  send:      "📨",
  send_text: "💬",
  wait:      "⏱",
  condition: "🔀",
  action:    "📋",
  end:       "🏁",
};

const NODE_TYPE_LABELS: Record<string, string> = {
  trigger:   "Gatilho",
  send:      "Enviar template",
  send_text: "Enviar texto",
  wait:      "Aguardar",
  condition: "Condição",
  action:    "Ação",
  end:       "Encerrar",
};

// ─── Relative-time helper ──────────────────────────────────────────────────────
function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diffMs / 1000);
  if (s < 60) return `${s}s atrás`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m atrás`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h atrás`;
  const d = Math.floor(h / 24);
  return `${d}d atrás`;
}

// ─── Single log entry ─────────────────────────────────────────────────────────
function LogEntry({ row, isNew }: { row: ExecutionLogRow; isNew: boolean }) {
  const cfg = STATUS_CONFIG[row.status] ?? STATUS_CONFIG.done;
  const icon = NODE_TYPE_ICONS[row.node_type ?? ""] ?? "◆";
  const typeLabel = NODE_TYPE_LABELS[row.node_type ?? ""] ?? (row.node_type ?? "nó");

  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        padding: "9px 12px",
        borderBottom: "1px solid #f0ede8",
        background: isNew ? "rgba(26,155,108,.04)" : "transparent",
        transition: "background 1.2s ease",
        alignItems: "flex-start",
      }}
    >
      {/* Timeline dot + line */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0, paddingTop: 3 }}>
        <div style={{
          width: 8, height: 8, borderRadius: "50%",
          background: cfg.dot,
          boxShadow: `0 0 0 2px ${cfg.border}`,
          flexShrink: 0,
        }} />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Top row: icon + type + status badge + timestamp */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12 }}>{icon}</span>
          <span style={{
            fontFamily: "'Outfit', sans-serif",
            fontSize: 11, fontWeight: 600, color: "#333",
            letterSpacing: "-.1px",
          }}>
            {typeLabel}
          </span>
          <span style={{
            display: "inline-flex", alignItems: "center",
            padding: "1px 6px", borderRadius: 4,
            background: cfg.bg, border: `1px solid ${cfg.border}`,
            fontSize: 9, fontWeight: 700, letterSpacing: ".7px",
            textTransform: "uppercase", color: cfg.text,
          }}>
            {cfg.label}
          </span>
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 9, color: "#b0a8a0", marginLeft: "auto",
            whiteSpace: "nowrap",
          }}>
            {relativeTime(row.created_at)}
          </span>
        </div>

        {/* Log text */}
        {row.log && (
          <div style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10, color: row.status === "failed" ? "#dc2626" : "#7b7570",
            marginTop: 3, lineHeight: 1.5,
            wordBreak: "break-word",
            whiteSpace: "pre-wrap",
          }}>
            {row.log}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────
export function CadenceExecutionLog({ campaignId }: Props) {
  const [rows, setRows] = useState<ExecutionLogRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  const newIdTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // Flash a row as "new" for 2 s then remove the highlight
  const markNew = useCallback((id: string) => {
    setNewIds(prev => new Set([...prev, id]));
    const t = setTimeout(() => {
      setNewIds(prev => { const next = new Set(prev); next.delete(id); return next; });
      newIdTimers.current.delete(id);
    }, 2000);
    newIdTimers.current.set(id, t);
  }, []);

  // Clear timers on unmount
  useEffect(() => {
    const timers = newIdTimers.current;
    return () => { timers.forEach(clearTimeout); };
  }, []);

  const fetchRows = useCallback(async () => {
    const res = await fetch(`/api/campaigns/${campaignId}/execution-log?limit=50`);
    if (res.ok) {
      const json = await res.json();
      setRows(json.data ?? []);
    }
    setLoading(false);
  }, [campaignId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchRows();

    const supabase = createClient();
    const channel = supabase
      .channel(`exec-log-${campaignId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "campaign_execution_log",
          filter: `campaign_id=eq.${campaignId}`,
        },
        (payload) => {
          const newRow = payload.new as ExecutionLogRow;
          setRows(prev => [newRow, ...prev].slice(0, 50));
          markNew(newRow.id);
          // Auto-expand on first realtime event so the user notices activity
          setOpen(true);
        }
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [campaignId, fetchRows, markNew]);

  // ── Counts for summary badge ───────────────────────────────────────────────
  const countDone    = rows.filter(r => r.status === "done").length;
  const countFailed  = rows.filter(r => r.status === "failed").length;
  const countSkipped = rows.filter(r => r.status === "skipped").length;

  return (
    <div style={{
      borderTop: "1px solid #e8e4df",
      background: "#fff",
      flexShrink: 0,
      fontFamily: "'Outfit', sans-serif",
    }}>
      {/* ── Toggle header ──────────────────────────────────────────────────── */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 16px",
          border: "none",
          background: "transparent",
          cursor: "pointer",
          textAlign: "left",
          borderBottom: open ? "1px solid #e8e4df" : "none",
        }}
        title={open ? "Ocultar log de execução" : "Ver log de execução"}
      >
        <span style={{ fontSize: 12 }}>📋</span>
        <span style={{
          fontSize: 11, fontWeight: 700, letterSpacing: ".6px",
          textTransform: "uppercase", color: "#7b7570",
        }}>
          Log de Execução
        </span>

        {/* Summary pills */}
        {rows.length > 0 && (
          <div style={{ display: "flex", gap: 5, marginLeft: 4 }}>
            {countDone > 0 && (
              <span style={{
                padding: "1px 7px", borderRadius: 4,
                background: "#edfaf5", border: "1px solid #a7f0d4",
                fontSize: 9, fontWeight: 700, color: "#14633d", letterSpacing: ".4px",
              }}>
                {countDone} OK
              </span>
            )}
            {countFailed > 0 && (
              <span style={{
                padding: "1px 7px", borderRadius: 4,
                background: "#fff5f5", border: "1px solid #fecaca",
                fontSize: 9, fontWeight: 700, color: "#dc2626", letterSpacing: ".4px",
              }}>
                {countFailed} FALHA
              </span>
            )}
            {countSkipped > 0 && (
              <span style={{
                padding: "1px 7px", borderRadius: 4,
                background: "#fff9ed", border: "1px solid #fde68a",
                fontSize: 9, fontWeight: 700, color: "#92400e", letterSpacing: ".4px",
              }}>
                {countSkipped} PULADO
              </span>
            )}
          </div>
        )}

        <div style={{ flex: 1 }} />

        {/* Realtime indicator dot */}
        <div style={{
          width: 6, height: 6, borderRadius: "50%",
          background: "#1A9B6C",
          boxShadow: "0 0 0 2px rgba(26,155,108,.2)",
          flexShrink: 0,
        }} title="Realtime ativo" />

        <span style={{ fontSize: 10, color: "#b0a8a0", marginLeft: 2 }}>
          {open ? "▲" : "▼"}
        </span>
      </button>

      {/* ── Log list ───────────────────────────────────────────────────────── */}
      {open && (
        <div style={{
          height: 220,
          overflowY: "auto",
          background: "#faf9f7",
        }}>
          {loading ? (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              height: "100%", fontSize: 12, color: "#9b9590",
            }}>
              Carregando log...
            </div>
          ) : rows.length === 0 ? (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", height: "100%",
              gap: 6,
            }}>
              <span style={{ fontSize: 22 }}>📋</span>
              <span style={{ fontSize: 12, color: "#9b9590" }}>
                Nenhuma execução registrada ainda
              </span>
              <span style={{ fontSize: 10, color: "#b0a8a0" }}>
                As entradas aparecem em tempo real quando a cadência processa leads
              </span>
            </div>
          ) : (
            <div>
              {rows.map(row => (
                <LogEntry
                  key={row.id}
                  row={row}
                  isNew={newIds.has(row.id)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

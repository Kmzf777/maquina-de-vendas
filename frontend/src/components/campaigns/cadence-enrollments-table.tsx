"use client";

import { useState, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";
import type { CadenceEnrollment } from "@/lib/types";
import { ENROLLMENT_STATUS_COLORS, ENROLLMENT_STATUS_LABELS } from "@/lib/constants";

interface CadenceEnrollmentsTableProps {
  cadenceId: string;
}

export function CadenceEnrollmentsTable({ cadenceId }: CadenceEnrollmentsTableProps) {
  const [enrollments, setEnrollments] = useState<CadenceEnrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const fetchEnrollments = async () => {
    const res = await fetch(`/api/cadences/${cadenceId}/enrollments`);
    const data = await res.json();
    setEnrollments(data.data || data);
    setLoading(false);
  };

  useEffect(() => {
    fetchEnrollments();

    const supabase = createClient();
    const channel = supabase
      .channel(`enrollments-${cadenceId}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "cadence_enrollments", filter: `cadence_id=eq.${cadenceId}` }, () => fetchEnrollments())
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [cadenceId]);

  const handleAction = async (enrollId: string, action: string) => {
    if (action === "remove") {
      await fetch(`/api/cadences/${cadenceId}/enrollments/${enrollId}`, { method: "DELETE" });
    } else {
      await fetch(`/api/cadences/${cadenceId}/enrollments/${enrollId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
    }
    fetchEnrollments();
  };

  const filtered = enrollments.filter((e) => {
    if (filter !== "all" && e.status !== filter) return false;
    if (search) {
      const lead = e.leads;
      if (!lead) return false;
      const text = `${lead.name || ""} ${lead.phone} ${lead.company || ""}`.toLowerCase();
      if (!text.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const filters = ["all", "active", "responded", "exhausted", "completed"];

  if (loading) return <div className="py-8 text-center text-[#9ca3af] text-[13px]">Carregando...</div>;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Buscar lead..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 rounded-lg border border-[#e5e5dc] text-[13px] bg-white w-64"
        />
        <div className="flex gap-1">
          {filters.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${
                filter === f ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
              }`}
            >
              {f === "all" ? "Todos" : ENROLLMENT_STATUS_LABELS[f] || f}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[13px] text-[#9ca3af] text-center py-8">Nenhum lead nesta cadencia</p>
      ) : (
        <div className="bg-white rounded-xl border border-[#e5e5dc] overflow-hidden">
          <div className="grid grid-cols-[1fr_100px_80px_120px_100px] gap-2 px-4 py-2 bg-[#f4f4f0] text-[11px] text-[#9ca3af] uppercase tracking-wider font-medium">
            <span>Lead</span>
            <span>Status</span>
            <span>Step</span>
            <span>Proximo envio</span>
            <span>Acoes</span>
          </div>

          {filtered.map((e) => {
            const lead = e.leads;
            const colors = ENROLLMENT_STATUS_COLORS[e.status] || ENROLLMENT_STATUS_COLORS.active;
            return (
              <div key={e.id} className="grid grid-cols-[1fr_100px_80px_120px_100px] gap-2 px-4 py-3 border-t border-[#e5e5dc] items-center">
                <div>
                  <p className="text-[13px] font-medium text-[#1f1f1f]">{lead?.name || lead?.phone || "—"}</p>
                  {lead?.name && <p className="text-[11px] text-[#5f6368]">{lead.phone}</p>}
                </div>
                <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium ${colors.bg} ${colors.text}`}>
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: colors.dot }} />
                  {ENROLLMENT_STATUS_LABELS[e.status] || e.status}
                </span>
                <span className="text-[13px] text-[#1f1f1f]">{e.current_step}/{e.total_messages_sent}</span>
                <span className="text-[12px] text-[#5f6368]">
                  {e.next_send_at ? new Date(e.next_send_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}
                </span>
                <div className="flex gap-1">
                  {e.status === "active" && (
                    <button onClick={() => handleAction(e.id, "pause")} className="text-[11px] text-[#8a7a2a] font-medium">Pausar</button>
                  )}
                  {(e.status === "paused" || e.status === "responded") && (
                    <button onClick={() => handleAction(e.id, "resume")} className="text-[11px] text-[#2d6a3f] font-medium">Retomar</button>
                  )}
                  <button onClick={() => handleAction(e.id, "remove")} className="text-[11px] text-[#a33] font-medium">Remover</button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

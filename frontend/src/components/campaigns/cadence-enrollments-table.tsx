"use client";

import { useState, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";
import type { CadenceEnrollment } from "@/lib/types";
import { ENROLLMENT_STATUS_LABELS } from "@/lib/constants";

interface CadenceEnrollmentsTableProps {
  cadenceId: string;
}

const STATUS_BADGE: Record<string, string> = {
  active: "bg-[#0bdf50]/10 text-[#0bdf50] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#0bdf50]/20",
  responded: "bg-[#0bdf50]/10 text-[#0bdf50] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#0bdf50]/20",
  exhausted: "bg-[#c41c1c]/10 text-[#c41c1c] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#c41c1c]/20",
  completed: "bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]",
  paused: "bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]",
};

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

  if (loading) return <div className="py-8 text-center text-[#7b7b78] text-[14px]">Carregando...</div>;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Buscar lead..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-64"
        />
        <div className="flex gap-1">
          {filters.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={filter === f
                ? "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                : "bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"}
            >
              {f === "all" ? "Todos" : ENROLLMENT_STATUS_LABELS[f] || f}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[14px] text-[#7b7b78] text-center py-8">Nenhum lead nesta cadencia</p>
      ) : (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#dedbd6]">
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Lead</th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal w-28">Status</th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal w-20">Step</th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal w-36">Proximo envio</th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal w-28">Acoes</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => {
                const lead = e.leads;
                return (
                  <tr key={e.id} className="border-b border-[#dedbd6] hover:bg-[#faf9f6]">
                    <td className="px-4 py-3">
                      <p className="text-[14px] text-[#111111]">{lead?.name || lead?.phone || "—"}</p>
                      {lead?.name && <p className="text-[11px] text-[#7b7b78]">{lead.phone}</p>}
                    </td>
                    <td className="px-4 py-3">
                      <span className={STATUS_BADGE[e.status] || STATUS_BADGE.paused}>
                        {ENROLLMENT_STATUS_LABELS[e.status] || e.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[14px] text-[#111111]">{e.current_step}/{e.total_messages_sent}</td>
                    <td className="px-4 py-3 text-[14px] text-[#7b7b78]">
                      {e.next_send_at ? new Date(e.next_send_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        {e.status === "active" && (
                          <button onClick={() => handleAction(e.id, "pause")} className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px] hover:text-[#111111] transition-colors">Pausar</button>
                        )}
                        {(e.status === "paused" || e.status === "responded") && (
                          <button onClick={() => handleAction(e.id, "resume")} className="text-[11px] text-[#0bdf50] uppercase tracking-[0.6px]">Retomar</button>
                        )}
                        <button onClick={() => handleAction(e.id, "remove")} className="text-[11px] text-[#c41c1c] uppercase tracking-[0.6px]">Remover</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

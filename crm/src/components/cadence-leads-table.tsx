"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import type { CadenceState, Lead } from "@/lib/types";
import { CADENCE_STATUS_COLORS, CADENCE_STATUS_LABELS, AGENT_STAGES } from "@/lib/constants";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

interface CadenceLeadsTableProps {
  campaignId: string;
}

type StatusFilter = "active" | "responded" | "exhausted" | "cooled" | "all";

interface CadenceRow extends CadenceState {
  leads: Lead;
}

export function CadenceLeadsTable({ campaignId }: CadenceLeadsTableProps) {
  const [rows, setRows] = useState<CadenceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("active");
  const [search, setSearch] = useState("");
  const router = useRouter();
  const supabase = createClient();

  const fetchCadenceStates = useCallback(async () => {
    const query = supabase
      .from("cadence_state")
      .select("*, leads(*)")
      .eq("campaign_id", campaignId)
      .order("created_at", { ascending: false });

    const { data } = await query;
    if (data) setRows(data as CadenceRow[]);
    setLoading(false);
  }, [campaignId]);

  useEffect(() => {
    fetchCadenceStates();

    const channel = supabase
      .channel(`cadence-${campaignId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "cadence_state", filter: `campaign_id=eq.${campaignId}` },
        () => fetchCadenceStates()
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [fetchCadenceStates, campaignId]);

  const filtered = rows.filter((r) => {
    if (filter !== "all" && r.status !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      const lead = r.leads;
      if (!lead) return false;
      return (
        (lead.name || "").toLowerCase().includes(q) ||
        (lead.company || "").toLowerCase().includes(q) ||
        lead.phone.includes(q)
      );
    }
    return true;
  });

  async function handlePause(leadId: string) {
    await fetch(`${FASTAPI_URL}/api/leads/${leadId}/cadence/pause`, { method: "POST" });
  }

  async function handleReset(leadId: string) {
    await fetch(`${FASTAPI_URL}/api/leads/${leadId}/cadence`, { method: "DELETE" });
  }

  async function handleHuman(leadId: string) {
    await fetch(`${FASTAPI_URL}/api/leads/${leadId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ human_control: true }),
    });
  }

  function goToConversation(phone: string) {
    router.push(`/conversas?phone=${encodeURIComponent(phone)}`);
  }

  const filters: { key: StatusFilter; label: string }[] = [
    { key: "active", label: "Leads ativos" },
    { key: "responded", label: "Responderam" },
    { key: "exhausted", label: "Esgotados" },
    { key: "cooled", label: "Esfriados" },
    { key: "all", label: "Todos" },
  ];

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-8">
        <div className="w-4 h-4 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
        <span className="text-[13px] text-[#5f6368]">Carregando leads...</span>
      </div>
    );
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex items-center gap-2 mb-4">
        {filters.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3.5 py-1.5 rounded-lg text-[12px] font-medium transition-colors ${
              filter === f.key
                ? "bg-[#1f1f1f] text-white"
                : "bg-[#f4f4f0] text-[#5f6368] hover:bg-[#e5e5dc]"
            }`}
          >
            {f.label}
          </button>
        ))}
        <div className="ml-auto">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar nome, empresa, telefone..."
            className="input-field text-[13px] w-64"
          />
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left border-b border-[#e5e5dc]">
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Lead</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Stage</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Status</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Progresso</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Proximo Envio</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => {
              const lead = r.leads;
              if (!lead) return null;
              const stageInfo = AGENT_STAGES.find((s) => s.key === lead.stage);
              const statusStyle = CADENCE_STATUS_COLORS[r.status];
              const progressText = `${r.total_messages_sent}/${r.max_messages}`;
              const progressPct = r.max_messages > 0 ? (r.total_messages_sent / r.max_messages) * 100 : 0;

              return (
                <tr key={r.id} className="border-b border-[#e5e5dc] last:border-0 hover:bg-[#f6f7ed]/50 transition-colors">
                  <td className="px-5 py-4">
                    <p className="font-medium text-[#1f1f1f]">{lead.name || lead.phone}</p>
                    <p className="text-[11px] text-[#9ca3af]">{lead.phone}</p>
                  </td>
                  <td className="px-5 py-4">
                    {stageInfo && (
                      <span
                        className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium ${stageInfo.color}`}
                      >
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: stageInfo.dotColor }} />
                        {stageInfo.label}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-4">
                    {statusStyle && (
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium ${statusStyle.bg} ${statusStyle.text}`}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: statusStyle.dot }} />
                        {CADENCE_STATUS_LABELS[r.status]}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-16 bg-[#e5e5dc] rounded-full h-1.5">
                        <div className="bg-[#1f1f1f] rounded-full h-1.5 transition-all" style={{ width: `${Math.min(100, progressPct)}%` }} />
                      </div>
                      <span className="text-[11px] text-[#9ca3af]">{progressText}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4 text-[12px] text-[#5f6368]">
                    {r.status === "responded"
                      ? "Com a Valeria"
                      : r.next_send_at
                        ? new Date(r.next_send_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
                        : "\u2014"}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-1.5">
                      {r.status === "active" && (
                        <button onClick={() => handlePause(lead.id)} className="text-[11px] font-medium text-[#5f6368] bg-[#f4f4f0] hover:bg-[#e5e5dc] px-2.5 py-1 rounded-md transition-colors">
                          Pausar
                        </button>
                      )}
                      {(r.status === "exhausted" || r.status === "cooled") && (
                        <button onClick={() => handleReset(lead.id)} className="text-[11px] font-medium text-[#5f6368] bg-[#f4f4f0] hover:bg-[#e5e5dc] px-2.5 py-1 rounded-md transition-colors">
                          Resetar
                        </button>
                      )}
                      <button onClick={() => goToConversation(lead.phone)} className="text-[11px] font-medium text-[#5f6368] bg-[#f4f4f0] hover:bg-[#e5e5dc] px-2.5 py-1 rounded-md transition-colors">
                        Conversa
                      </button>
                      {(r.status === "active" || r.status === "responded") && (
                        <button onClick={() => handleHuman(lead.id)} className="text-[11px] font-medium text-[#5f6368] bg-[#f4f4f0] hover:bg-[#e5e5dc] px-2.5 py-1 rounded-md transition-colors">
                          Humano
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center text-[13px] text-[#9ca3af]">
                  Nenhum lead encontrado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

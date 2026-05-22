"use client";

import { useState, useEffect, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { CampaignEnrollment } from "@/lib/types";

interface CampaignEnrollmentsTableProps {
  campaignId: string;
}

const STATUS_LABELS: Record<string, { style: string; label: string }> = {
  active:    { style: "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20", label: "Ativo" },
  paused:    { style: "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20", label: "Pausado" },
  completed: { style: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20", label: "Completo" },
  failed:    { style: "bg-[#c41c1c]/10 text-[#c41c1c] border-[#c41c1c]/20", label: "Falhou" },
  removed:   { style: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]", label: "Removido" },
  cancelled: { style: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]", label: "Cancelado" },
};

function StatusBadge({ status }: { status: string }) {
  const entry = STATUS_LABELS[status] ?? STATUS_LABELS.active;
  return (
    <span className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border ${entry.style}`}>
      {entry.label}
    </span>
  );
}

export function CampaignEnrollmentsTable({ campaignId }: CampaignEnrollmentsTableProps) {
  const [enrollments, setEnrollments] = useState<CampaignEnrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const fetchEnrollments = useCallback(async () => {
    const res = await fetch(`/api/campaigns/${campaignId}/enrollments`);
    if (res.ok) {
      const json = await res.json();
      // Route returns either flat array or { data: [...] }
      const arr = Array.isArray(json) ? json : (json.data ?? []);
      setEnrollments(arr);
    }
    setLoading(false);
  }, [campaignId]);

  useEffect(() => {
    fetchEnrollments();

    const supabase = createClient();
    const channel = supabase
      .channel(`campaign-enrollments-${campaignId}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "campaign_enrollments",
          filter: `campaign_id=eq.${campaignId}`,
        },
        () => fetchEnrollments()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [campaignId, fetchEnrollments]);

  const handleAction = async (
    enrollId: string,
    action: "pause" | "resume" | "remove"
  ) => {
    if (action === "remove") {
      await fetch(`/api/campaigns/${campaignId}/enrollments/${enrollId}`, {
        method: "DELETE",
      });
    } else {
      await fetch(`/api/campaigns/${campaignId}/enrollments/${enrollId}`, {
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
      const text =
        `${lead.name ?? ""} ${lead.phone} ${lead.company ?? ""}`.toLowerCase();
      if (!text.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const filters = ["all", "active", "paused", "completed", "failed"];

  if (loading)
    return (
      <div className="py-8 text-center text-[#7b7b78] text-[14px]">
        Carregando...
      </div>
    );

  return (
    <div>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
        <div className="p-4 border-b border-[#dedbd6] bg-[#f7f5f1] flex gap-3 items-center">
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
                className={
                  filter === f
                    ? "bg-[#111111] text-white px-3 py-1.5 rounded-[4px] text-[13px]"
                    : "border border-[#dedbd6] text-[#7b7b78] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] hover:text-[#111111]"
                }
              >
                {f === "all" ? "Todos" : STATUS_LABELS[f]?.label ?? f}
              </button>
            ))}
          </div>
        </div>

        {filtered.length === 0 ? (
          <p className="text-[14px] text-[#7b7b78] text-center py-8">
            Nenhum lead nesta cadência
          </p>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#dedbd6] bg-[#f7f5f1]">
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">
                  Lead
                </th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">
                  Status
                </th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">
                  Nó atual
                </th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">
                  Próxima execução
                </th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">
                  Ações
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr
                  key={e.id}
                  className="border-b border-[#dedbd6] hover:bg-[#faf9f6] transition-colors"
                >
                  <td className="px-4 py-3">
                    <p className="text-[14px] font-medium text-[#111111]">
                      {e.leads?.name ?? "—"}
                    </p>
                    <p className="text-[12px] text-[#7b7b78]">{e.leads?.phone}</p>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={e.status} />
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-[13px] text-[#111111]">
                      {e.current_node?.type ?? "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-[13px] text-[#7b7b78]">
                      {e.next_execute_at
                        ? new Date(e.next_execute_at).toLocaleString("pt-BR", {
                            day: "2-digit",
                            month: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      {e.status === "active" && (
                        <button
                          onClick={() => handleAction(e.id, "pause")}
                          className="text-[13px] text-[#7b7b78] hover:text-[#111111] transition-colors"
                        >
                          Pausar
                        </button>
                      )}
                      {e.status === "paused" && (
                        <button
                          onClick={() => handleAction(e.id, "resume")}
                          className="text-[13px] text-[#0bdf50] hover:text-[#0bdf50]/70 transition-colors"
                        >
                          Retomar
                        </button>
                      )}
                      <button
                        onClick={() => handleAction(e.id, "remove")}
                        className="text-[13px] text-[#c41c1c] hover:text-[#c41c1c]/70 transition-colors"
                      >
                        Remover
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// Backward-compat alias so any consumer using the old name still compiles
export { CampaignEnrollmentsTable as CadenceEnrollmentsTable };

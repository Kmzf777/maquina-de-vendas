"use client";

import { useState, useEffect } from "react";
import { LeadBroadcastHistory } from "@/components/leads/lead-broadcast-history";
import { ENROLLMENT_STATUS_COLORS, ENROLLMENT_STATUS_LABELS } from "@/lib/constants";

interface Enrollment {
  campaign_name: string;
  campaign_created_at: string;
  status: string;
  enrolled_at: string;
  next_execute_at: string | null;
  completed_at: string | null;
}

interface CrmCampanhasTabProps {
  leadId: string;
}

export function CrmCampanhasTab({ leadId }: CrmCampanhasTabProps) {
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    import("@/lib/supabase/client").then(({ createClient }) => {
      const supabase = createClient();
      supabase
        .from("campaign_enrollments")
        .select("*, campaigns(id, name, created_at)")
        .eq("lead_id", leadId)
        .order("enrolled_at", { ascending: false })
        .then(({ data }) => {
          if (data) {
            setEnrollments(
              data.map((ce: Record<string, unknown>) => {
                const camp = ce.campaigns as { id: string; name: string; created_at: string } | null;
                return {
                  campaign_name: camp?.name || "Campanha",
                  campaign_created_at: camp?.created_at || "",
                  status: ce.status as string,
                  enrolled_at: ce.enrolled_at as string,
                  next_execute_at: ce.next_execute_at as string | null,
                  completed_at: ce.completed_at as string | null,
                };
              })
            );
          }
          setLoading(false);
        });
    });
  }, [leadId]);

  return (
    <div className="p-4 space-y-4">
      <div>
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">
          Cadências ({enrollments.length})
        </p>
        {loading ? (
          <div className="space-y-2">
            {[0, 1].map((i) => (
              <div key={i} className="h-20 rounded-[8px] bg-[#f0ede8] animate-pulse" />
            ))}
          </div>
        ) : enrollments.length === 0 ? (
          <p className="text-[13px] text-[#7b7b78] text-center py-4">Nenhuma campanha encontrada.</p>
        ) : (
          <div className="space-y-3">
            {enrollments.map((c, i) => {
              const sc = ENROLLMENT_STATUS_COLORS[c.status] || ENROLLMENT_STATUS_COLORS.active;
              const label = ENROLLMENT_STATUS_LABELS[c.status] || c.status;
              return (
                <div key={i} className="border border-[#dedbd6] rounded-[8px] p-4">
                  <div className="flex justify-between items-center mb-2.5">
                    <div>
                      <p className="text-[14px] font-medium text-[#111111]">{c.campaign_name}</p>
                      {c.enrolled_at && (
                        <p className="text-[12px] text-[#7b7b78]">
                          Iniciada em {new Date(c.enrolled_at).toLocaleDateString("pt-BR")}
                        </p>
                      )}
                    </div>
                    <span
                      className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-[4px] ${sc.bg} ${sc.text}`}
                    >
                      {label}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2.5">
                    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2">
                      <p className="text-[10px] text-[#7b7b78] uppercase tracking-[0.6px]">Próximo envio</p>
                      <p className="text-[13px] font-medium text-[#111111]">
                        {c.next_execute_at ? new Date(c.next_execute_at).toLocaleDateString("pt-BR") : "—"}
                      </p>
                    </div>
                    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2">
                      <p className="text-[10px] text-[#7b7b78] uppercase tracking-[0.6px]">Concluída em</p>
                      <p className="text-[13px] font-medium text-[#111111]">
                        {c.completed_at ? new Date(c.completed_at).toLocaleDateString("pt-BR") : "—"}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="border-t border-[#dedbd6] pt-4">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Disparos Recebidos</p>
        <LeadBroadcastHistory leadId={leadId} />
      </div>
    </div>
  );
}

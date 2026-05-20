"use client";

import { useState, useEffect } from "react";
import { LeadBroadcastHistory } from "@/components/leads/lead-broadcast-history";
import { ENROLLMENT_STATUS_COLORS, ENROLLMENT_STATUS_LABELS } from "@/lib/constants";

interface Enrollment {
  cadence_name: string;
  cadence_created_at: string;
  status: string;
  current_step: number;
  max_messages: number;
  total_messages_sent: number;
  next_send_at: string | null;
  responded_at: string | null;
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
        .from("cadence_enrollments")
        .select("*, cadences(name, created_at, max_messages)")
        .eq("lead_id", leadId)
        .then(({ data }) => {
          if (data) {
            setEnrollments(
              data.map((ce: Record<string, unknown>) => {
                const cad = ce.cadences as { name: string; created_at: string; max_messages: number } | null;
                return {
                  cadence_name: cad?.name || "Cadência",
                  cadence_created_at: cad?.created_at || "",
                  status: ce.status as string,
                  current_step: ce.current_step as number,
                  max_messages: cad?.max_messages ?? 0,
                  total_messages_sent: ce.total_messages_sent as number,
                  next_send_at: ce.next_send_at as string | null,
                  responded_at: ce.responded_at as string | null,
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
          Cadencias ({enrollments.length})
        </p>
        {loading ? (
          <div className="space-y-2">
            {[0, 1].map((i) => (
              <div key={i} className="h-20 rounded-[8px] bg-[#f0ede8] animate-pulse" />
            ))}
          </div>
        ) : enrollments.length === 0 ? (
          <p className="text-[13px] text-[#7b7b78] text-center py-4">Nenhuma cadência encontrada.</p>
        ) : (
          <div className="space-y-3">
            {enrollments.map((c, i) => {
              const sc = ENROLLMENT_STATUS_COLORS[c.status] || ENROLLMENT_STATUS_COLORS.active;
              const label = ENROLLMENT_STATUS_LABELS[c.status] || c.status;
              return (
                <div key={i} className="border border-[#dedbd6] rounded-[8px] p-4">
                  <div className="flex justify-between items-center mb-2.5">
                    <div>
                      <p className="text-[14px] font-medium text-[#111111]">{c.cadence_name}</p>
                      {c.cadence_created_at && (
                        <p className="text-[12px] text-[#7b7b78]">
                          Criada em {new Date(c.cadence_created_at).toLocaleDateString("pt-BR")}
                        </p>
                      )}
                    </div>
                    <span
                      className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-[4px] ${sc.bg} ${sc.text}`}
                    >
                      {label}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2.5">
                    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2">
                      <p className="text-[10px] text-[#7b7b78] uppercase tracking-[0.6px]">Cadencia</p>
                      <p className="text-[13px] font-medium text-[#111111]">Step {c.current_step} de {c.max_messages}</p>
                    </div>
                    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2">
                      <p className="text-[10px] text-[#7b7b78] uppercase tracking-[0.6px]">Mensagens</p>
                      <p className="text-[13px] font-medium text-[#111111]">{c.total_messages_sent} enviadas</p>
                    </div>
                    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2">
                      <p className="text-[10px] text-[#7b7b78] uppercase tracking-[0.6px]">
                        {c.responded_at ? "Respondeu em" : "Proximo envio"}
                      </p>
                      <p className="text-[13px] font-medium text-[#111111]">
                        {c.responded_at
                          ? new Date(c.responded_at).toLocaleDateString("pt-BR")
                          : c.next_send_at
                            ? new Date(c.next_send_at).toLocaleDateString("pt-BR")
                            : "—"}
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

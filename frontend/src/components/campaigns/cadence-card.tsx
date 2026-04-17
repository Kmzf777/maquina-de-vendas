"use client";

import type { Cadence } from "@/lib/types";
import { AGENT_STAGES, DEAL_STAGES } from "@/lib/constants";
import { useRouter } from "next/navigation";

interface CadenceCardProps {
  cadence: Cadence;
  enrollmentCounts?: { active: number; responded: number; exhausted: number; completed: number };
  stepsCount?: number;
}

export function CadenceCard({ cadence: c, enrollmentCounts, stepsCount }: CadenceCardProps) {
  const router = useRouter();
  const counts = enrollmentCounts || { active: 0, responded: 0, exhausted: 0, completed: 0 };

  const statusStyles: Record<string, string> = {
    active: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
    paused: "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20",
    archived: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
  };
  const statusLabels: Record<string, string> = { active: "Ativa", paused: "Pausada", archived: "Arquivada" };

  const allStages = [...AGENT_STAGES, ...DEAL_STAGES];
  const stageName = c.target_stage
    ? allStages.find((s) => s.key === c.target_stage)?.label || c.target_stage
    : null;

  let triggerLabel = "Manual";
  if (c.target_type === "lead_stage" && stageName) {
    triggerLabel = `Lead → ${stageName}`;
  } else if (c.target_type === "deal_stage" && stageName) {
    triggerLabel = `Deal → ${stageName}`;
  }

  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 flex flex-col gap-4 hover:border-[#111111]/30 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <span className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border mb-2 ${statusStyles[c.status] ?? statusStyles.active}`}>
            {statusLabels[c.status] ?? c.status}
          </span>
          <h3 className="text-[15px] font-medium text-[#111111] truncate">{c.name}</h3>
          <p className="text-[12px] text-[#7b7b78] mt-0.5">
            {triggerLabel} · {stepsCount ?? 0} steps · Janela {c.send_start_hour}h–{c.send_end_hour}h
          </p>
        </div>
      </div>

      {/* Enrollment stats */}
      <div className="grid grid-cols-4 gap-2 border-t border-[#dedbd6] pt-4">
        {[
          { label: "Ativos", value: counts.active, color: counts.active > 0 ? "#ff5600" : "#111111" },
          { label: "Respond.", value: counts.responded, color: "#0bdf50" },
          { label: "Esgotado", value: counts.exhausted, color: "#fe4c02" },
          { label: "Completo", value: counts.completed, color: "#65b5ff" },
        ].map(({ label, value, color }) => (
          <div key={label} className="flex flex-col">
            <span className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78]">{label}</span>
            <span className="text-[20px] font-normal leading-tight mt-0.5" style={{ color, letterSpacing: "-0.3px" }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-[#dedbd6] pt-3">
        <span className="text-[12px] text-[#7b7b78]">
          Cooldown {c.cooldown_hours}h · Max {c.max_messages} msgs
        </span>
        <button
          onClick={() => router.push(`/campanhas/${c.id}`)}
          className="text-[13px] text-[#111111] hover:underline transition-colors"
        >
          Ver Detalhes →
        </button>
      </div>
    </div>
  );
}

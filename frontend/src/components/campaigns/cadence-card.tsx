"use client";

import type { Cadence } from "@/lib/types";
import { AGENT_STAGES, DEAL_STAGES, CADENCE_TARGET_LABELS } from "@/lib/constants";
import { useRouter } from "next/navigation";

interface CadenceCardProps {
  cadence: Cadence;
  enrollmentCounts?: { active: number; responded: number; exhausted: number; completed: number };
  stepsCount?: number;
}

export function CadenceCard({ cadence: c, enrollmentCounts, stepsCount }: CadenceCardProps) {
  const router = useRouter();
  const counts = enrollmentCounts || { active: 0, responded: 0, exhausted: 0, completed: 0 };

  const allStages = [...AGENT_STAGES, ...DEAL_STAGES];
  const stageName = c.target_stage
    ? allStages.find((s) => s.key === c.target_stage)?.label || c.target_stage
    : null;

  let triggerText = "Manual";
  if (c.target_type !== "manual" && stageName) {
    triggerText = c.stagnation_days
      ? `Apos ${c.stagnation_days} dias em ${stageName}`
      : `Quando entra em ${stageName}`;
  }

  return (
    <div
      className="card p-4 cursor-pointer hover:shadow-md transition-shadow"
      onClick={() => router.push(`/campanhas/${c.id}`)}
    >
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-[14px] font-semibold text-[#1f1f1f] truncate">{c.name}</h4>
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
          c.status === "active" ? "bg-[#d8f0dc] text-[#2d6a3f]" :
          c.status === "paused" ? "bg-[#f0ecd0] text-[#8a7a2a]" :
          "bg-[#f4f4f0] text-[#5f6368]"
        }`}>
          {c.status === "active" ? "Ativa" : c.status === "paused" ? "Pausada" : "Arquivada"}
        </span>
      </div>

      <div className="flex items-center gap-2 mb-3">
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-[#f6f7ed] text-[#5f6368] font-medium">
          {CADENCE_TARGET_LABELS[c.target_type]}
        </span>
        <span className="text-[12px] text-[#5f6368]">{triggerText}</span>
      </div>

      {c.description && (
        <p className="text-[12px] text-[#5f6368] mb-3 line-clamp-2">{c.description}</p>
      )}

      <div className="grid grid-cols-4 gap-2 text-center mb-3">
        <div>
          <p className="text-[14px] font-bold text-[#92400e]">{counts.active}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Ativos</p>
        </div>
        <div>
          <p className="text-[14px] font-bold text-[#2d6a3f]">{counts.responded}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Responderam</p>
        </div>
        <div>
          <p className="text-[14px] font-bold text-[#991b1b]">{counts.exhausted}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Esgotados</p>
        </div>
        <div>
          <p className="text-[14px] font-bold text-[#2a5a8a]">{counts.completed}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Completaram</p>
        </div>
      </div>

      <div className="flex items-center gap-3 text-[11px] text-[#5f6368]">
        {stepsCount !== undefined && <span>{stepsCount} steps</span>}
        <span>Janela: {c.send_start_hour}h-{c.send_end_hour}h</span>
        <span>Max: {c.max_messages} msgs</span>
      </div>
    </div>
  );
}

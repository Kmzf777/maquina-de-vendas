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

  const statusBadge = c.status === "active"
    ? "bg-[#0bdf50]/10 text-[#0bdf50] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#0bdf50]/20"
    : "bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]";

  const statusLabel = c.status === "active" ? "Ativa" : c.status === "paused" ? "Pausada" : "Arquivada";

  return (
    <div
      className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 cursor-pointer transition-colors hover:border-[#111111]"
      onClick={() => router.push(`/campanhas/${c.id}`)}
    >
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-[14px] font-normal text-[#111111] truncate">{c.name}</h4>
        <span className={statusBadge}>{statusLabel}</span>
      </div>

      <div className="flex items-center gap-2 mb-3">
        <span className="bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]">
          {CADENCE_TARGET_LABELS[c.target_type]}
        </span>
        <span className="text-[12px] text-[#7b7b78]">{triggerText}</span>
      </div>

      {c.description && (
        <p className="text-[12px] text-[#7b7b78] mb-3 line-clamp-2">{c.description}</p>
      )}

      <div className="grid grid-cols-4 gap-2 text-center mb-3">
        <div>
          <p className="text-[14px] font-normal text-[#111111]">{counts.active}</p>
          <p className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Ativos</p>
        </div>
        <div>
          <p className="text-[14px] font-normal text-[#0bdf50]">{counts.responded}</p>
          <p className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Responderam</p>
        </div>
        <div>
          <p className="text-[14px] font-normal text-[#c41c1c]">{counts.exhausted}</p>
          <p className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Esgotados</p>
        </div>
        <div>
          <p className="text-[14px] font-normal text-[#111111]">{counts.completed}</p>
          <p className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Completaram</p>
        </div>
      </div>

      <div className="flex items-center gap-3 text-[11px] text-[#7b7b78]">
        {stepsCount !== undefined && <span>{stepsCount} steps</span>}
        <span>Janela: {c.send_start_hour}h-{c.send_end_hour}h</span>
        <span>Max: {c.max_messages} msgs</span>
      </div>
    </div>
  );
}

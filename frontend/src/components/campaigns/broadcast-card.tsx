"use client";

import type { Broadcast } from "@/lib/types";

interface BroadcastCardProps {
  broadcast: Broadcast;
  onStart: () => void;
  onPause: () => void;
  onClick: () => void;
}

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]",
  running: "bg-[#0bdf50]/10 text-[#0bdf50] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#0bdf50]/20",
  paused: "bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]",
  completed: "bg-[#0bdf50]/10 text-[#0bdf50] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#0bdf50]/20",
  failed: "bg-[#c41c1c]/10 text-[#c41c1c] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#c41c1c]/20",
};

export function BroadcastCard({ broadcast: b, onStart, onPause, onClick }: BroadcastCardProps) {
  const pct = b.total_leads > 0 ? Math.round((b.sent / b.total_leads) * 100) : 0;

  return (
    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 cursor-pointer transition-colors hover:border-[#111111]" onClick={onClick}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[14px] font-normal text-[#111111] truncate">{b.name}</h4>
        <span className={STATUS_BADGE[b.status] || STATUS_BADGE.draft}>
          {b.status}
        </span>
      </div>

      <p className="text-[12px] text-[#7b7b78] mb-3">Template: {b.template_name}</p>

      <div className="w-full h-1.5 bg-[#dedbd6] rounded-full mb-3">
        <div className="h-full bg-[#0bdf50] rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>

      <div className="grid grid-cols-4 gap-2 text-center mb-3">
        <div>
          <p className="text-[16px] font-normal text-[#111111]">{b.total_leads}</p>
          <p className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Leads</p>
        </div>
        <div>
          <p className="text-[16px] font-normal text-[#0bdf50]">{b.sent}</p>
          <p className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Enviados</p>
        </div>
        <div>
          <p className="text-[16px] font-normal text-[#111111]">{b.delivered}</p>
          <p className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Entregues</p>
        </div>
        <div>
          <p className="text-[16px] font-normal text-[#c41c1c]">{b.failed}</p>
          <p className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Falhas</p>
        </div>
      </div>

      {b.cadences && (
        <p className="text-[11px] text-[#7b7b78] mb-2">
          Cadencia: <span className="font-normal text-[#111111]">{b.cadences.name}</span>
        </p>
      )}

      <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
        {b.status === "draft" && (
          <button onClick={onStart} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]">
            Iniciar
          </button>
        )}
        {b.status === "running" && (
          <button onClick={onPause} className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">
            Pausar
          </button>
        )}
        {b.status === "paused" && (
          <button onClick={onStart} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]">
            Retomar
          </button>
        )}
      </div>
    </div>
  );
}

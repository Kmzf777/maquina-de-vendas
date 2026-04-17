"use client";

import type { Broadcast } from "@/lib/types";

interface BroadcastCardProps {
  broadcast: Broadcast;
  onStart: () => void;
  onPause: () => void;
  onClick: () => void;
}

export function BroadcastCard({ broadcast, onStart, onPause, onClick }: BroadcastCardProps) {
  const pct = broadcast.total_leads > 0
    ? Math.round((broadcast.sent / broadcast.total_leads) * 100) : 0;

  const statusStyles: Record<string, string> = {
    draft: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
    running: "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20",
    paused: "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20",
    completed: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
    scheduled: "bg-[#65b5ff]/10 text-[#65b5ff] border-[#65b5ff]/20",
  };
  const statusLabels: Record<string, string> = {
    draft: "Rascunho", running: "Rodando", paused: "Pausado",
    completed: "Completo", scheduled: "Agendado",
  };
  const fillColor = broadcast.status === "completed" ? "#0bdf50"
    : broadcast.status === "running" ? "#ff5600"
    : broadcast.status === "paused" ? "#fe4c02" : "#dedbd6";

  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 flex flex-col gap-4 cursor-pointer" onClick={onClick}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <span className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border mb-2 ${statusStyles[broadcast.status] ?? statusStyles.draft}`}>
            {statusLabels[broadcast.status] ?? broadcast.status}
          </span>
          <h3 className="text-[15px] font-medium text-[#111111] truncate">{broadcast.name}</h3>
          <p className="text-[13px] text-[#7b7b78] mt-0.5 truncate">{broadcast.template_name}</p>
        </div>
      </div>

      {/* Progress */}
      <div>
        <div className="flex justify-between items-center mb-1.5">
          <span className="text-[12px] text-[#7b7b78]">{broadcast.sent} de {broadcast.total_leads} leads</span>
          <span className="text-[12px] font-medium text-[#111111]">{pct}%</span>
        </div>
        <div className="w-full h-1.5 bg-[#f0ede8] rounded-full overflow-hidden">
          <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: fillColor }} />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-4 gap-2 border-t border-[#dedbd6] pt-4">
        {[
          { label: "Enviados", value: broadcast.sent, color: "#111111" },
          { label: "Entregues", value: broadcast.delivered, color: "#0bdf50" },
          { label: "Falhou", value: broadcast.failed, color: "#c41c1c" },
          { label: "Total", value: broadcast.total_leads, color: "#111111" },
        ].map(({ label, value, color }) => (
          <div key={label} className="flex flex-col">
            <span className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78]">{label}</span>
            <span className="text-[20px] font-normal leading-tight mt-0.5" style={{ color, letterSpacing: '-0.3px' }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex justify-end gap-2 border-t border-[#dedbd6] pt-3" onClick={(e) => e.stopPropagation()}>
        {broadcast.status === "draft" && (
          <button onClick={onStart} className="bg-[#111111] text-white px-[14px] py-1.5 rounded-[4px] text-[13px] transition-transform hover:scale-110 active:scale-[0.85]">
            Iniciar
          </button>
        )}
        {broadcast.status === "running" && (
          <button onClick={onPause} className="border border-[#dedbd6] text-[#313130] px-[14px] py-1.5 rounded-[4px] text-[13px] transition-transform hover:scale-110 active:scale-[0.85]">
            Pausar
          </button>
        )}
        {broadcast.status === "paused" && (
          <button onClick={onStart} className="bg-[#111111] text-white px-[14px] py-1.5 rounded-[4px] text-[13px] transition-transform hover:scale-110 active:scale-[0.85]">
            Retomar
          </button>
        )}
      </div>
    </div>
  );
}

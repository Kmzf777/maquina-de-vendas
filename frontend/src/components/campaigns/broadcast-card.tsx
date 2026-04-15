"use client";

import type { Broadcast } from "@/lib/types";
import { BROADCAST_STATUS_COLORS } from "@/lib/constants";

interface BroadcastCardProps {
  broadcast: Broadcast;
  onStart: () => void;
  onPause: () => void;
  onClick: () => void;
}

export function BroadcastCard({ broadcast: b, onStart, onPause, onClick }: BroadcastCardProps) {
  const pct = b.total_leads > 0 ? Math.round((b.sent / b.total_leads) * 100) : 0;

  return (
    <div className="card p-4 cursor-pointer hover:shadow-md transition-shadow" onClick={onClick}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[14px] font-semibold text-[#1f1f1f] truncate">{b.name}</h4>
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${BROADCAST_STATUS_COLORS[b.status] || ""}`}>
          {b.status}
        </span>
      </div>

      <p className="text-[12px] text-[#5f6368] mb-3">Template: {b.template_name}</p>

      <div className="w-full h-1.5 bg-[#e5e5dc] rounded-full mb-3">
        <div className="h-full bg-[#c8cc8e] rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>

      <div className="grid grid-cols-4 gap-2 text-center mb-3">
        <div>
          <p className="text-[16px] font-bold text-[#1f1f1f]">{b.total_leads}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Leads</p>
        </div>
        <div>
          <p className="text-[16px] font-bold text-[#2d6a3f]">{b.sent}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Enviados</p>
        </div>
        <div>
          <p className="text-[16px] font-bold text-[#5b8aad]">{b.delivered}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Entregues</p>
        </div>
        <div>
          <p className="text-[16px] font-bold text-[#a33]">{b.failed}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Falhas</p>
        </div>
      </div>

      {b.cadences && (
        <p className="text-[11px] text-[#5f6368] mb-2">
          Cadencia: <span className="font-medium text-[#1f1f1f]">{b.cadences.name}</span>
        </p>
      )}

      <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
        {b.status === "draft" && (
          <button onClick={onStart} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333]">
            Iniciar
          </button>
        )}
        {b.status === "running" && (
          <button onClick={onPause} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#f0ecd0] text-[#8a7a2a] hover:bg-[#e5e0c0]">
            Pausar
          </button>
        )}
        {b.status === "paused" && (
          <button onClick={onStart} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#d8f0dc] text-[#2d6a3f] hover:bg-[#c0e8c4]">
            Retomar
          </button>
        )}
      </div>
    </div>
  );
}

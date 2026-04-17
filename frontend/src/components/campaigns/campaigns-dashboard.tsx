"use client";

import { useEffect, useState } from "react";
import { CampaignTrendChart } from "./campaign-trend-chart";

interface Stats {
  activeBroadcasts: number;
  activeCadences: number;
  leadsInFollowUp: number;
  responseRate: number;
  respondedCount: number;
  trend: { date: string; sent: number; responded: number }[];
}

interface CampaignsDashboardProps {
  period: string;
  onPeriodChange: (p: string) => void;
}

export function CampaignsDashboard({ period, onPeriodChange }: CampaignsDashboardProps) {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    fetch(`/api/campaigns/stats?period=${period}`)
      .then((r) => r.json())
      .then(setStats);
  }, [period]);

  if (!stats) {
    return (
      <div className="grid grid-cols-5 gap-4 mb-6">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="bg-white border border-[#dedbd6] rounded-[8px] p-5 h-28 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-5 mb-6">
      <div className="grid grid-cols-5 gap-4">
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Disparos Ativos</p>
          <p style={{ letterSpacing: '-1.5px' }} className="text-[48px] font-normal text-[#111111] leading-none">{stats.activeBroadcasts ?? 0}</p>
          <p className="text-[13px] text-[#7b7b78] mt-2">rodando agora</p>
        </div>
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Taxa de Resposta</p>
          <p style={{ letterSpacing: '-1.5px' }} className={`text-[48px] font-normal leading-none ${
            (stats.responseRate ?? 0) >= 30 ? "text-[#0bdf50]" :
            (stats.responseRate ?? 0) >= 10 ? "text-[#fe4c02]" : "text-[#c41c1c]"
          }`}>{stats.responseRate ?? 0}%</p>
          <p className="text-[13px] text-[#7b7b78] mt-2">de resposta</p>
        </div>
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Em Follow-up</p>
          <p style={{ letterSpacing: '-1.5px' }} className={`text-[48px] font-normal leading-none ${
            (stats.leadsInFollowUp ?? 0) > 0 ? "text-[#ff5600]" : "text-[#111111]"
          }`}>{stats.leadsInFollowUp ?? 0}</p>
          <p className="text-[13px] text-[#7b7b78] mt-2">leads ativos</p>
        </div>
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Cadências Ativas</p>
          <p style={{ letterSpacing: '-1.5px' }} className="text-[48px] font-normal text-[#111111] leading-none">{stats.activeCadences ?? 0}</p>
          <p className="text-[13px] text-[#7b7b78] mt-2">configuradas</p>
        </div>
        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Responderam</p>
          <p style={{ letterSpacing: '-1.5px' }} className="text-[48px] font-normal text-[#0bdf50] leading-none">{stats.respondedCount ?? 0}</p>
          <p className="text-[13px] text-[#7b7b78] mt-2">leads</p>
        </div>
      </div>

      <CampaignTrendChart data={stats.trend} period={period} onPeriodChange={onPeriodChange} />
    </div>
  );
}

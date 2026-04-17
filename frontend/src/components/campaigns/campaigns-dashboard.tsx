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
          <div key={i} className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 h-20 animate-pulse" />
        ))}
      </div>
    );
  }

  const kpis = [
    { label: "Disparos ativos", value: stats.activeBroadcasts },
    { label: "Cadencias ativas", value: stats.activeCadences },
    { label: "Leads em follow-up", value: stats.leadsInFollowUp },
    { label: "Taxa de resposta", value: `${stats.responseRate}%` },
    { label: "Responderam", value: stats.respondedCount },
  ];

  const periods = [
    { key: "7d", label: "7 dias" },
    { key: "30d", label: "30 dias" },
    { key: "90d", label: "90 dias" },
  ];

  return (
    <div className="space-y-5 mb-6">
      <div className="grid grid-cols-5 gap-4">
        {kpis.map((kpi) => (
          <div key={kpi.label} className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4">
            <p className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">{kpi.label}</p>
            <span className="text-[22px] font-normal text-[#111111] leading-none mt-1 block">{kpi.value}</span>
          </div>
        ))}
      </div>

      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Tendencia de respostas
          </h3>
          <div className="flex gap-1">
            {periods.map((p) => (
              <button
                key={p.key}
                onClick={() => onPeriodChange(p.key)}
                className={period === p.key
                  ? "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                  : "bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <CampaignTrendChart data={stats.trend} />
      </div>
    </div>
  );
}

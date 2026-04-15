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
          <div key={i} className="card p-4 h-20 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
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
          <div key={kpi.label} className="card p-4">
            <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">{kpi.label}</p>
            <span className="text-[22px] font-bold text-[#1f1f1f] leading-none mt-1 block">{kpi.value}</span>
          </div>
        ))}
      </div>

      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[13px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
            Tendencia de respostas
          </h3>
          <div className="flex gap-1">
            {periods.map((p) => (
              <button
                key={p.key}
                onClick={() => onPeriodChange(p.key)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${
                  period === p.key ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
                }`}
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

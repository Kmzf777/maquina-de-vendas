"use client";

import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { useRealtimeDeals } from "@/hooks/use-realtime-deals";
import { DEAL_STAGES } from "@/lib/constants";
import { KpiCard } from "@/components/kpi-card";
import { FunnelChart } from "@/components/funnel-chart";
import { LeadSourcesChart } from "@/components/dashboard/lead-sources-chart";
import { FunnelMovement } from "@/components/dashboard/funnel-movement";

const TrendUpIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M3 14l4-4 3 3 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M13 6h4v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const UsersIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="7.5" cy="7" r="2.5" stroke="currentColor" strokeWidth="1.8" />
    <path d="M2.5 16c0-2.5 2-4.5 5-4.5s5 2 5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    <circle cx="14" cy="7.5" r="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M14 11.5c2 0 3.5 1.2 3.5 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);
const CheckIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M5 10l3.5 3.5L15 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const XIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);
const ChatIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 14l-1 4 4-2c1.2.5 2.5.8 3.8.8 4.4 0 8-3 8-6.8S15.2 3 10.8 3 2.8 6 2.8 9.8c0 1.5.5 2.9 1.2 4.2z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const ClockIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.8" />
    <path d="M10 6.5V10l2.5 2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export default function DashboardPage() {
  const { leads, loading: leadsLoading } = useRealtimeLeads();
  const { deals, loading: dealsLoading } = useRealtimeDeals();

  if (leadsLoading || dealsLoading) {
    return (
      <div className="space-y-6">
        <div>
          <div className="h-8 w-48 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
          <div className="h-4 w-72 rounded-lg animate-pulse mt-2" style={{ backgroundColor: "#e5e5dc" }} />
        </div>
        <div className="grid grid-cols-3 gap-5">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card p-5 h-28 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
      </div>
    );
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const leadsToday = leads.filter((l) => new Date(l.created_at) >= today).length;

  const activeDeals = deals.filter((d) => d.stage !== "fechado_ganho" && d.stage !== "fechado_perdido");
  const activeValue = activeDeals.reduce((sum, d) => sum + (d.value || 0), 0);

  const wonDeals = deals.filter((d) => d.stage === "fechado_ganho");
  const wonValue = wonDeals.reduce((sum, d) => sum + (d.value || 0), 0);

  const lostDeals = deals.filter((d) => d.stage === "fechado_perdido");
  const lostValue = lostDeals.reduce((sum, d) => sum + (d.value || 0), 0);

  const oneHourAgo = Date.now() - 60 * 60 * 1000;
  const unanswered = leads.filter(
    (l) => l.last_msg_at && new Date(l.last_msg_at).getTime() < oneHourAgo && !l.human_control
  ).length;

  const withResponse = leads.filter((l) => l.first_response_at);
  const avgResponseMs = withResponse.length > 0
    ? withResponse.reduce((sum, l) => {
        return sum + (new Date(l.first_response_at!).getTime() - new Date(l.created_at).getTime());
      }, 0) / withResponse.length
    : 0;
  const avgResponseMin = Math.round(avgResponseMs / 60000);
  const responseStr = avgResponseMin > 0 ? `${avgResponseMin}m` : "\u2014";

  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  const funnelData = DEAL_STAGES
    .filter((s) => s.key !== "fechado_perdido")
    .map((stage) => {
      const stageDeals = deals.filter((d) => d.stage === stage.key);
      return {
        name: stage.label,
        count: stageDeals.length,
        value: stageDeals.reduce((sum, d) => sum + (d.value || 0), 0),
      };
    });

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-[28px] font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
          Dashboard
        </h1>
        <p className="text-[14px] mt-1" style={{ color: "var(--text-muted)" }}>
          Visao geral do desempenho e metricas
        </p>
      </div>

      <div className="grid grid-cols-3 gap-5 mb-8">
        <KpiCard label="Leads hoje" value={leadsToday} icon={TrendUpIcon} />
        <KpiCard label="Deals ativos" value={activeDeals.length} subtitle={fmt(activeValue)} icon={UsersIcon} />
        <KpiCard label="Deals ganhos" value={wonDeals.length} subtitle={fmt(wonValue)} icon={CheckIcon} />
        <KpiCard label="Deals perdidos" value={lostDeals.length} subtitle={fmt(lostValue)} icon={XIcon} />
        <KpiCard label="Chats sem resposta" value={unanswered} icon={ChatIcon} />
        <KpiCard label="Tempo de resposta" value={responseStr} icon={ClockIcon} />
      </div>

      <div className="grid grid-cols-2 gap-5 mb-8">
        <FunnelChart data={funnelData} />
        <LeadSourcesChart leads={leads} />
      </div>

      <div className="mb-8">
        <FunnelMovement deals={deals} />
      </div>

    </div>
  );
}

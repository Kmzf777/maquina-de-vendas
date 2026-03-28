"use client";

import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
import { AGENT_STAGES } from "@/lib/constants";
import { KpiCard } from "@/components/kpi-card";
import { FunnelChart } from "@/components/funnel-chart";
import { CampaignMetricsTable } from "@/components/campaign-table";
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
  const { campaigns, loading: campaignsLoading } = useRealtimeCampaigns();

  if (leadsLoading || campaignsLoading) {
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

  const activeLeads = leads.filter((l) => l.seller_stage !== "perdido" && l.seller_stage !== "fechado");
  const activeValue = activeLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);

  const wonLeads = leads.filter((l) => l.seller_stage === "fechado");
  const wonValue = wonLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);

  const lostLeads = leads.filter((l) => l.seller_stage === "perdido");
  const lostValue = lostLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);

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

  const funnelData: { name: string; count: number; value: number }[] = AGENT_STAGES.map((stage) => {
    const stageLeads = leads.filter((l) => l.stage === stage.key);
    return {
      name: stage.label,
      count: stageLeads.length,
      value: stageLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0),
    };
  });
  const humanLeads = leads.filter((l) => l.human_control);
  funnelData.push({
    name: "Convertidos",
    count: humanLeads.length,
    value: humanLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0),
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
        <KpiCard label="Leads ativos" value={activeLeads.length} subtitle={fmt(activeValue)} icon={UsersIcon} />
        <KpiCard label="Leads ganhos" value={wonLeads.length} subtitle={fmt(wonValue)} icon={CheckIcon} />
        <KpiCard label="Leads perdidos" value={lostLeads.length} subtitle={fmt(lostValue)} icon={XIcon} />
        <KpiCard label="Chats sem resposta" value={unanswered} icon={ChatIcon} />
        <KpiCard label="Tempo de resposta" value={responseStr} icon={ClockIcon} />
      </div>

      <div className="grid grid-cols-2 gap-5 mb-8">
        <FunnelChart data={funnelData} />
        <LeadSourcesChart leads={leads} />
      </div>

      <div className="mb-8">
        <FunnelMovement leads={leads} />
      </div>

      <CampaignMetricsTable campaigns={campaigns} />
    </div>
  );
}

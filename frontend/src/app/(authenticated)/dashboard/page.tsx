"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { KpiCard } from "@/components/kpi-card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ConversionFunnel } from "@/components/dashboard/conversion-funnel";
import { OutboundFunnel } from "@/components/dashboard/outbound-funnel";
import { FollowupBoard } from "@/components/dashboard/followup-board";
import { SlaTable } from "@/components/dashboard/sla-table";
import { OverdueLeadsSection } from "@/components/dashboard/overdue-leads-section";
import { OnlineUsersSection } from "@/components/dashboard/online-users-section";
import { ConversionsSection } from "@/components/dashboard/conversions-section";
import { fmtDuration, fmtInt, fmtPct } from "@/components/dashboard/format";
import { dualFromUsd, type FxRate } from "@/components/dashboard/currency";
import type {
  DashboardConversion,
  DashboardFollowups,
  DashboardKpis,
  DashboardOutbound,
} from "@/components/dashboard/types";

// ---------------------------------------------------------------------------
// Período (mesmo padrão visual do /estatisticas: Hoje / 7 dias / 30 dias)
// ---------------------------------------------------------------------------

type PeriodDays = 1 | 7 | 30;

const PERIOD_OPTIONS: { label: string; days: PeriodDays }[] = [
  { label: "Hoje", days: 1 },
  { label: "7 dias", days: 7 },
  { label: "30 dias", days: 30 },
];

/** Data LOCAL em YYYY-MM-DD (nunca toISOString, que desloca para UTC). */
function localDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** start inclusivo (hoje − (days−1)) e end EXCLUSIVO (amanhã). */
function getRange(days: PeriodDays): { start: string; end: string } {
  const start = new Date();
  start.setDate(start.getDate() - (days - 1));
  const end = new Date();
  end.setDate(end.getDate() + 1);
  return { start: localDateStr(start), end: localDateStr(end) };
}

// ---------------------------------------------------------------------------
// Estado por bloco: um bloco com erro mostra aviso discreto e não derruba
// a página; refreshes silenciosos (polling/focus) não voltam ao skeleton.
// ---------------------------------------------------------------------------

interface BlockState<T> {
  data: T | null;
  loading: boolean;
  error: boolean;
}

const INITIAL_BLOCK = { data: null, loading: true, error: false };

function InfoTip({ text }: { text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-help" aria-label="Mais informações">
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10 9.2v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="10" cy="6.4" r="0.9" fill="currentColor" />
          </svg>
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-[280px] leading-relaxed">{text}</TooltipContent>
    </Tooltip>
  );
}

const TrendUpIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M3 14l4-4 3 3 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M13 6h4v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const ChatIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 14l-1 4 4-2c1.2.5 2.5.8 3.8.8 4.4 0 8-3 8-6.8S15.2 3 10.8 3 2.8 6 2.8 9.8c0 1.5.5 2.9 1.2 4.2z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const HandoffIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M3 10h11M11 6.5l3.5 3.5-3.5 3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="16.5" cy="10" r="1.2" fill="currentColor" />
  </svg>
);
const PercentIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M15.5 4.5l-11 11" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    <circle cx="6" cy="6" r="2.2" stroke="currentColor" strokeWidth="1.6" />
    <circle cx="14" cy="14" r="2.2" stroke="currentColor" strokeWidth="1.6" />
  </svg>
);
const DollarIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 2.5v15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    <path d="M13.5 5.5c-.7-1-2-1.5-3.5-1.5-1.9 0-3.3 1-3.3 2.6 0 3.4 7 1.9 7 5.4 0 1.7-1.6 2.7-3.7 2.7-1.7 0-3.1-.7-3.8-1.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-4">
      {children}
    </p>
  );
}

function BlockError({ label }: { label: string }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 text-[13px] text-[#7b7b78]">
      Não foi possível carregar {label}. Nova tentativa automática em instantes.
    </div>
  );
}

function CardSkeletonRow({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-5">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="bg-white border border-[#dedbd6] rounded-[8px] p-4 h-32 animate-pulse"
        />
      ))}
    </div>
  );
}

function BlockSkeleton({ height = "h-56" }: { height?: string }) {
  return (
    <div className={`bg-white border border-[#dedbd6] rounded-[8px] ${height} animate-pulse`} />
  );
}

// ---------------------------------------------------------------------------
// Página
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const [period, setPeriod] = useState<PeriodDays>(1);

  const [kpis, setKpis] = useState<BlockState<DashboardKpis>>(INITIAL_BLOCK);
  const [conversion, setConversion] =
    useState<BlockState<DashboardConversion>>(INITIAL_BLOCK);
  const [outbound, setOutbound] =
    useState<BlockState<DashboardOutbound>>(INITIAL_BLOCK);
  const [followups, setFollowups] =
    useState<BlockState<DashboardFollowups>>(INITIAL_BLOCK);

  // Câmbio: bloco à parte, sem skeleton. Enquanto não chega (ou se falhar), os
  // cards de custo mostram só a moeda nativa — o painel nunca espera o câmbio.
  const [fx, setFx] = useState<FxRate | null>(null);

  // Descarta respostas de fetches antigos (troca de período em voo).
  const runIdRef = useRef(0);

  const refresh = useCallback(
    (reset: boolean) => {
      const runId = ++runIdRef.current;
      const { start, end } = getRange(period);
      const q = `start=${start}&end=${end}`;

      const fetchBlock = <T,>(
        url: string,
        set: React.Dispatch<React.SetStateAction<BlockState<T>>>,
      ) => {
        if (reset) set({ data: null, loading: true, error: false });
        fetch(url)
          .then(async (res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return (await res.json()) as T;
          })
          .then((data) => {
            if (runIdRef.current !== runId) return;
            set({ data, loading: false, error: false });
          })
          .catch(() => {
            if (runIdRef.current !== runId) return;
            set((prev) => ({ ...prev, loading: false, error: true }));
          });
      };

      // 4 rotas em paralelo; followups ignora o período (sempre "hoje").
      fetchBlock<DashboardKpis>(`/api/dashboard/kpis?${q}`, setKpis);
      fetchBlock<DashboardConversion>(`/api/dashboard/conversion?${q}`, setConversion);
      fetchBlock<DashboardOutbound>(`/api/dashboard/outbound?${q}`, setOutbound);
      fetchBlock<DashboardFollowups>(`/api/dashboard/followups`, setFollowups);

      // Câmbio não depende do período e não derruba nada: falhou, fica null.
      fetch(`/api/dashboard/fx`)
        .then((res) => (res.ok ? (res.json() as Promise<FxRate>) : null))
        .then((data) => {
          if (runIdRef.current !== runId) return;
          if (data) setFx(data);
        })
        .catch(() => {});
    },
    [period],
  );

  // Fetch no mount e a cada mudança de período (com skeleton).
  useEffect(() => {
    refresh(true);
  }, [refresh]);

  // Polling de 60s + refresh no focus da janela (silenciosos).
  useEffect(() => {
    const interval = setInterval(() => refresh(false), 60_000);
    const onFocus = () => refresh(false);
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  const k = kpis.data;
  const trendPct = k?.leads_trend_pct ?? null;
  const isToday = period === 1;

  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex flex-col h-full">
        {/* Page header */}
        <div className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-3 md:py-5 flex flex-wrap items-end justify-between gap-4 flex-shrink-0">
          <div>
            <h1
              style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }}
              className="text-[32px] font-normal text-[#111111]"
            >
              Dashboard
            </h1>
            <p className="text-[14px] text-[#7b7b78] mt-0.5">Visão geral do pipeline</p>
          </div>

          {/* Seletor de período */}
          <div className="flex gap-1">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => setPeriod(opt.days)}
                className={
                  period === opt.days
                    ? "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                    : "bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                }
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Main content */}
        <div className="px-4 md:px-8 py-4 md:py-8 overflow-auto flex-1 bg-[#faf9f6]">
          {/* Linha 1 — O motor hoje */}
          <div className="mb-8">
            <SectionLabel>O motor hoje</SectionLabel>
            {kpis.loading && !k ? (
              <CardSkeletonRow />
            ) : kpis.error && !k ? (
              <BlockError label="os indicadores do motor" />
            ) : k ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-5">
                <KpiCard
                  label="Leads novos"
                  value={fmtInt(k.leads_new)}
                  icon={TrendUpIcon}
                  trend={
                    trendPct !== null
                      ? `vs período anterior: ${trendPct >= 0 ? "+" : ""}${trendPct.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`
                      : undefined
                  }
                  trendPositive={trendPct !== null ? trendPct >= 0 : undefined}
                />
                <KpiCard
                  label="Leads ativos com a Valéria"
                  value={fmtInt(k.active_with_ai)}
                  subtitle={`${fmtInt(k.active_awaiting_lead)} aguardando lead`}
                  icon={
                    <InfoTip text="Snapshot de agora, janela de 24h: leads com IA ativa e mensagem recebida nas últimas 24 horas. Não é afetado pelo seletor de período." />
                  }
                />
                <KpiCard
                  label="Conversas atendidas pela IA"
                  value={fmtInt(k.conversations_attended)}
                  icon={ChatIcon}
                />
                <KpiCard
                  label="Handoffs p/ humano"
                  value={fmtInt(k.handoffs)}
                  icon={HandoffIcon}
                />
              </div>
            ) : null}
          </div>

          {/* Linha 2 — Qualidade e custo */}
          <div className="mb-8">
            <SectionLabel>Qualidade e custo</SectionLabel>
            {kpis.loading && !k ? (
              <CardSkeletonRow />
            ) : kpis.error && !k ? (
              <BlockError label="os indicadores de qualidade e custo" />
            ) : k ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-5">
                <KpiCard
                  label="Taxa de qualificação"
                  value={fmtPct(k.qualification_rate)}
                  icon={PercentIcon}
                />
                <KpiCard
                  label="SLA humano pós-handoff"
                  value={
                    k.sla_samples > 0 && k.sla_median_minutes !== null
                      ? fmtDuration(k.sla_median_minutes)
                      : "—"
                  }
                  subtitle={
                    k.sla_samples > 0
                      ? `p95 ${k.sla_p95_minutes !== null ? fmtDuration(k.sla_p95_minutes) : "—"} · ${fmtInt(k.sla_samples)} handoffs`
                      : undefined
                  }
                  icon={
                    <InfoTip text="Conta apenas horário comercial: seg–sex, 10h–16h (BRT). Feriados não são descontados." />
                  }
                />
                <KpiCard
                  label="Custo IA por handoff"
                  value={dualFromUsd(k.cost_per_handoff_usd, fx).primary}
                  subtitle={dualFromUsd(k.cost_per_handoff_usd, fx).secondary}
                  icon={DollarIcon}
                />
                <KpiCard
                  label={`Custo por atendimento (${isToday ? "hoje" : "no período"})`}
                  value={dualFromUsd(k.cost_per_atendimento_usd, fx).primary}
                  subtitle={dualFromUsd(k.cost_per_atendimento_usd, fx).secondary}
                  icon={DollarIcon}
                />
              </div>
            ) : null}
          </div>

          {/* Blocos: Conversão fim-a-fim + Outbound Frio */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-5 mb-8">
            <div>
              <SectionLabel>Conversão fim-a-fim</SectionLabel>
              {conversion.loading && !conversion.data ? (
                <BlockSkeleton />
              ) : conversion.error && !conversion.data ? (
                <BlockError label="a conversão fim-a-fim" />
              ) : conversion.data ? (
                <ConversionFunnel data={conversion.data} />
              ) : null}
            </div>
            <div>
              <SectionLabel>Outbound Frio</SectionLabel>
              {outbound.loading && !outbound.data ? (
                <BlockSkeleton />
              ) : outbound.error && !outbound.data ? (
                <BlockError label="o funil de outbound frio" />
              ) : outbound.data ? (
                <OutboundFunnel data={outbound.data} />
              ) : null}
            </div>
          </div>

          {/* Bloco: Esteira de Follow-up */}
          <div className="mb-8">
            <SectionLabel>Esteira de Follow-up</SectionLabel>
            {followups.loading && !followups.data ? (
              <BlockSkeleton height="h-48" />
            ) : followups.error && !followups.data ? (
              <BlockError label="a esteira de follow-up" />
            ) : followups.data ? (
              <FollowupBoard data={followups.data} />
            ) : null}
          </div>

          {/* Drill-down existente (intocado) */}
          <SlaTable />
          <OverdueLeadsSection />
          <OnlineUsersSection />
          <ConversionsSection />
        </div>
      </div>
    </TooltipProvider>
  );
}

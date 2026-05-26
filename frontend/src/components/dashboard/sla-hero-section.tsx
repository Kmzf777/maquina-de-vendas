"use client";

import { useState } from "react";
import { useJoaoSlaStats, type DateFilter } from "@/hooks/use-joao-sla-stats";
import { formatBusinessDuration } from "@/lib/business-hours";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { KpiCard } from "@/components/kpi-card";

const DATE_FILTER_OPTIONS: { value: DateFilter; label: string }[] = [
  { value: "1d", label: "Hoje" },
  { value: "7d", label: "7 dias" },
  { value: "30d", label: "30 dias" },
  { value: "all", label: "Tudo" },
];

const WORST_SLA_LABEL: Record<DateFilter, string> = {
  "1d": "Pior SLA hoje",
  "7d": "Pior SLA (7 dias)",
  "30d": "Pior SLA (30 dias)",
  "all": "Pior SLA registrado",
};

// ---------- Inline SVG icons ----------
const ClockIcon = (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4" />
    <path
      d="M8 5v3l2 2"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const AlertIcon = (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <path
      d="M8 2.5L14 13H2L8 2.5Z"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinejoin="round"
    />
    <path
      d="M8 7v2.5"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    />
    <circle cx="8" cy="11" r="0.6" fill="currentColor" />
  </svg>
);

const WorstSlaIcon = (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <rect x="2" y="11" width="2.5" height="3" rx="0.5" fill="currentColor" opacity="0.4" />
    <rect x="6" y="7.5" width="2.5" height="6.5" rx="0.5" fill="currentColor" opacity="0.6" />
    <rect x="10" y="4" width="2.5" height="10" rx="0.5" fill="currentColor" />
    <path
      d="M11.25 2L13.5 4.25M11.25 2H9M11.25 2V4.25"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

// ---------- Skeleton ----------
function SlaCardSkeleton() {
  return (
    <div className="animate-pulse bg-[#dedbd6]/40 rounded-[8px] h-28" />
  );
}

// ---------- Main section ----------
export function SlaHeroSection() {
  const [filter, setFilter] = useState<DateFilter>("7d");
  const { avgSlaMinutes, overdueCount, worstSlaMinutes, loading } =
    useJoaoSlaStats(filter);

  return (
    <div className="mb-8">
      {/* Discreet section header */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
          SLA — Resposta João
        </p>
        <Select
          value={filter}
          onValueChange={(v) => setFilter(v as DateFilter)}
        >
          <SelectTrigger className="h-7 w-[110px] text-[13px] border-[#dedbd6] bg-white rounded-[6px] text-[#111111] focus:ring-0 focus:ring-offset-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="text-[13px]">
            {DATE_FILTER_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* KPI cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-5">
        {loading ? (
          <>
            <SlaCardSkeleton />
            <SlaCardSkeleton />
            <SlaCardSkeleton />
          </>
        ) : (
          <>
            <KpiCard
              label="Média de resposta"
              value={avgSlaMinutes !== null ? formatBusinessDuration(avgSlaMinutes) : "—"}
              subtitle="horário comercial"
              icon={ClockIcon}
            />
            <KpiCard
              label="Em atraso agora"
              value={String(overdueCount)}
              trend={overdueCount > 0 ? `${overdueCount} conversa${overdueCount !== 1 ? "s" : ""}` : undefined}
              trendPositive={overdueCount > 0 ? false : undefined}
              subtitle={overdueCount === 0 ? "> 20min sem resposta" : undefined}
              icon={AlertIcon}
            />
            <KpiCard
              label={WORST_SLA_LABEL[filter]}
              value={worstSlaMinutes !== null ? formatBusinessDuration(worstSlaMinutes) : "—"}
              subtitle="maior tempo registrado"
              icon={WorstSlaIcon}
            />
          </>
        )}
      </div>
    </div>
  );
}

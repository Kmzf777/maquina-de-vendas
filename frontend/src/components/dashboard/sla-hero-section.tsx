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

const DATE_FILTER_OPTIONS: { value: DateFilter; label: string }[] = [
  { value: "1d", label: "Hoje" },
  { value: "7d", label: "7 dias" },
  { value: "30d", label: "30 dias" },
  { value: "all", label: "Tudo" },
];

// ---------- Skeleton ----------
function MetricCardSkeleton() {
  return (
    <div className="flex-1 min-w-0 bg-white border border-[#dedbd6] rounded-[8px] p-5 animate-pulse">
      <div className="h-[11px] w-24 bg-[#dedbd6]/60 rounded mb-4" />
      <div className="h-10 w-20 bg-[#dedbd6]/50 rounded mb-2" />
      <div className="h-[13px] w-28 bg-[#dedbd6]/40 rounded" />
    </div>
  );
}

// ---------- Metric card ----------
interface MetricCardProps {
  label: string;
  value: string;
  subtitle: string;
  /** When true, renders card in alert/overdue style */
  alert?: boolean;
}

function MetricCard({ label, value, subtitle, alert = false }: MetricCardProps) {
  return (
    <div
      className={[
        "flex-1 min-w-0 rounded-[8px] p-5 border transition-colors duration-200",
        alert
          ? "bg-[#fff5f5] border-[#f5c6c6]"
          : "bg-white border-[#dedbd6]",
      ].join(" ")}
    >
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">
        {label}
      </p>
      <p
        className={[
          "text-[48px] font-normal leading-none tabular-nums",
          alert ? "text-[#c41c1c]" : "text-[#111111]",
        ].join(" ")}
        style={{ letterSpacing: "-1.5px" }}
      >
        {value}
      </p>
      <p
        className={[
          "text-[13px] mt-2",
          alert ? "text-[#c41c1c]/80" : "text-[#7b7b78]",
        ].join(" ")}
      >
        {subtitle}
      </p>
    </div>
  );
}

// ---------- Main section ----------
export function SlaHeroSection() {
  const [filter, setFilter] = useState<DateFilter>("7d");
  const { avgSlaMinutes, overdueCount, worstSlaTodayMinutes, loading } =
    useJoaoSlaStats(filter);

  return (
    <div
      className="mb-6 rounded-[8px] border border-[#dedbd6] bg-[#faf9f6] overflow-hidden"
      style={{ borderLeftWidth: "3px", borderLeftColor: "#ff5600" }}
    >
      {/* Section header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-[#dedbd6]">
        <div className="flex items-center gap-2">
          {/* Clock icon */}
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <circle cx="8" cy="8" r="6" stroke="#ff5600" strokeWidth="1.5" />
            <path
              d="M8 5v3l2 2"
              stroke="#ff5600"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <p className="text-[12px] uppercase tracking-[0.6px] font-medium text-[#111111]">
            SLA — Resposta João
          </p>
        </div>

        <Select
          value={filter}
          onValueChange={(v) => setFilter(v as DateFilter)}
        >
          <SelectTrigger className="h-7 w-[110px] text-[12px] border-[#dedbd6] bg-white rounded-[6px] text-[#111111] focus:ring-0 focus:ring-offset-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="text-[12px]">
            {DATE_FILTER_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Cards */}
      <div className="flex gap-4 p-4 flex-wrap md:flex-nowrap">
        {loading ? (
          <>
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
          </>
        ) : (
          <>
            <MetricCard
              label="Média de resposta"
              value={
                avgSlaMinutes !== null
                  ? formatBusinessDuration(avgSlaMinutes)
                  : "—"
              }
              subtitle="horário comercial"
            />
            <MetricCard
              label="Em atraso agora"
              value={String(overdueCount)}
              subtitle="> 20min sem resposta"
              alert={overdueCount > 0}
            />
            <MetricCard
              label="Pior SLA hoje"
              value={
                worstSlaTodayMinutes !== null
                  ? formatBusinessDuration(worstSlaTodayMinutes)
                  : "—"
              }
              subtitle="maior tempo registrado"
            />
          </>
        )}
      </div>
    </div>
  );
}

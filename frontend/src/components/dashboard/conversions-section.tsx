"use client";

import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

// ---- Types ----------------------------------------------------------------

interface ConversionStats {
  total: number;
  meta_sent: number;
  google_pending: number;
  google_exported: number;
  by_event: {
    lead: number;
    qualified: number;
    opportunity: number;
    purchase: number;
  };
  purchase_value: number;
}

// ---- Skeleton -------------------------------------------------------------

function StatSkeleton() {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 animate-pulse">
      <div className="h-3 w-28 bg-[#dedbd6]/40 rounded mb-3" />
      <div className="h-12 w-20 bg-[#dedbd6]/30 rounded" />
    </div>
  );
}

// ---- Metric card ----------------------------------------------------------

function StatCard({
  label,
  value,
  subtitle,
  accent,
}: {
  label: string;
  value: string | number;
  subtitle?: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`bg-white border rounded-[8px] p-5 ${
        accent ? "border-[#111111]" : "border-[#dedbd6]"
      }`}
    >
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">
        {label}
      </p>
      <p
        className="text-[48px] font-normal leading-none text-[#111111]"
        style={{ letterSpacing: "-1.5px" }}
      >
        {value}
      </p>
      {subtitle && (
        <p className="text-[13px] mt-2 text-[#7b7b78]">{subtitle}</p>
      )}
    </div>
  );
}

// ---- Section --------------------------------------------------------------

export function ConversionsSection() {
  const [stats, setStats] = useState<ConversionStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/conversions/stats")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled) {
          setStats(data && !data.error ? (data as ConversionStats) : null);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-4">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Conversões (Ads)
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-5">
          {[0, 1, 2, 3].map((i) => (
            <StatSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  }

  // Render nothing if data is unavailable (backend offline / not deployed yet)
  if (!stats) return null;

  const fmtBRL = (v: number) =>
    `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  const eventBadges: { label: string; count: number }[] = [
    { label: "Qualificado", count: stats.by_event.qualified },
    { label: "Oportunidade", count: stats.by_event.opportunity },
    { label: "Venda", count: stats.by_event.purchase },
  ].filter((b) => b.count > 0);

  return (
    <div className="mb-8">
      {/* Section heading */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Conversões (Ads)
          </p>
          <p className="text-[12px] text-[#7b7b78] mt-0.5">
            Atribuição enviada ao Meta e pendente de exportação no Google
          </p>
        </div>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-5 mb-4">
        <StatCard
          label="Pendentes p/ Google"
          value={stats.google_pending}
          subtitle="aguardando exportação"
          accent
        />
        <StatCard
          label="Exportadas (Google)"
          value={stats.google_exported}
          subtitle="já enviadas"
        />
        <StatCard
          label="Enviadas ao Meta"
          value={stats.meta_sent}
          subtitle="via CAPI"
        />
        <StatCard
          label="Valor em vendas"
          value={fmtBRL(stats.purchase_value)}
        />
      </div>

      {/* Footer row: event breakdown + download button */}
      <div className="bg-white border border-[#dedbd6] rounded-[8px] px-5 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        {/* By-event badges */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mr-1">
            Por evento:
          </span>
          {eventBadges.length > 0 ? (
            eventBadges.map((b) => (
              <Badge
                key={b.label}
                variant="outline"
                className="text-[11px] border-[#dedbd6] text-[#111111] bg-[#faf9f6] px-2 py-0.5"
              >
                {b.label} · {b.count}
              </Badge>
            ))
          ) : (
            <span className="text-[12px] text-[#7b7b78]">Sem eventos registrados</span>
          )}
        </div>

        {/* Download button */}
        <div className="flex items-center gap-3 flex-shrink-0">
          <p className="text-[12px] text-[#7b7b78]">
            {stats.google_pending} pendente{stats.google_pending !== 1 ? "s" : ""}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="border-[#dedbd6] bg-white text-[#111111] hover:bg-[#f7f5f1] active:bg-[#f0ede8] rounded-[4px] text-[13px] h-8 px-3 flex items-center gap-1.5"
            onClick={() => { window.location.href = "/api/conversions/google-export"; }}
          >
            <Download size={13} strokeWidth={2} />
            Baixar conversões Google (CSV)
          </Button>
        </div>
      </div>
    </div>
  );
}

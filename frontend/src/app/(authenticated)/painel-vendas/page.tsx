"use client";

import { useState, useEffect } from "react";
import { SalesMetricsCards } from "@/components/sales/sales-metrics-cards";
import { SalesFiltersBar } from "@/components/sales/sales-filters";
import { SalesTable } from "@/components/sales/sales-table";
import { useSales, type SalesFilters } from "@/hooks/use-sales";

interface SalesMetrics {
  total_value: number;
  count: number;
  avg_value: number;
  avg_repurchase_cycle_days: number | null;
}

// helpers
function startOfMonth(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function PainelVendasPage() {
  const [filters, setFilters] = useState<SalesFilters>({
    from: startOfMonth(),
    to: today(),
    page: 1,
  });
  const [metrics, setMetrics] = useState<SalesMetrics | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(true);

  const { sales, count, loading } = useSales(filters);

  useEffect(() => {
    setMetricsLoading(true);
    const params = new URLSearchParams();
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
    fetch(`/api/sales/metrics?${params}`)
      .then((r) => r.json())
      .then((data) => { setMetrics(data); setMetricsLoading(false); })
      .catch(() => setMetricsLoading(false));
  }, [filters.from, filters.to]);

  return (
    <div className="flex-1 overflow-y-auto bg-[#faf9f6]">
      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        <div>
          <h1 className="text-[22px] font-semibold text-[#111111] tracking-tight">Painel de Vendas</h1>
          <p className="text-[13px] text-[#7b7b78] mt-0.5">Histórico de vendas e métricas de recompra</p>
        </div>

        <SalesMetricsCards metrics={metrics} loading={metricsLoading} />

        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 space-y-5">
          <SalesFiltersBar filters={filters} onChange={setFilters} />
          <SalesTable
            sales={sales}
            loading={loading}
            count={count}
            page={filters.page ?? 1}
            onPageChange={(p) => setFilters((f) => ({ ...f, page: p }))}
          />
        </div>
      </div>
    </div>
  );
}

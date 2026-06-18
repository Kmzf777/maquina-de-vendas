"use client";

import { useState, useEffect } from "react";
import { SalesMetricsCards } from "@/components/sales/sales-metrics-cards";
import { SalesFiltersBar } from "@/components/sales/sales-filters";
import { SalesTable } from "@/components/sales/sales-table";
import { useSales, type SalesFilters } from "@/hooks/use-sales";
import { SaleCreateModal } from "@/components/sales/sale-create-modal";
import type { Sale } from "@/lib/types";

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

  const { sales, count, loading, refetch } = useSales(filters);
  const [showCreate, setShowCreate] = useState(false);
  const [editingSale, setEditingSale] = useState<Sale | null>(null);

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
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-[22px] font-semibold text-[#111111] tracking-tight">Painel de Vendas</h1>
            <p className="text-[13px] text-[#7b7b78] mt-0.5">Histórico de vendas e métricas de recompra</p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-[4px] bg-[#1f9d57] text-white text-[14px] font-medium hover:bg-[#1b8a4c] transition-colors shrink-0"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
            </svg>
            Registrar Venda
          </button>
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
            onEdit={(s) => setEditingSale(s)}
            onDelete={async (id) => {
              if (!window.confirm("Excluir esta venda? Esta ação não pode ser desfeita.")) return;
              const r = await fetch(`/api/sales/${id}`, { method: "DELETE" });
              if (r.ok) refetch(); else alert("Erro ao excluir venda.");
            }}
          />
        </div>
      </div>
      {(showCreate || editingSale) && (
        <SaleCreateModal
          pickLead={!editingSale}
          editingSale={editingSale}
          onClose={() => { setShowCreate(false); setEditingSale(null); }}
          onSaved={() => { refetch(); setShowCreate(false); setEditingSale(null); }}
        />
      )}
    </div>
  );
}

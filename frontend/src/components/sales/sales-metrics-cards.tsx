"use client";

interface SalesMetrics {
  total_value: number;
  count: number;
  avg_value: number;
  avg_repurchase_cycle_days: number | null;
}

interface SalesMetricsCardsProps {
  metrics: SalesMetrics | null;
  loading: boolean;
}

function MetricCard({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">{label}</p>
      {loading ? (
        <div className="h-7 w-24 bg-[#dedbd6]/40 rounded-[4px] animate-pulse" />
      ) : (
        <p className="text-[22px] font-semibold text-[#111111] leading-none">{value}</p>
      )}
    </div>
  );
}

export function SalesMetricsCards({ metrics, loading }: SalesMetricsCardsProps) {
  const fmt = (n: number) =>
    n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <MetricCard
        label="Faturamento do período"
        value={metrics ? `R$ ${fmt(metrics.total_value)}` : "R$ 0,00"}
        loading={loading}
      />
      <MetricCard
        label="Nº de vendas"
        value={metrics ? String(metrics.count) : "0"}
        loading={loading}
      />
      <MetricCard
        label="Ticket médio"
        value={metrics ? `R$ ${fmt(metrics.avg_value)}` : "R$ 0,00"}
        loading={loading}
      />
      <MetricCard
        label="Ciclo médio de recompra"
        value={
          metrics?.avg_repurchase_cycle_days != null
            ? `${metrics.avg_repurchase_cycle_days} dias`
            : "—"
        }
        loading={loading}
      />
    </div>
  );
}

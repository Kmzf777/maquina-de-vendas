"use client";

import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { useCurrentRole } from "@/hooks/use-current-role";

// ── Types ──────────────────────────────────────────────────────────────────────

interface TimeseriesPoint {
  date: string;
  qualified: number;
  opportunity: number;
  purchase: number;
}

interface DashboardData {
  kpis: {
    google_pending: number;
    google_exported: number;
    meta_sent: number;
    purchase_value: number;
  };
  traffic_split: {
    paid: number;
    organic: number;
    unknown: number;
  };
  timeseries: TimeseriesPoint[];
  value_by_traffic: {
    paid: number;
    organic: number;
    unknown: number;
  };
}

// ── Palette constants ──────────────────────────────────────────────────────────

const COLOR_PAID = "#111111";
const COLOR_ORGANIC = "#5aad65";
const COLOR_UNKNOWN = "#b3b3b0";
const COLOR_QUALIFIED = "#d4a04a";
const COLOR_OPPORTUNITY = "#5b8aad";
const COLOR_PURCHASE = "#5aad65";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtBRL(v: number): string {
  return `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

function shortDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return `${d.getDate()}/${d.getMonth() + 1}`;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatSkeleton() {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 animate-pulse">
      <div className="h-3 w-28 bg-[#dedbd6]/40 rounded mb-3" />
      <div className="h-10 w-20 bg-[#dedbd6]/30 rounded" />
      <div className="h-3 w-24 bg-[#dedbd6]/20 rounded mt-3" />
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 animate-pulse">
      <div className="h-3 w-32 bg-[#dedbd6]/40 rounded mb-4" />
      <div className="h-[180px] bg-[#dedbd6]/20 rounded" />
    </div>
  );
}

function KpiCard({
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
        className="text-[40px] font-normal leading-none text-[#111111]"
        style={{ letterSpacing: "-1.5px" }}
      >
        {value}
      </p>
      {subtitle && (
        <p className="text-[12px] mt-2 text-[#7b7b78]">{subtitle}</p>
      )}
    </div>
  );
}

function ChartCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-4">
        {title}
      </p>
      {children}
    </div>
  );
}

// Custom tooltip for BRL values
function BrlTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 shadow-sm text-[12px]">
      {label && (
        <p className="text-[#7b7b78] mb-1">{label}</p>
      )}
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {p.name}: {fmtBRL(p.value)}
        </p>
      ))}
    </div>
  );
}

// Custom tooltip for stacked bar (conversions per stage)
function StackedTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const nameMap: Record<string, string> = {
    qualified: "Qualificado",
    opportunity: "Oportunidade",
    purchase: "Venda",
  };
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 shadow-sm text-[12px]">
      {label && <p className="text-[#7b7b78] mb-1">{shortDate(label)}</p>}
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {nameMap[p.name] ?? p.name}: {p.value}
        </p>
      ))}
    </div>
  );
}

// ── Donut chart ────────────────────────────────────────────────────────────────

function DonutChart({ split }: { split: DashboardData["traffic_split"] }) {
  const data = [
    { name: "Pago", value: split.paid, color: COLOR_PAID },
    { name: "Orgânico", value: split.organic, color: COLOR_ORGANIC },
    { name: "Não classif.", value: split.unknown, color: COLOR_UNKNOWN },
  ].filter((d) => d.value > 0);

  if (data.length === 0) {
    return (
      <p className="text-[12px] text-[#7b7b78] text-center py-8">
        Sem dados de tráfego
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={55}
          outerRadius={80}
          dataKey="value"
          paddingAngle={2}
        >
          {data.map((entry) => (
            <Cell key={entry.name} fill={entry.color} />
          ))}
        </Pie>
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload || payload.length === 0) return null;
            const p = payload[0] as { name: string; value: number; payload: { color: string } };
            return (
              <div className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 shadow-sm text-[12px]">
                <p style={{ color: p.payload.color }}>
                  {p.name}: {p.value}
                </p>
              </div>
            );
          }}
        />
        <Legend
          formatter={(value: string, entry) => {
            const e = entry as { payload?: { value: number } };
            return (
              <span className="text-[11px] text-[#7b7b78]">
                {value}{" "}
                <span className="text-[#111111] font-medium">
                  {e.payload?.value ?? 0}
                </span>
              </span>
            );
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

// ── Stacked bar chart (timeseries) ─────────────────────────────────────────────

function TimeseriesChart({ data }: { data: TimeseriesPoint[] }) {
  // Show a tick every ~5 days
  const tickInterval = Math.max(1, Math.floor(data.length / 6));

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} barCategoryGap="20%">
        <CartesianGrid strokeDasharray="3 3" stroke="#dedbd6" vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={shortDate}
          tick={{ fontSize: 11, fill: "#7b7b78" }}
          interval={tickInterval}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          allowDecimals={false}
          tick={{ fontSize: 11, fill: "#7b7b78" }}
          axisLine={false}
          tickLine={false}
          width={24}
        />
        <Tooltip content={<StackedTooltip />} />
        <Legend
          formatter={(value: string) => {
            const map: Record<string, string> = {
              qualified: "Qualificado",
              opportunity: "Oportunidade",
              purchase: "Venda",
            };
            return (
              <span className="text-[11px] text-[#7b7b78]">
                {map[value] ?? value}
              </span>
            );
          }}
        />
        <Bar dataKey="qualified" stackId="a" fill={COLOR_QUALIFIED} radius={[0, 0, 0, 0]} />
        <Bar dataKey="opportunity" stackId="a" fill={COLOR_OPPORTUNITY} radius={[0, 0, 0, 0]} />
        <Bar dataKey="purchase" stackId="a" fill={COLOR_PURCHASE} radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Value by traffic chart ─────────────────────────────────────────────────────

function ValueByTrafficChart({ byTraffic }: { byTraffic: DashboardData["value_by_traffic"] }) {
  const data = [
    { name: "Pago", value: byTraffic.paid, color: COLOR_PAID },
    { name: "Orgânico", value: byTraffic.organic, color: COLOR_ORGANIC },
    ...(byTraffic.unknown > 0
      ? [{ name: "Não classif.", value: byTraffic.unknown, color: COLOR_UNKNOWN }]
      : []),
  ];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} layout="vertical" barCategoryGap="30%">
        <CartesianGrid strokeDasharray="3 3" stroke="#dedbd6" horizontal={false} />
        <XAxis
          type="number"
          tickFormatter={(v: number) => `R$${(v / 1000).toFixed(0)}k`}
          tick={{ fontSize: 11, fill: "#7b7b78" }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          dataKey="name"
          type="category"
          tick={{ fontSize: 11, fill: "#7b7b78" }}
          axisLine={false}
          tickLine={false}
          width={72}
        />
        <Tooltip content={<BrlTooltip />} />
        <Bar dataKey="value" radius={[0, 2, 2, 0]}>
          {data.map((entry) => (
            <Cell key={entry.name} fill={entry.color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Fetch state ───────────────────────────────────────────────────────────────

type FetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "done"; data: DashboardData };

// ── Main section ───────────────────────────────────────────────────────────────

export function ConversionsSection() {
  const { role, loading: roleLoading } = useCurrentRole();
  const [fetchState, setFetchState] = useState<FetchState>({ status: "idle" });

  useEffect(() => {
    if (roleLoading || role !== "admin") return;

    let cancelled = false;

    const run = async () => {
      setFetchState({ status: "loading" });
      try {
        const r = await fetch("/api/conversions/dashboard");
        if (!r.ok) throw new Error(String(r.status));
        const json = (await r.json()) as DashboardData;
        if (!cancelled) {
          setFetchState(
            json && !("error" in json)
              ? { status: "done", data: json }
              : { status: "error" },
          );
        }
      } catch {
        if (!cancelled) setFetchState({ status: "error" });
      }
    };

    void run();

    return () => {
      cancelled = true;
    };
  }, [role, roleLoading]);

  // Gate: render nothing for vendedores or while role is resolving
  if (roleLoading || role !== "admin") return null;

  // ── Loading / idle skeleton ─────────────────────────────────────────────────
  if (fetchState.status === "idle" || fetchState.status === "loading") {
    return (
      <div className="mb-8">
        <div className="mb-4">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Conversões (Ads)
          </p>
          <p className="text-[12px] text-[#7b7b78] mt-0.5">
            Atribuição enviada ao Meta e pendente de exportação no Google
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-5 mb-5">
          {[0, 1, 2, 3].map((i) => (
            <StatSkeleton key={i} />
          ))}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-5">
          {[0, 1, 2].map((i) => (
            <ChartSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  }

  // ── Error / no-data empty state ─────────────────────────────────────────────
  if (fetchState.status === "error") {
    return (
      <div className="mb-8">
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
        <div className="bg-white border border-[#dedbd6] rounded-[8px] px-5 py-8 text-center">
          <p className="text-[13px] text-[#7b7b78]">
            Dados de conversões indisponíveis no momento.
          </p>
        </div>
      </div>
    );
  }

  // fetchState.status === "done" — data is guaranteed
  const { data } = fetchState;

  // ── Full render ─────────────────────────────────────────────────────────────
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

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-5 mb-5">
        <KpiCard
          label="Pendentes p/ Google"
          value={data.kpis.google_pending}
          subtitle="aguardando exportação"
          accent
        />
        <KpiCard
          label="Exportadas (Google)"
          value={data.kpis.google_exported}
          subtitle="já enviadas"
        />
        <KpiCard
          label="Enviadas ao Meta"
          value={data.kpis.meta_sent}
          subtitle="via CAPI"
        />
        <KpiCard
          label="Valor em vendas"
          value={fmtBRL(data.kpis.purchase_value)}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-5 mb-5">
        <ChartCard title="Orgânico × Pago">
          <DonutChart split={data.traffic_split} />
        </ChartCard>

        <ChartCard title="Conversões / dia (30d)">
          <TimeseriesChart data={data.timeseries} />
        </ChartCard>

        <ChartCard title="Valor por origem">
          <ValueByTrafficChart byTraffic={data.value_by_traffic} />
        </ChartCard>
      </div>

      {/* Footer: download */}
      <div className="bg-white border border-[#dedbd6] rounded-[8px] px-5 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <p className="text-[12px] text-[#7b7b78]">
          {data.kpis.google_pending} conversão
          {data.kpis.google_pending !== 1 ? "ões" : ""} pendente
          {data.kpis.google_pending !== 1 ? "s" : ""} para exportação
        </p>
        <Button
          variant="outline"
          size="sm"
          className="border-[#dedbd6] bg-white text-[#111111] hover:bg-[#f7f5f1] active:bg-[#f0ede8] rounded-[4px] text-[13px] h-8 px-3 flex items-center gap-1.5"
          onClick={() => {
            window.location.href = "/api/conversions/google-export";
          }}
        >
          <Download size={13} strokeWidth={2} />
          Baixar conversões Google (CSV)
        </Button>
      </div>
    </div>
  );
}

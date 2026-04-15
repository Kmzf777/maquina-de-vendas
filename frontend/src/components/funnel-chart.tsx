"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface FunnelChartProps {
  data: { name: string; count: number; value?: number }[];
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number; payload?: { value?: number } }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const val = payload[0].payload?.value;
  const valStr = val ? `R$ ${val.toLocaleString("pt-BR")}` : null;
  return (
    <div className="rounded-lg px-3 py-2 shadow-lg text-[13px]" style={{ backgroundColor: "#1f1f1f", color: "#fff" }}>
      <p className="font-medium">{label}</p>
      <p className="opacity-80">{payload[0].value} leads</p>
      {valStr && <p className="opacity-60">{valStr}</p>}
    </div>
  );
}

export function FunnelChart({ data }: FunnelChartProps) {
  return (
    <div className="card p-5">
      <h3
        className="text-[13px] font-semibold uppercase tracking-wider mb-5 flex items-center gap-2"
        style={{ color: "var(--text-secondary)" }}
      >
        Funil de Qualificacao
        <span className="text-[14px] opacity-50">&rarr;</span>
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} layout="vertical" margin={{ left: 80 }}>
          <XAxis
            type="number"
            tick={{ fontSize: 12, fill: "#9ca3af" }}
            axisLine={{ stroke: "#e5e5dc" }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={80}
            tick={{ fontSize: 12, fill: "#5f6368" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(200,204,142,0.1)" }} />
          <Bar dataKey="count" fill="#1f1f1f" radius={[0, 6, 6, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

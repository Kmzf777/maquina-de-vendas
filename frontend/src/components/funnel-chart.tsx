"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface FunnelChartProps {
  data: { name: string; count: number; value?: number }[];
}

const REPORT_COLORS = ["#65b5ff", "#0bdf50", "#fe4c02", "#ff2067", "#b3e01c", "#c41c1c"];

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
    <div
      className="rounded-[8px] px-3 py-2 text-[13px] border border-[#dedbd6]"
      style={{ backgroundColor: "#faf9f6", color: "#111111" }}
    >
      <p className="font-medium text-[#111111]">{label}</p>
      <p className="text-[#7b7b78]">{payload[0].value} leads</p>
      {valStr && <p className="text-[#7b7b78]">{valStr}</p>}
    </div>
  );
}

export function FunnelChart({ data }: FunnelChartProps) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      <h3
        className="text-[18px] font-medium text-[#111111] mb-5"
        style={{ letterSpacing: "-0.3px" }}
      >
        Funil de Qualificação
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} layout="vertical" margin={{ left: 80 }}>
          <XAxis
            type="number"
            tick={{ fontSize: 12, fill: "#7b7b78" }}
            axisLine={{ stroke: "#dedbd6" }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={80}
            tick={{ fontSize: 12, fill: "#7b7b78" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(222,219,214,0.3)" }} />
          <Bar dataKey="count" radius={[0, 4, 4, 0]}>
            {data.map((_, index) => (
              <Cell key={`cell-${index}`} fill={REPORT_COLORS[index % REPORT_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

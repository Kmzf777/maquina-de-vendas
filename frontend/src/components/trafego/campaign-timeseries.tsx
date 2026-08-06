"use client";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

export type TsPoint = { date: string; leads: number; vendas: number; receita: number };

const fmtDay = (d: unknown) => {
  try {
    return new Date(String(d) + "T00:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  } catch {
    return String(d);
  }
};

export function CampaignTimeseries({ data }: { data: TsPoint[] }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <div className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">
        Evolução (leads × vendas por dia)
      </div>
      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke="#f0ede8" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={fmtDay}
              tick={{ fontSize: 11, fill: "#7b7b78" }}
              tickLine={false}
              axisLine={{ stroke: "#dedbd6" }}
              minTickGap={16}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 11, fill: "#7b7b78" }}
              tickLine={false}
              axisLine={false}
              width={28}
            />
            <Tooltip
              labelFormatter={fmtDay}
              contentStyle={{ borderRadius: 8, border: "1px solid #dedbd6", fontSize: 12 }}
            />
            <Bar dataKey="leads" name="Leads" fill="#ff5600" radius={[3, 3, 0, 0]} maxBarSize={22} />
            <Line dataKey="vendas" name="Vendas" stroke="#0bdf50" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

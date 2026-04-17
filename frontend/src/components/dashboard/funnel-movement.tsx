"use client";

import { useState } from "react";
import { DEAL_STAGES } from "@/lib/constants";
import type { Deal } from "@/lib/types";

interface FunnelMovementProps {
  deals: Deal[];
}

type Period = "today" | "7d" | "30d";

function getPeriodStart(period: Period): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  if (period === "7d") d.setDate(d.getDate() - 7);
  if (period === "30d") d.setDate(d.getDate() - 30);
  return d;
}

export function FunnelMovement({ deals }: FunnelMovementProps) {
  const [period, setPeriod] = useState<Period>("30d");
  const periodStart = getPeriodStart(period);

  const stages = DEAL_STAGES.filter((s) => s.key !== "fechado_perdido");

  const data = stages.map((stage) => {
    const inStage = deals.filter((d) => d.stage === stage.key);
    const entered = inStage.filter(
      (d) => d.updated_at && new Date(d.updated_at) >= periodStart
    );
    const value = inStage.reduce((sum, d) => sum + (d.value || 0), 0);

    return {
      ...stage,
      count: inStage.length,
      entered: entered.length,
      value,
    };
  });

  const lost = deals.filter(
    (d) =>
      d.stage === "fechado_perdido" &&
      d.closed_at &&
      new Date(d.closed_at) >= periodStart
  );
  const lostValue = lost.reduce((sum, d) => sum + (d.value || 0), 0);

  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
  const periods: { key: Period; label: string }[] = [
    { key: "today", label: "Hoje" },
    { key: "7d", label: "7 dias" },
    { key: "30d", label: "30 dias" },
  ];

  return (
    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[11px] font-normal uppercase tracking-[0.6px] text-[#7b7b78]">
          Movimentacao do Pipeline
        </h3>
        <div className="flex gap-1">
          {periods.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`px-2.5 py-1 rounded-[4px] text-[11px] font-normal transition-colors ${
                period === p.key
                  ? "bg-[#111111] text-white"
                  : "text-[#7b7b78] hover:bg-[#dedbd6]/40"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr>
              <th className="text-left py-2 px-3 text-[#7b7b78] font-normal uppercase tracking-[0.6px] text-[11px]" />
              {data.map((d) => (
                <th key={d.key} className="text-center py-2 px-3 min-w-[120px]">
                  <div
                    className="h-1 rounded-full mb-2"
                    style={{ backgroundColor: d.dotColor }}
                  />
                  <span className="text-[12px] font-normal text-[#111111]">{d.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-[#dedbd6]">
              <td className="py-2 px-3 text-[#7b7b78] text-[11px] uppercase tracking-[0.6px]">Na etapa</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-2 px-3">
                  <span className="text-[14px] font-normal text-[#111111]">{d.count}</span>
                  <br />
                  <span className="text-[11px] text-[#7b7b78]">{fmt(d.value)}</span>
                </td>
              ))}
            </tr>
            <tr className="border-t border-[#dedbd6]">
              <td className="py-2 px-3 text-[#7b7b78] text-[11px] uppercase tracking-[0.6px]">Entrou na etapa</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-2 px-3">
                  <span className={`text-[14px] font-normal ${d.entered > 0 ? "text-[#0bdf50]" : "text-[#7b7b78]"}`}>
                    {d.entered > 0 ? `+${d.entered}` : "0"}
                  </span>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#dedbd6] flex items-center gap-4">
        <span className="text-[11px] text-[#7b7b78] uppercase tracking-[0.6px]">Perdidos no periodo:</span>
        <span className="text-[14px] font-normal text-[#c41c1c]">{lost.length} deals</span>
        <span className="text-[12px] text-[#7b7b78]">{fmt(lostValue)}</span>
      </div>
    </div>
  );
}

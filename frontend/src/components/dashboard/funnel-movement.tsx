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
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <h3
          className="text-[13px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-secondary)" }}
        >
          Movimentacao do Pipeline
        </h3>
        <div className="flex gap-1">
          {periods.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${
                period === p.key
                  ? "bg-[#1f1f1f] text-white"
                  : "text-[#5f6368] hover:bg-[#f6f7ed]"
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
              <th className="text-left py-2 px-3 text-[#9ca3af] font-medium uppercase tracking-wider text-[11px]" />
              {data.map((d) => (
                <th key={d.key} className="text-center py-2 px-3 min-w-[120px]">
                  <div className={`h-1 rounded-full mb-2 ${d.color}`} />
                  <span className="text-[12px] font-semibold text-[#1f1f1f]">{d.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-[#e5e5dc]">
              <td className="py-2 px-3 text-[#9ca3af] text-[11px] uppercase">Na etapa</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-2 px-3">
                  <span className="text-[14px] font-bold text-[#1f1f1f]">{d.count}</span>
                  <br />
                  <span className="text-[11px] text-[#5f6368]">{fmt(d.value)}</span>
                </td>
              ))}
            </tr>
            <tr className="border-t border-[#e5e5dc]">
              <td className="py-2 px-3 text-[#9ca3af] text-[11px] uppercase">Entrou na etapa</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-2 px-3">
                  <span className={`text-[14px] font-bold ${d.entered > 0 ? "text-[#2d6a3f]" : "text-[#9ca3af]"}`}>
                    {d.entered > 0 ? `+${d.entered}` : "0"}
                  </span>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#e5e5dc] flex items-center gap-4">
        <span className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Perdidos no periodo:</span>
        <span className="text-[14px] font-bold text-[#a33]">{lost.length} deals</span>
        <span className="text-[12px] text-[#5f6368]">{fmt(lostValue)}</span>
      </div>
    </div>
  );
}

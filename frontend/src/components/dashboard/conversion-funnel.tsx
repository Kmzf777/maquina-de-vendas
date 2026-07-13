"use client";

import type { DashboardConversion } from "./types";
import { FunnelBars } from "./funnel-bars";
import { fmtPct } from "./format";

/**
 * Bloco "Conversão fim-a-fim": coorte de leads do período → handoff → ganho.
 * handoff_rate e win_rate vêm prontos da rota (sobre o total de leads);
 * a taxa handoff→ganho é derivada localmente com guarda de divisão por zero.
 */
export function ConversionFunnel({ data }: { data: DashboardConversion }) {
  const handoffToWon = data.with_handoff > 0 ? data.won / data.with_handoff : 0;

  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      <FunnelBars
        stages={[
          { label: "Leads", count: data.leads_total },
          {
            label: "Handoff",
            count: data.with_handoff,
            rateFromPrev: `${fmtPct(data.handoff_rate)} dos leads chegam a handoff`,
          },
          {
            label: "Ganho",
            count: data.won,
            rateFromPrev: `${fmtPct(handoffToWon)} dos handoffs viram ganho`,
          },
        ]}
      />
      <p className="mt-4 pt-3 border-t border-[#f0ede8] text-[12px] text-[#7b7b78]">
        Fim-a-fim: {fmtPct(data.win_rate)} dos leads criados no período viram ganho.
      </p>
    </div>
  );
}

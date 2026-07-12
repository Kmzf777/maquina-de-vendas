"use client";

import type { DashboardOutbound } from "./types";
import { FunnelBars } from "./funnel-bars";
import { fmtPct } from "./format";

/**
 * Bloco "Outbound Frio": funil Enviado → Entregue → Respondeu dos disparos
 * com templates `utilidade_*`. delivery_rate e reply_rate são ambos sobre os
 * ENVIADOS (contrato da rota) — o rótulo deixa a base explícita.
 */
export function OutboundFunnel({ data }: { data: DashboardOutbound }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      <FunnelBars
        stages={[
          { label: "Enviado", count: data.sent },
          {
            label: "Entregue",
            count: data.delivered,
            rateFromPrev: `${fmtPct(data.delivery_rate)} de entrega`,
          },
          {
            label: "Respondeu",
            count: data.replied,
            rateFromPrev: `${fmtPct(data.reply_rate)} de resposta (sobre enviados)`,
          },
        ]}
      />
      <p className="mt-4 pt-3 border-t border-[#f0ede8] text-[12px] text-[#7b7b78]">
        Disparos com templates utilidade_* no período.
      </p>
    </div>
  );
}

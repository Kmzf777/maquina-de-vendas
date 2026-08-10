"use client";
import type { CampaignRow } from "@/components/trafego/campaign-report-table";

const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtInt = (v: number) => v.toLocaleString("pt-BR");
const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
const fmtRoas = (v: number | null) =>
  v == null
    ? "—"
    : `${v.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}x`;

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 flex flex-col gap-1">
      <div className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">{label}</div>
      <div
        className="text-[22px] md:text-[26px] font-normal text-[#111111] mt-1 tabular-nums leading-none"
        style={{ letterSpacing: "-0.5px" }}
      >
        {value}
      </div>
    </div>
  );
}

export function CampaignKpis({ summary }: { summary: CampaignRow }) {
  const hasSpend = summary.investimento > 0 || summary.roas != null;
  const cards: { label: string; value: string }[] = [
    { label: "Leads", value: fmtInt(summary.leads) },
    { label: "Conversas", value: fmtInt(summary.conversas) },
    { label: "Foi pro closer", value: fmtInt(summary.closer) },
    { label: "Clientes", value: fmtInt(summary.clientes) },
    { label: "Pedidos", value: fmtInt(summary.pedidos) },
    { label: "Receita", value: fmtBRL(summary.receita) },
    { label: "Ticket médio", value: fmtBRL(summary.ticket_medio) },
    { label: "Conversão", value: fmtPct(summary.conversao) },
    ...(hasSpend
      ? [
          { label: "Investimento", value: fmtBRL(summary.investimento) },
          { label: "ROAS", value: fmtRoas(summary.roas) },
        ]
      : []),
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {cards.map(c => <Card key={c.label} {...c} />)}
    </div>
  );
}

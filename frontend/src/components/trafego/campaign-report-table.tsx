"use client";

import { Fragment } from "react";
import { TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export type CampaignRow = {
  channel: string; campaign: string; leads: number; conversas: number;
  closer: number; clientes: number; pedidos: number; receita: number;
  investimento: number; roas: number | null; ticket_medio: number; conversao: number;
};

export type ReportTotal = { leads: number; conversas: number; closer: number; clientes: number; pedidos: number; receita: number; investimento: number; roas: number | null };

export type ChannelSubtotal = { leads: number; conversas: number; closer: number; clientes: number; pedidos: number; receita: number; investimento: number; roas: number | null };
export type ChannelSubtotals = Record<string, ChannelSubtotal>;

const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
const fmtInt = (v: number) => v.toLocaleString("pt-BR");
const fmtRoas = (v: number | null) => (v == null ? "—" : `${v.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}x`);

// Cabeçalho fixo no scroll: cada <th> é sticky top-0 com fundo sólido (cobre as linhas
// que passam por baixo) e z-index acima do corpo. Base compartilhada p/ manter DRY.
const TH = "sticky top-0 z-20 bg-white border-b border-[#dedbd6] text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]";

/** Cores de canal alinhadas à paleta do projeto (laranja p/ pago, verde p/ orgânico, neutro p/ sem rastreio). */
const CHANNEL_STYLES: Record<string, string> = {
  "Google Ads": "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20",
  "Meta Ads": "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20",
  "Orgânico": "bg-[#0bdf50]/10 text-[#0f9d43] border-[#0bdf50]/20",
  "Sem rastreio": "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
};

function ChannelBadge({ channel }: { channel: string }) {
  const style = CHANNEL_STYLES[channel] ?? CHANNEL_STYLES["Sem rastreio"];
  return (
    <span className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-[4px] border whitespace-nowrap ${style}`}>
      {channel}
    </span>
  );
}

export function CampaignReportTable({ rows, total, subtotals = {}, onRowClick }: {
  rows: CampaignRow[];
  total?: ReportTotal;
  subtotals?: ChannelSubtotals;
  onRowClick: (r: CampaignRow) => void;
}) {
  if (rows.length === 0) {
    return <p className="text-[14px] text-[#7b7b78] py-8 text-center">Nenhuma campanha no período.</p>;
  }
  const totalConversao = total && total.leads > 0 ? total.clientes / total.leads : 0;
  const totalTicket = total && total.pedidos > 0 ? total.receita / total.pedidos : 0;
  return (
    // Painel com scroll PRÓPRIO: este div é o container de scroll (não a página), então o
    // thead sticky top-0 cola rente ao topo do painel e as linhas passam por baixo — sem
    // header "voador". <table> nativo em vez do wrapper shadcn (que usa overflow-x-auto e
    // criaria um scroll-context extra, quebrando o sticky).
    <div className="flex-1 min-h-0 overflow-auto">
    <table className="w-full caption-bottom text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className={TH}>Canal</TableHead>
          <TableHead className={TH}>Campanha</TableHead>
          <TableHead className={`${TH} text-right`}>Leads</TableHead>
          <TableHead className={`${TH} text-right`}>Conversas</TableHead>
          <TableHead className={`${TH} text-right`}>Closer</TableHead>
          <TableHead className={`${TH} text-right`}>Clientes</TableHead>
          <TableHead className={`${TH} text-right`}>Pedidos</TableHead>
          <TableHead className={`${TH} text-right`}>Receita</TableHead>
          <TableHead className={`${TH} text-right`}>Investimento</TableHead>
          <TableHead className={`${TH} text-right`}>ROAS</TableHead>
          <TableHead className={`${TH} text-right`}>Ticket</TableHead>
          <TableHead className={`${TH} text-right`}>Conversão</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => {
          const isGroupEnd = i === rows.length - 1 || rows[i + 1].channel !== r.channel;
          const sub = subtotals[r.channel];
          const subTicket = sub && sub.pedidos > 0 ? sub.receita / sub.pedidos : 0;
          const subConversao = sub && sub.leads > 0 ? sub.clientes / sub.leads : 0;
          return (
            <Fragment key={`${r.channel}-${r.campaign}-${i}`}>
              <TableRow
                className="cursor-pointer border-[#dedbd6] hover:bg-[#faf9f6]"
                onClick={() => onRowClick(r)}
              >
                <TableCell><ChannelBadge channel={r.channel} /></TableCell>
                <TableCell className="text-[14px] text-[#111111] font-medium max-w-[240px] truncate">{r.campaign}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtInt(r.leads)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] tabular-nums">{fmtInt(r.conversas)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] tabular-nums">{fmtInt(r.closer)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtInt(r.clientes)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtInt(r.pedidos)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtBRL(r.receita)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{r.investimento > 0 ? fmtBRL(r.investimento) : "—"}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtRoas(r.roas)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#7b7b78] tabular-nums">{fmtBRL(r.ticket_medio)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtPct(r.conversao)}</TableCell>
              </TableRow>
              {isGroupEnd && sub && (
                <TableRow className="bg-[#faf9f6] border-[#dedbd6] hover:bg-[#faf9f6]">
                  <TableCell colSpan={2} className="text-[12px] font-medium text-[#7b7b78]">
                    Subtotal · {r.channel}
                  </TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtInt(sub.leads)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtInt(sub.conversas)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtInt(sub.closer)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtInt(sub.clientes)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtInt(sub.pedidos)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtBRL(sub.receita)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{r.channel === "Google Ads" ? fmtBRL(sub.investimento) : "—"}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtRoas(sub.roas)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtBRL(subTicket)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtPct(subConversao)}</TableCell>
                </TableRow>
              )}
            </Fragment>
          );
        })}
      </TableBody>
      {total && (
        <TableFooter className="bg-[#faf9f6] border-t border-[#dedbd6]">
          <TableRow className="hover:bg-transparent">
            <TableCell className="text-[13px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]" colSpan={2}>Total</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtInt(total.leads)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtInt(total.conversas)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtInt(total.closer)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtInt(total.clientes)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtInt(total.pedidos)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtBRL(total.receita)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{total.investimento > 0 ? fmtBRL(total.investimento) : "—"}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtRoas(total.roas)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtBRL(totalTicket)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtPct(totalConversao)}</TableCell>
          </TableRow>
        </TableFooter>
      )}
    </table>
    </div>
  );
}

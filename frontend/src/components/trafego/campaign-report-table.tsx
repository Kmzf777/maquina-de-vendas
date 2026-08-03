"use client";

import { Fragment } from "react";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export type CampaignRow = {
  channel: string; campaign: string; leads: number; conversas: number;
  closer: number; vendas: number; receita: number; ticket_medio: number; conversao: number;
};

export type ReportTotal = { leads: number; conversas: number; closer: number; vendas: number; receita: number };

export type ChannelSubtotal = { leads: number; conversas: number; closer: number; vendas: number; receita: number };
export type ChannelSubtotals = Record<string, ChannelSubtotal>;

const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
const fmtInt = (v: number) => v.toLocaleString("pt-BR");

/** Cores de canal alinhadas à paleta do projeto (laranja p/ pago, verde p/ orgânico, neutro p/ direto). */
const CHANNEL_STYLES: Record<string, string> = {
  "Google Ads": "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20",
  "Meta Ads": "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20",
  "Orgânico": "bg-[#0bdf50]/10 text-[#0f9d43] border-[#0bdf50]/20",
  "Direto": "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
};

function ChannelBadge({ channel }: { channel: string }) {
  const style = CHANNEL_STYLES[channel] ?? CHANNEL_STYLES["Direto"];
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
  const totalConversao = total && total.leads > 0 ? total.vendas / total.leads : 0;
  const totalTicket = total && total.vendas > 0 ? total.receita / total.vendas : 0;
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Canal</TableHead>
          <TableHead className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Campanha</TableHead>
          <TableHead className="text-right text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Leads</TableHead>
          <TableHead className="text-right text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Conversas</TableHead>
          <TableHead className="text-right text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Closer</TableHead>
          <TableHead className="text-right text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Vendas</TableHead>
          <TableHead className="text-right text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Receita</TableHead>
          <TableHead className="text-right text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Ticket</TableHead>
          <TableHead className="text-right text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Conversão</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => {
          const isGroupEnd = i === rows.length - 1 || rows[i + 1].channel !== r.channel;
          const sub = subtotals[r.channel];
          const subTicket = sub && sub.vendas > 0 ? sub.receita / sub.vendas : 0;
          const subConversao = sub && sub.leads > 0 ? sub.vendas / sub.leads : 0;
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
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtInt(r.vendas)}</TableCell>
                <TableCell className="text-right text-[14px] text-[#111111] tabular-nums">{fmtBRL(r.receita)}</TableCell>
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
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtInt(sub.vendas)}</TableCell>
                  <TableCell className="text-right text-[13px] font-medium text-[#111111] tabular-nums">{fmtBRL(sub.receita)}</TableCell>
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
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtInt(total.vendas)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtBRL(total.receita)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtBRL(totalTicket)}</TableCell>
            <TableCell className="text-right text-[14px] font-medium text-[#111111] tabular-nums">{fmtPct(totalConversao)}</TableCell>
          </TableRow>
        </TableFooter>
      )}
    </Table>
  );
}

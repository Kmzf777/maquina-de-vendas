"use client";
import { useState } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";

export type CampaignLead = {
  lead_id: string; name: string | null; phone: string | null; created_at: string | null;
  utm_source: string | null; utm_medium: string | null; utm_campaign: string | null;
  traffic_type: string | null; conversou: boolean; stage: string | null;
  comprou: boolean; valor: number; sold_at: string | null;
};

const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtDate = (v: string | null) => {
  if (!v) return "—";
  try { return new Date(v).toLocaleDateString("pt-BR"); } catch { return "—"; }
};

function OriginBadge({ trafficType }: { trafficType: string | null }) {
  const isPaid = trafficType === "paid";
  const isOrganic = trafficType === "organic";
  const style = isPaid
    ? "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20"
    : isOrganic
      ? "bg-[#0bdf50]/10 text-[#0f9d43] border-[#0bdf50]/20"
      : "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]";
  return (
    <span className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-[4px] border whitespace-nowrap ${style}`}>
      {isPaid ? "Pago" : isOrganic ? "Orgânico" : "—"}
    </span>
  );
}

export function CampaignLeadsTable({ leads }: { leads: CampaignLead[] }) {
  const [q, setQ] = useState("");
  const norm = (s: string) => s.toLowerCase();
  const filtered = q
    ? leads.filter(l => norm(`${l.name ?? ""} ${l.phone ?? ""}`).includes(norm(q)))
    : leads;

  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
      <div className="p-3 border-b border-[#dedbd6] flex items-center justify-between gap-3">
        <Input
          placeholder="Buscar por nome ou telefone…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="max-w-xs text-[14px]"
        />
        {filtered.length !== leads.length && (
          <span className="text-[12px] text-[#7b7b78] whitespace-nowrap">
            {filtered.length} de {leads.length}
          </span>
        )}
        {filtered.length === leads.length && leads.length > 0 && (
          <span className="text-[12px] text-[#7b7b78] whitespace-nowrap">
            {leads.length} lead{leads.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
      <div className="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {["Lead", "Origem", "Fonte", "Meio", "Etapa", "Conversou", "Entrada", "Venda"].map(h => (
                <TableHead key={h} className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78] whitespace-nowrap">
                  {h}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-[14px] text-[#7b7b78] py-8">
                  Nenhum lead nesta campanha.
                </TableCell>
              </TableRow>
            ) : filtered.map(l => (
              <TableRow key={l.lead_id} className="border-[#dedbd6] hover:bg-[#faf9f6]">
                <TableCell className="text-[14px] text-[#111111] font-medium max-w-[200px] truncate">
                  {l.name || l.phone || l.lead_id}
                </TableCell>
                <TableCell>
                  <OriginBadge trafficType={l.traffic_type} />
                </TableCell>
                <TableCell className="text-[13px] text-[#7b7b78]">{l.utm_source || "—"}</TableCell>
                <TableCell className="text-[13px] text-[#7b7b78]">{l.utm_medium || "—"}</TableCell>
                <TableCell className="text-[13px] text-[#7b7b78]">{l.stage || "—"}</TableCell>
                <TableCell className="text-[13px] text-[#7b7b78]">{l.conversou ? "Sim" : "Não"}</TableCell>
                <TableCell className="text-[13px] tabular-nums text-[#7b7b78]">{fmtDate(l.created_at)}</TableCell>
                <TableCell className={`text-[13px] tabular-nums ${l.comprou ? "text-[#111111] font-medium" : "text-[#7b7b78]"}`}>
                  {l.comprou
                    ? <><span className="text-[#7b7b78] font-normal">{fmtDate(l.sold_at)} </span>{fmtBRL(l.valor)}</>
                    : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

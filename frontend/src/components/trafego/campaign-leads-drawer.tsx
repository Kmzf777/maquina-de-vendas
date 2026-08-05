"use client";

import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

export type CampaignLead = {
  lead_id: string; name: string | null; phone: string | null; created_at: string | null;
  utm_source: string | null; utm_medium: string | null; utm_campaign: string | null;
  traffic_type: string | null; conversou: boolean; stage: string | null;
  comprou: boolean; valor: number; sold_at: string | null;
};

const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtDate = (v: string | null): string => {
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
  const label = isPaid ? "Pago" : isOrganic ? "Orgânico" : "—";
  return (
    <span className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-[4px] border whitespace-nowrap ${style}`}>
      {label}
    </span>
  );
}

export function CampaignLeadsDrawer({ channel, campaign, period, mode, dateFrom, dateTo, onClose }: {
  channel: string | null; campaign: string | null; period: string; mode: string;
  dateFrom?: string; dateTo?: string; onClose: () => void;
}) {
  const [leads, setLeads] = useState<CampaignLead[]>([]);
  const [loading, setLoading] = useState(false);
  const open = channel !== null && campaign !== null;

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    const params: Record<string, string> = { channel: channel!, campaign: campaign!, period, mode };
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    const qs = new URLSearchParams(params).toString();
    fetch(`/api/traffic/leads?${qs}`)
      .then(r => r.json())
      .then(d => setLeads(Array.isArray(d.leads) ? d.leads : []))
      .catch(() => setLeads([]))
      .finally(() => setLoading(false));
  }, [open, channel, campaign, period, mode, dateFrom, dateTo]);

  const compradores = leads.filter((l) => l.comprou).length;

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto p-0">
        <SheetHeader className="border-b border-[#dedbd6] px-5 py-4">
          <SheetTitle style={{ letterSpacing: "-0.3px" }} className="text-[18px] font-medium text-[#111111]">
            {channel} · {campaign}
          </SheetTitle>
          <SheetDescription className="text-[13px] text-[#7b7b78]">
            {leads.length} lead{leads.length === 1 ? "" : "s"}
            {compradores > 0 ? ` · ${compradores} comprador${compradores === 1 ? "" : "es"}` : ""}
          </SheetDescription>
        </SheetHeader>
        <div className="px-5 py-4">
          {loading ? (
            <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
          ) : leads.length === 0 ? (
            <p className="text-[14px] text-[#7b7b78] py-8 text-center">Nenhum lead nesta campanha.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Lead</TableHead>
                  <TableHead className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Origem</TableHead>
                  <TableHead className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Etapa</TableHead>
                  <TableHead className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Entrada</TableHead>
                  <TableHead className="text-right text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">Venda</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {leads.map((l) => (
                  <TableRow key={l.lead_id} className="border-[#dedbd6] hover:bg-[#faf9f6]">
                    <TableCell className="text-[14px] text-[#111111] font-medium max-w-[160px] truncate">{l.name || l.phone || l.lead_id}</TableCell>
                    <TableCell><OriginBadge trafficType={l.traffic_type} /></TableCell>
                    <TableCell className="text-[14px] text-[#7b7b78]">{l.stage || "—"}</TableCell>
                    <TableCell className="text-[13px] tabular-nums text-[#7b7b78]">{fmtDate(l.created_at)}</TableCell>
                    <TableCell className={`text-right text-[13px] tabular-nums ${l.comprou ? "text-[#111111] font-medium" : "text-[#7b7b78]"}`}>
                      {l.comprou ? <><span className="text-[#7b7b78] font-normal">{fmtDate(l.sold_at)} </span>{fmtBRL(l.valor)}</> : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

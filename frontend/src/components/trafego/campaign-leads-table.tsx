"use client";
import { useState, type ReactNode } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { CampaignLeadPanel } from "@/components/trafego/campaign-lead-panel";
import type { AtribuicaoManual } from "@/components/trafego/campaign-attribution";
import { stageLabel } from "@/lib/lead-overview";

export type PrimeiraOrigem = {
  canal: string | null; campanha_id: string | null; campanha_nome: string | null; occurred_at: string | null;
};

export type CampaignLead = {
  lead_id: string; name: string | null; phone: string | null; created_at: string | null;
  utm_source: string | null; utm_medium: string | null; utm_campaign: string | null;
  traffic_type: string | null; conversou: boolean; stage: string | null;
  comprou: boolean; valor: number; sold_at: string | null;
  // Call de 01/10 (P2). Opcionais: backend anterior ao P2 não os manda.
  canal?: string | null;
  atribuicao_manual?: boolean;
  campanha_manual_canal?: "meta" | "google" | null;
  campanha_manual_id?: string | null;
  campanha_manual_nome?: string | null;
  ja_era_cliente?: boolean | null;
  ja_era_cliente_fonte?: "auto" | "vendedor" | null;
  compras?: number;
  primeira_origem?: PrimeiraOrigem | null;
};

const HEADERS = [
  "Lead", "Origem", "Fonte", "Meio", "Etapa", "Conversou",
  "Já era cliente", "Compras", "Primeira origem", "Entrada", "Venda",
];

const fmtBRL = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
const fmtDate = (v: string | null) => {
  if (!v) return "—";
  try { return new Date(v).toLocaleDateString("pt-BR"); } catch { return "—"; }
};

/** Sim / Não / —. O sistema nunca marca "não" sozinho (P0): "—" é "ninguém sabe ainda". */
export function jaEraClienteTexto(v: boolean | null | undefined): string {
  return v === true ? "Sim" : v === false ? "Não" : "—";
}

/** Primeira entrada da linha do tempo; sem ela, o canal atual marcado como "(atual)". */
export function primeiraOrigemTexto(
  l: Pick<CampaignLead, "primeira_origem" | "canal">,
): { texto: string; atual: boolean } {
  const o = l.primeira_origem;
  if (o && (o.canal || o.campanha_nome)) {
    return { texto: [o.canal, o.campanha_nome].filter(Boolean).join(" · "), atual: false };
  }
  return l.canal ? { texto: l.canal, atual: true } : { texto: "—", atual: false };
}

function Selo({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex items-center text-[10px] font-medium uppercase tracking-[0.4px] px-1.5 py-px rounded-[3px] border bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6] whitespace-nowrap"
    >
      {children}
    </span>
  );
}

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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Atribuição feita no painel aparece na hora (selo manual); os totais recalculam ao recarregar.
  const [overrides, setOverrides] = useState<Record<string, Partial<CampaignLead>>>({});
  const rows = leads.map(l => (overrides[l.lead_id] ? { ...l, ...overrides[l.lead_id] } : l));
  const norm = (s: string) => s.toLowerCase();
  const filtered = q
    ? rows.filter(l => norm(`${l.name ?? ""} ${l.phone ?? ""}`).includes(norm(q)))
    : rows;
  const selected = rows.find(l => l.lead_id === selectedId) ?? null;
  const onAttributionChange = (leadId: string, a: AtribuicaoManual) =>
    setOverrides(prev => ({ ...prev, [leadId]: { ...prev[leadId], ...a } }));

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
              {HEADERS.map(h => (
                <TableHead key={h} className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78] whitespace-nowrap">
                  {h}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={HEADERS.length} className="text-center text-[14px] text-[#7b7b78] py-8">
                  Nenhum lead nesta campanha.
                </TableCell>
              </TableRow>
            ) : filtered.map(l => {
              const origem = primeiraOrigemTexto(l);
              return (
                <TableRow
                  key={l.lead_id}
                  // A linha inteira abre o painel para quem usa mouse; o botão na
                  // primeira célula é o alvo real de teclado e leitor de tela.
                  // Trocar o <tr> por role="button" resolveria o clique e quebraria
                  // a semântica da tabela — que é o que faz a leitura por coluna
                  // funcionar.
                  onClick={() => setSelectedId(l.lead_id)}
                  data-state={selectedId === l.lead_id ? "selected" : undefined}
                  className="border-[#dedbd6] hover:bg-[#faf9f6] data-[state=selected]:bg-[#f0ede8] cursor-pointer"
                >
                  <TableCell className="text-[14px] text-[#111111] font-medium max-w-[220px]">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setSelectedId(l.lead_id); }}
                        className="block min-w-0 truncate text-left hover:underline underline-offset-2 focus:outline-none focus-visible:ring-1 focus-visible:ring-[#111111] rounded-[2px]"
                      >
                        {l.name || l.phone || l.lead_id}
                      </button>
                      {l.atribuicao_manual && <Selo title="Campanha atribuída à mão no /trafego">manual</Selo>}
                    </div>
                  </TableCell>
                  <TableCell>
                    <OriginBadge trafficType={l.traffic_type} />
                  </TableCell>
                  <TableCell className="text-[13px] text-[#7b7b78]">{l.utm_source || "—"}</TableCell>
                  <TableCell className="text-[13px] text-[#7b7b78]">{l.utm_medium || "—"}</TableCell>
                  <TableCell className="text-[13px] text-[#7b7b78]">{stageLabel(l.stage)}</TableCell>
                  <TableCell className="text-[13px] text-[#7b7b78]">{l.conversou ? "Sim" : "Não"}</TableCell>
                  <TableCell className="text-[13px] text-[#7b7b78] whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5">
                      <span>{jaEraClienteTexto(l.ja_era_cliente)}</span>
                      {l.ja_era_cliente != null && l.ja_era_cliente_fonte === "auto" && (
                        <Selo title="Marcado pelo sistema: há venda anterior à entrada do lead">auto</Selo>
                      )}
                    </span>
                  </TableCell>
                  <TableCell className="text-[13px] tabular-nums text-[#7b7b78]">{l.compras ?? "—"}</TableCell>
                  <TableCell
                    className={`text-[13px] whitespace-nowrap ${origem.atual ? "text-[#b5b1aa]" : "text-[#7b7b78]"}`}
                    title={origem.atual ? "Sem entrada registrada na linha do tempo: canal atual" : undefined}
                  >
                    {origem.texto}{origem.atual ? " (atual)" : ""}
                  </TableCell>
                  <TableCell className="text-[13px] tabular-nums text-[#7b7b78]">{fmtDate(l.created_at)}</TableCell>
                  <TableCell className={`text-[13px] tabular-nums ${l.comprou ? "text-[#111111] font-medium" : "text-[#7b7b78]"}`}>
                    {l.comprou
                      ? <><span className="text-[#7b7b78] font-normal">{fmtDate(l.sold_at)} </span>{fmtBRL(l.valor)}</>
                      : "—"}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <CampaignLeadPanel
        target={selected}
        onClose={() => setSelectedId(null)}
        onAttributionChange={onAttributionChange}
      />
    </div>
  );
}

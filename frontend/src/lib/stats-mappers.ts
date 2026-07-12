// Mappers puros: linha(s) crua(s) de RPC (stats_costs_*/stats_whatsapp_*) -> JSON de
// resposta das rotas /api/stats/*. Gap-fill, preços de WhatsApp e arredondamentos
// espelham byte-a-byte o JS que antes agregava no cliente (ver
// scratchpad/stats-rpc-contract.md). Nenhuma dependência de Next/Supabase aqui —
// só para as rotas conseguirem chamar sb.rpc(...) e mapear o resultado.

const MARKETING_PRICE = 0.0617;
const UTILITY_PRICE = 0.0067;

// Conversão USD→BRL "de fatura" para o custo de IA: câmbio médio + impostos embutidos
// pelo Google Cloud Brasil (IOF/ISS). Derivado da conciliação real de 11/07/2026:
// $2,39 rastreados no token_usage ⇒ R$ 13,70 na fatura ⇒ multiplicador efetivo ~5,73.
// É ESTIMATIVA de conciliação, não cotação — ajustável via env CUSTO_IA_MULTIPLICADOR_BRL
// (lido na rota, server-side) quando câmbio/imposto mudarem.
export const DEFAULT_USD_TO_BRL_WITH_TAX = 5.73;

/** Parse defensivo do env CUSTO_IA_MULTIPLICADOR_BRL: lixo/zero/negativo → default. */
export function resolveBrlMultiplier(raw?: string | null): number {
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : DEFAULT_USD_TO_BRL_WITH_TAX;
}

/** Formata em Real (pt-BR): 13.7 → "R$ 13,70". */
export function formatBRL(value: number): string {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(value);
}

function round6(x: number): number {
  return Math.round(x * 1e6) / 1e6;
}

function round4(x: number): number {
  return Math.round(x * 1e4) / 1e4;
}

function toNum(v: unknown): number {
  if (v === null || v === undefined) return 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

// ---------------------------------------------------------------------------
// 1) stats_costs_summary
// ---------------------------------------------------------------------------

export interface CostsSummaryRow {
  total_cost: number | string | null;
  total_calls: number | string | null;
  total_prompt_tokens: number | string | null;
  total_completion_tokens: number | string | null;
  unique_leads: number | string | null;
}

export interface CostsSummaryResponse {
  total_cost: number;
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  unique_leads: number;
  avg_cost_per_lead: number;
  /** Estimativa em R$ da fatura Google (USD × multiplicador câmbio+impostos). ADITIVO:
   * os campos em USD acima permanecem intocados — Regra de Ouro da conciliação. */
  total_cost_brl: number;
  /** Multiplicador usado (p/ rótulo/auditoria no front). */
  brl_multiplier: number;
}

export function mapCostsSummary(
  row: CostsSummaryRow | null | undefined,
  brlMultiplier: number = DEFAULT_USD_TO_BRL_WITH_TAX
): CostsSummaryResponse {
  const totalCost = toNum(row?.total_cost);
  const totalCalls = toNum(row?.total_calls);
  const totalPrompt = toNum(row?.total_prompt_tokens);
  const totalCompletion = toNum(row?.total_completion_tokens);
  const uniqueLeads = toNum(row?.unique_leads);
  const avgCostPerLead = uniqueLeads > 0 ? totalCost / uniqueLeads : 0;

  return {
    total_cost: round6(totalCost),
    total_calls: totalCalls,
    total_prompt_tokens: totalPrompt,
    total_completion_tokens: totalCompletion,
    total_tokens: totalPrompt + totalCompletion,
    unique_leads: uniqueLeads,
    avg_cost_per_lead: round6(avgCostPerLead),
    total_cost_brl: round4(totalCost * brlMultiplier),
    brl_multiplier: brlMultiplier,
  };
}

// ---------------------------------------------------------------------------
// 2) stats_costs_daily (gap-fill continua aqui, não na RPC)
// ---------------------------------------------------------------------------

export interface DailyCostRow {
  day: string;
  cost: number | string | null;
}

export interface DailyCostPoint {
  date: string;
  cost: number;
}

export function fillDailyCosts(
  rows: DailyCostRow[],
  startDate: string,
  endDate: string
): DailyCostPoint[] {
  const daily: Record<string, number> = {};
  for (const row of rows) {
    daily[row.day] = toNum(row.cost);
  }

  const data: DailyCostPoint[] = [];
  const current = new Date(startDate + "T00:00:00");
  const end = new Date(endDate + "T00:00:00");
  while (current < end) {
    const dayStr = current.toISOString().slice(0, 10);
    data.push({ date: dayStr, cost: round6(daily[dayStr] || 0) });
    current.setDate(current.getDate() + 1);
  }
  return data;
}

// ---------------------------------------------------------------------------
// 3) stats_costs_breakdown
// ---------------------------------------------------------------------------

export interface BreakdownRow {
  key: string | null;
  cost: number | string | null;
  calls: number | string | null;
  tokens: number | string | null;
}

export interface BreakdownItem {
  key: string | null;
  cost: number;
  calls: number;
  tokens: number;
}

export function mapCostsBreakdown(rows: BreakdownRow[]): BreakdownItem[] {
  return rows.map((r) => ({
    key: r.key,
    cost: round6(toNum(r.cost)),
    calls: toNum(r.calls),
    tokens: toNum(r.tokens),
  }));
}

// ---------------------------------------------------------------------------
// 4) stats_costs_top_leads (join com leads continua na rota)
// ---------------------------------------------------------------------------

export interface TopLeadRow {
  lead_id: string;
  cost: number | string | null;
  calls: number | string | null;
  tokens: number | string | null;
  stage: string | null;
}

export interface LeadInfo {
  id: string;
  name: string | null;
  phone: string | null;
}

export interface TopLeadItem {
  lead_id: string;
  cost: number;
  calls: number;
  tokens: number;
  stage: string | null;
  name: string;
  phone: string;
}

export function mapTopLeads(rows: TopLeadRow[], leadInfos: LeadInfo[]): TopLeadItem[] {
  const leadMap = Object.fromEntries(leadInfos.map((l) => [l.id, l]));
  return rows.map((r) => {
    const info = leadMap[r.lead_id];
    return {
      lead_id: r.lead_id,
      cost: round6(toNum(r.cost)),
      calls: toNum(r.calls),
      tokens: toNum(r.tokens),
      stage: r.stage,
      name: info?.name || info?.phone || "Desconhecido",
      phone: info?.phone || "",
    };
  });
}

// ---------------------------------------------------------------------------
// 5) stats_whatsapp_summary (preços continuam na rota)
// ---------------------------------------------------------------------------

export interface WhatsappSummaryRow {
  marketing_count: number | string | null;
  utility_count: number | string | null;
}

export interface WhatsappSummaryResponse {
  marketing_count: number;
  marketing_cost: number;
  utility_count: number;
  utility_cost: number;
  total_whatsapp_cost: number;
  truncated: boolean;
}

export function mapWhatsappSummary(
  row: WhatsappSummaryRow | null | undefined
): WhatsappSummaryResponse {
  const marketingCount = toNum(row?.marketing_count);
  const utilityCount = toNum(row?.utility_count);

  return {
    marketing_count: marketingCount,
    marketing_cost: round4(marketingCount * MARKETING_PRICE),
    utility_count: utilityCount,
    utility_cost: round4(utilityCount * UTILITY_PRICE),
    total_whatsapp_cost: round4(marketingCount * MARKETING_PRICE + utilityCount * UTILITY_PRICE),
    // agregação no servidor não trunca (sem .limit(10000) no client)
    truncated: false,
  };
}

// ---------------------------------------------------------------------------
// 6) stats_whatsapp_daily (gap-fill + preços continuam na rota)
// ---------------------------------------------------------------------------

export interface WhatsappDailyRow {
  day: string;
  marketing_count: number | string | null;
  utility_count: number | string | null;
}

export interface WhatsappDailyPoint {
  date: string;
  marketing_cost: number;
  utility_cost: number;
  total: number;
}

export function fillWhatsappDaily(
  rows: WhatsappDailyRow[],
  startDate: string,
  endDate: string
): WhatsappDailyPoint[] {
  const daily: Record<string, { marketingCost: number; utilityCost: number }> = {};
  for (const row of rows) {
    daily[row.day] = {
      marketingCost: toNum(row.marketing_count) * MARKETING_PRICE,
      utilityCost: toNum(row.utility_count) * UTILITY_PRICE,
    };
  }

  const data: WhatsappDailyPoint[] = [];
  const current = new Date(startDate + "T00:00:00");
  const end = new Date(endDate + "T00:00:00");
  while (current < end) {
    const dayStr = current.toISOString().slice(0, 10);
    const d = daily[dayStr] ?? { marketingCost: 0, utilityCost: 0 };
    data.push({
      date: dayStr,
      marketing_cost: round4(d.marketingCost),
      utility_cost: round4(d.utilityCost),
      total: round4(d.marketingCost + d.utilityCost),
    });
    current.setDate(current.getDate() + 1);
  }
  return data;
}

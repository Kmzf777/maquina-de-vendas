// Mappers puros das RPCs do dashboard principal (20260712_dashboard_rpcs.sql) ->
// JSON das rotas /api/dashboard/*. Mesmo padrão de stats-mappers: sem Next/Supabase,
// numeric/bigint do PostgREST chega como string e vira number aqui; divisões por zero
// viram 0/null para o front nunca renderizar NaN.

function toNum(v: unknown): number {
  if (v === null || v === undefined) return 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function toNumOrNull(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function rate(num: number, den: number): number {
  return den > 0 ? Math.round((num / den) * 10000) / 10000 : 0;
}

// ---------------------------------------------------------------------------
// 1) dashboard_kpis
// ---------------------------------------------------------------------------

export interface KpisRow {
  leads_new: number | string | null;
  leads_prev: number | string | null;
  active_with_ai: number | string | null;
  active_awaiting_lead: number | string | null;
  conversations_attended: number | string | null;
  handoffs: number | string | null;
  qualification_rate: number | string | null;
  sla_median_minutes: number | string | null;
  sla_p95_minutes: number | string | null;
  sla_samples: number | string | null;
  cost_per_handoff_usd: number | string | null;
  cost_per_atendimento_usd: number | string | null;
}

export interface KpisResponse {
  leads_new: number;
  leads_prev: number;
  /** % vs período anterior; null quando não há base de comparação (prev=0). */
  leads_trend_pct: number | null;
  active_with_ai: number;
  active_awaiting_lead: number;
  conversations_attended: number;
  handoffs: number;
  qualification_rate: number;
  sla_median_minutes: number | null;
  sla_p95_minutes: number | null;
  sla_samples: number;
  cost_per_handoff_usd: number | null;
  cost_per_atendimento_usd: number | null;
}

export function mapKpis(row: KpisRow | null | undefined): KpisResponse {
  const leadsNew = toNum(row?.leads_new);
  const leadsPrev = toNum(row?.leads_prev);
  return {
    leads_new: leadsNew,
    leads_prev: leadsPrev,
    leads_trend_pct:
      leadsPrev > 0 ? Math.round(((leadsNew - leadsPrev) / leadsPrev) * 1000) / 10 : null,
    active_with_ai: toNum(row?.active_with_ai),
    active_awaiting_lead: toNum(row?.active_awaiting_lead),
    conversations_attended: toNum(row?.conversations_attended),
    handoffs: toNum(row?.handoffs),
    qualification_rate: toNum(row?.qualification_rate),
    sla_median_minutes: toNumOrNull(row?.sla_median_minutes),
    sla_p95_minutes: toNumOrNull(row?.sla_p95_minutes),
    sla_samples: toNum(row?.sla_samples),
    cost_per_handoff_usd: toNumOrNull(row?.cost_per_handoff_usd),
    cost_per_atendimento_usd: toNumOrNull(row?.cost_per_atendimento_usd),
  };
}

// ---------------------------------------------------------------------------
// 2) dashboard_funnel_conversion
// ---------------------------------------------------------------------------

export interface ConversionRow {
  leads_total: number | string | null;
  with_handoff: number | string | null;
  won: number | string | null;
}

export interface ConversionResponse {
  leads_total: number;
  with_handoff: number;
  won: number;
  handoff_rate: number;
  win_rate: number;
}

export function mapConversion(row: ConversionRow | null | undefined): ConversionResponse {
  const total = toNum(row?.leads_total);
  const handoff = toNum(row?.with_handoff);
  const won = toNum(row?.won);
  return {
    leads_total: total,
    with_handoff: handoff,
    won,
    handoff_rate: rate(handoff, total),
    win_rate: rate(won, total),
  };
}

// ---------------------------------------------------------------------------
// 3) dashboard_outbound_frio
// ---------------------------------------------------------------------------

export interface OutboundRow {
  sent: number | string | null;
  delivered: number | string | null;
  replied: number | string | null;
}

export interface OutboundResponse {
  sent: number;
  delivered: number;
  replied: number;
  delivery_rate: number;
  reply_rate: number;
}

export function mapOutbound(row: OutboundRow | null | undefined): OutboundResponse {
  const sent = toNum(row?.sent);
  const delivered = toNum(row?.delivered);
  const replied = toNum(row?.replied);
  return {
    sent,
    delivered,
    replied,
    delivery_rate: rate(delivered, sent),
    reply_rate: rate(replied, sent),
  };
}

// ---------------------------------------------------------------------------
// 4) dashboard_followups
// ---------------------------------------------------------------------------

export interface FollowupsRow {
  scheduled_today: number | string | null;
  sent_today: number | string | null;
  overdue_pending: number | string | null;
  by_type: unknown;
  returns_pending: number | string | null;
  next_return_at: string | null;
}

export interface FollowupTypeItem {
  job_type: string;
  scheduled: number;
  sent: number;
}

export interface FollowupsResponse {
  scheduled_today: number;
  sent_today: number;
  overdue_pending: number;
  by_type: FollowupTypeItem[];
  returns_pending: number;
  next_return_at: string | null;
}

export function mapFollowups(row: FollowupsRow | null | undefined): FollowupsResponse {
  const raw = Array.isArray(row?.by_type) ? (row?.by_type as Record<string, unknown>[]) : [];
  return {
    scheduled_today: toNum(row?.scheduled_today),
    sent_today: toNum(row?.sent_today),
    overdue_pending: toNum(row?.overdue_pending),
    by_type: raw.map((r) => ({
      job_type: String(r.job_type ?? "?"),
      scheduled: toNum(r.scheduled),
      sent: toNum(r.sent),
    })),
    returns_pending: toNum(row?.returns_pending),
    next_return_at: row?.next_return_at ?? null,
  };
}

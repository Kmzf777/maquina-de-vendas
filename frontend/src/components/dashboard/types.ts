// Contratos das 4 rotas do dashboard principal (/api/dashboard/*).
// Fonte: spec docs/superpowers/specs/2026-07-12-fix-main-dashboard.md.
// Estes tipos espelham EXATAMENTE o JSON das rotas — não renomear campos aqui.

/** GET /api/dashboard/kpis?start=YYYY-MM-DD&end=YYYY-MM-DD */
export interface DashboardKpis {
  leads_new: number;
  leads_prev: number;
  leads_trend_pct: number | null;
  active_with_ai: number;
  active_awaiting_lead: number;
  conversations_attended: number;
  handoffs: number;
  /** 0..1 */
  qualification_rate: number;
  sla_median_minutes: number | null;
  sla_p95_minutes: number | null;
  sla_samples: number;
  cost_per_handoff_usd: number | null;
  cost_per_atendimento_usd: number | null;
}

/** GET /api/dashboard/conversion?start&end */
export interface DashboardConversion {
  leads_total: number;
  with_handoff: number;
  won: number;
  /** 0..1 — handoffs sobre o total de leads da coorte */
  handoff_rate: number;
  /** 0..1 — ganhos sobre o total de leads da coorte */
  win_rate: number;
}

/** GET /api/dashboard/outbound?start&end */
export interface DashboardOutbound {
  sent: number;
  delivered: number;
  replied: number;
  /** 0..1 — entregues sobre enviados */
  delivery_rate: number;
  /** 0..1 — respostas sobre enviados */
  reply_rate: number;
}

export interface DashboardFollowupByType {
  job_type: string;
  scheduled: number;
  sent: number;
}

/** GET /api/dashboard/followups (ignora período) */
export interface DashboardFollowups {
  scheduled_today: number;
  sent_today: number;
  overdue_pending: number;
  by_type: DashboardFollowupByType[];
  returns_pending: number;
  /** ISO 8601 ou null */
  next_return_at: string | null;
}

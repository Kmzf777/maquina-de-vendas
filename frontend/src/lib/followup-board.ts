// Helpers puros do painel do motor de Follow-up (aba Follow-up em /campanhas).
// Nota: `isCadenceTouch` de cadence-display.ts assume job_type == null, mas o motor
// grava job_type='standard' nos toques da cadência — aqui `standard|null` são toque.

export type BoardJob = {
  id: string;
  sequence: number | null;
  job_type: string | null;
  status: string;
  fire_at: string | null;
  sent_at: string | null;
  cancel_reason: string | null;
  objetivo: string | null;
  lead_id: string | null;
  lead_name: string | null;
  lead_phone: string | null;
};

export const BOARD_STATUSES = ["pending", "awaiting_reopen", "sent", "cancelled"] as const;
export type BoardStatus = (typeof BOARD_STATUSES)[number];

export const STATUS_FILTER_LABELS: Record<BoardStatus, string> = {
  pending: "Pendentes",
  awaiting_reopen: "Aguardando reabertura",
  sent: "Enviados",
  cancelled: "Cancelados",
};

const JOB_TYPE_LABELS: Record<string, string> = {
  handoff_rescue: "Resgate de handoff",
  lp_welcome: "Boas-vindas LP",
  ai_reengage: "Reengajamento IA",
  ai_scheduled_return: "Retorno agendado",
};

/** Rótulo do toque: cadência (standard|null) → "T<seq>"; especializado → nome do tipo. */
export function touchTypeLabel(job: Pick<BoardJob, "job_type" | "sequence">): string {
  const jt = job.job_type;
  if (jt == null || jt === "standard") {
    return job.sequence != null ? `T${job.sequence}` : "Toque";
  }
  return JOB_TYPE_LABELS[jt] ?? jt;
}

/** Só pending/awaiting_reopen são canceláveis pela operação — nunca sent/processing. */
export function isCancellable(job: Pick<BoardJob, "status">): boolean {
  return job.status === "pending" || job.status === "awaiting_reopen";
}

/** Instante relevante para exibição: enviado usa sent_at; o resto usa fire_at. */
export function displayInstant(job: Pick<BoardJob, "status" | "fire_at" | "sent_at">): string | null {
  return job.status === "sent" ? (job.sent_at ?? job.fire_at) : (job.fire_at ?? job.sent_at);
}

/** Data/hora curta em BRT (dd/mm HH:MM); null → "—". */
export function formatBRT(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

/** Offset da definição → rótulo humano ("mesmo dia", "+18h", "D+1", "D+6"). */
export function offsetLabel(offsetHours: number, jitterMinutes: number[] | null): string {
  if (offsetHours === 0) {
    if (jitterMinutes && jitterMinutes.length === 2) {
      const [lo, hi] = jitterMinutes;
      return `mesmo dia (+${formatMinutes(lo)}–${formatMinutes(hi)})`;
    }
    return "mesmo dia";
  }
  if (offsetHours < 24) return `+${trimZero(offsetHours)}h`;
  const days = Math.floor(offsetHours / 24);
  const rest = offsetHours - days * 24;
  return rest > 0 ? `D+${days} (+${trimZero(rest)}h)` : `D+${days}`;
}

function trimZero(n: number): string {
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 10) / 10);
}

function formatMinutes(min: number): string {
  if (min < 60) return `${min}min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h${String(m).padStart(2, "0")}` : `${h}h`;
}

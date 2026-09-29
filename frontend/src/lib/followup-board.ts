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
  // --- contexto das esteiras do João (metadata do job; rota preenche) ---
  /** `metadata.cadencia`: "novo" | "em_conversa" | "proposta" | "reposicao" | "em_atencao". */
  cadencia: string | null;
  /** `metadata.funil`: "atacado" | "private_label" | "reposicao_atacado" | … */
  funil: string | null;
  /** `metadata.toque`: número do toque dentro da esteira. */
  toque: number | null;
  /** `metadata.acao`: "mover_etapa" quando o job MOVE o card em vez de enviar mensagem. */
  acao: string | null;
  /** RÓTULO da etapa em que o card está AGORA — já resolvido pela rota. Nunca uma key. */
  etapa_atual: string | null;
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

/** Todos os job_type das esteiras do João compartilham este prefixo (joao_novo, …). */
const JOAO_JOB_TYPE_PREFIX = "joao_";

/** `metadata.acao` do job que fecha a esteira movendo o card — não é toque. */
const ACAO_MOVER_ETAPA = "mover_etapa";

/**
 * Rótulo do toque, nesta ordem:
 *  1. job que MOVE o card (`acao === "mover_etapa"`) → "move o card". Vem antes de
 *     qualquer número: o agendador grava `sequence` = último toque + 1, então sem este
 *     ramo ele apareceria como um toque que nunca existiu.
 *  2. job do João (`job_type` começa com "joao_") → "<rótulo da cadência> · <n>º toque",
 *     com o número vindo de `toque` e `sequence` como reserva. Sem rótulo (a definição
 *     ainda não carregou) → só "<n>º toque".
 *  3. o resto — cadência da ValerIA (`standard`|null) → "T<seq>"; tipos especializados →
 *     rótulo de JOB_TYPE_LABELS.
 *
 * `rotuloDaCadencia` vem de `/api/cadence/definition` — NUNCA de um mapa hardcoded aqui.
 * A chave crua do job_type não sai por nenhum caminho.
 */
export function touchTypeLabel(
  job: Pick<BoardJob, "job_type" | "sequence" | "toque" | "acao">,
  rotuloDaCadencia?: string | null,
): string {
  if (job.acao === ACAO_MOVER_ETAPA) return "move o card";

  const jt = job.job_type;

  if (jt != null && jt.startsWith(JOAO_JOB_TYPE_PREFIX)) {
    const rotulo = rotuloDaCadencia != null && rotuloDaCadencia.trim() !== "" ? rotuloDaCadencia.trim() : null;
    const numero = job.toque ?? job.sequence;
    if (numero == null) return rotulo ?? "Toque";
    return rotulo ? `${rotulo} · ${numero}º toque` : `${numero}º toque`;
  }

  if (jt == null || jt === "standard") {
    return job.sequence != null ? `T${job.sequence}` : "Toque";
  }
  return JOB_TYPE_LABELS[jt] ?? humanizarJobType(jt);
}

/** Tipo sem rótulo conhecido: mostra algo legível, nunca a chave crua ("novo_tipo"). */
function humanizarJobType(jt: string): string {
  const texto = jt.replace(/[_-]+/g, " ").trim();
  if (texto === "") return "Toque";
  return texto.charAt(0).toUpperCase() + texto.slice(1);
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

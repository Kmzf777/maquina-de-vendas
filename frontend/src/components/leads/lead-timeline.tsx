"use client";

// ── Tipos do payload de GET /api/leads/[id]/timeline ───────────────────────────────────

/** Linha de `lead_events` como a rota entrega. */
export interface TimelineEvent {
  kind: "evento";
  id: string;
  /** entrada | etapa | venda | venda_cancelada | disparo | mesclagem | atribuicao_manual | (legado) stage_change */
  event_type: string;
  /** occurred_at (quando aconteceu; no backfill ≠ inserção), ISO. */
  at: string;
  source: string | null;
  old_value: string | null;
  new_value: string | null;
  metadata: Record<string, unknown>;
}

/** Marcador diário: o cliente mandou mensagem neste dia (fuso America/Sao_Paulo). */
export interface TimelineConversou {
  kind: "conversou";
  /** `conversou:YYYY-MM-DD` */
  id: string;
  /** YYYY-MM-DD em São Paulo. */
  dia: string;
  /** Última mensagem inbound do dia (ISO) — define a posição na lista. */
  at: string;
  mensagens: number;
}

export type TimelineItem = TimelineEvent | TimelineConversou;

export interface TimelineResponse {
  /** Do mais novo para o mais antigo. */
  items: TimelineItem[];
  /** Seções que falharam: "eventos" | "conversas". */
  partial: string[];
}

export interface LeadTimelineProps {
  leadId: string;
}

export function LeadTimeline(props: LeadTimelineProps) {
  void props;
  return null;
}

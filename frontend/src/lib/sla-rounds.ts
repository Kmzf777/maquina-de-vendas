import {
  businessMinutesBetween,
  type BusinessWindow,
} from "@/lib/business-hours";

export interface SlaMessage {
  sent_by: string;       // só 'user' e 'seller' importam
  created_at: string;    // ISO
}

export interface SlaConversation {
  id: string;
  last_seller_response_at: string | null;
  messages: SlaMessage[]; // ordem cronológica, apenas 'user'/'seller'
}

export interface SellerRounds {
  closed: number[];       // minutos comerciais de rodadas respondidas
  openElapsed: number[];  // minutos comerciais decorridos de rodadas abertas
}

export interface SellerSlaResult {
  avgMinutes: number | null;
  overdueCount: number;
  worstMinutes: number | null;
}

/**
 * Percorre as conversas e extrai as rodadas de espera.
 * Rodada = primeira msg do cliente sem resposta -> primeira resposta do vendedor
 * (msg do vendedor ou Finalizar). Rajadas do cliente não reiniciam o relógio.
 */
export function collectRounds(
  conversations: SlaConversation[],
  win: BusinessWindow,
  now: Date = new Date()
): SellerRounds {
  const closed: number[] = [];
  const openElapsed: number[] = [];

  for (const conv of conversations) {
    let waitStart: string | null = null;

    for (const msg of conv.messages) {
      if (msg.sent_by === "user") {
        if (waitStart === null) waitStart = msg.created_at;
      } else if (msg.sent_by === "seller") {
        if (waitStart !== null) {
          const mins = businessMinutesBetween(new Date(waitStart), new Date(msg.created_at), win);
          if (mins >= 0) closed.push(mins);
          waitStart = null;
        }
      }
    }

    if (waitStart !== null) {
      const finalize = conv.last_seller_response_at;
      if (finalize && finalize > waitStart) {
        const mins = businessMinutesBetween(new Date(waitStart), new Date(finalize), win);
        if (mins >= 0) closed.push(mins);
      } else {
        const elapsed = businessMinutesBetween(new Date(waitStart), now, win);
        openElapsed.push(elapsed);
      }
    }
  }

  return { closed, openElapsed };
}

/** Resume rodadas em média (fechadas), pior (fechadas+abertas) e atraso (>alvo). */
export function summarizeRounds(
  rounds: SellerRounds,
  targetMinutes: number
): SellerSlaResult {
  const { closed, openElapsed } = rounds;

  const avgMinutes =
    closed.length > 0 ? closed.reduce((a, b) => a + b, 0) / closed.length : null;

  const all = [...closed, ...openElapsed];
  const worstMinutes = all.length > 0 ? Math.max(...all) : null;

  const overdueCount = openElapsed.filter((m) => m > targetMinutes).length;

  return { avgMinutes, overdueCount, worstMinutes };
}

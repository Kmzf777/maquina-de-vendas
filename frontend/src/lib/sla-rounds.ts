import {
  businessMinutesBetween,
  type BusinessWindow,
} from "@/lib/business-hours";

export interface SlaMessage {
  sent_by: string;       // 'user' abre a espera; resposta real (REPLY_SENDERS) fecha
  created_at: string;    // ISO
}

/**
 * Quem conta como "resposta real" ao cliente — encerra a rodada de espera.
 * Vendedor humano (via CRM) e a IA conversacional (ValerIA = 'agent').
 * Disparos em massa não-conversacionais (broadcast/followup/campaign/automation/
 * handoff) NÃO contam como resposta: não tiram o cliente da fila de espera.
 */
const REPLY_SENDERS = new Set(["seller", "agent"]);

export interface SlaConversation {
  id: string;
  last_seller_response_at: string | null;
  messages: SlaMessage[]; // ordem cronológica: 'user' + respostas reais ('seller'/'agent')
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

export interface OpenRound {
  conversationId: string;
  elapsedMinutes: number;
}

/**
 * Um único passe cronológico por conversa. Retorna os minutos comerciais das
 * rodadas fechadas e, se houver uma rodada aberta no fim, seus minutos decorridos.
 * Regras: rodada começa na primeira msg do cliente sem resposta; fecha na primeira
 * resposta real (msg de REPLY_SENDERS — vendedor ou IA — ou Finalizar via
 * last_seller_response_at); rajadas do cliente não reiniciam; mensagens proativas
 * ou disparos em massa (broadcast/followup/...) sem espera aberta são ignorados.
 */
function walkConversation(
  conv: SlaConversation,
  win: BusinessWindow,
  now: Date
): { closed: number[]; openElapsedMinutes: number | null } {
  const closed: number[] = [];
  let waitStart: string | null = null;

  for (const msg of conv.messages) {
    if (msg.sent_by === "user") {
      if (waitStart === null) waitStart = msg.created_at;
    } else if (REPLY_SENDERS.has(msg.sent_by)) {
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
      return { closed, openElapsedMinutes: null };
    }
    const elapsed = businessMinutesBetween(new Date(waitStart), now, win);
    return { closed, openElapsedMinutes: elapsed };
  }

  return { closed, openElapsedMinutes: null };
}

/**
 * Percorre as conversas e extrai as rodadas de espera (fechadas + aberta).
 */
export function collectRounds(
  conversations: SlaConversation[],
  win: BusinessWindow,
  now: Date = new Date()
): SellerRounds {
  const closed: number[] = [];
  const openElapsed: number[] = [];

  for (const conv of conversations) {
    const r = walkConversation(conv, win, now);
    closed.push(...r.closed);
    if (r.openElapsedMinutes !== null) openElapsed.push(r.openElapsedMinutes);
  }

  return { closed, openElapsed };
}

/**
 * Retorna só as rodadas ABERTAS, preservando o conversationId, para a seção
 * acionável "Em atraso agora". O filtro por alvo (> target) é aplicado pelo chamador.
 */
export function collectOpenRounds(
  conversations: SlaConversation[],
  win: BusinessWindow,
  now: Date = new Date()
): OpenRound[] {
  const out: OpenRound[] = [];
  for (const conv of conversations) {
    const r = walkConversation(conv, win, now);
    if (r.openElapsedMinutes !== null) {
      out.push({ conversationId: conv.id, elapsedMinutes: r.openElapsedMinutes });
    }
  }
  return out;
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

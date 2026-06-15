import {
  businessMinutesBetween,
  type BusinessWindow,
} from "@/lib/business-hours";

export interface SlaMessage {
  sent_by: string;       // 'user' = cliente; resto = nosso lado (role assistant)
  created_at: string;    // ISO
}

/**
 * Quem conta como "resposta real" ao cliente — fecha a rodada e entra no tempo
 * médio de resposta. Vendedor humano (via CRM) e a IA conversacional (ValerIA =
 * 'agent'). Disparos não-conversacionais (broadcast/followup/campaign/automation/
 * handoff) NÃO são resposta real: não entram no tempo médio. Mas, por serem
 * mensagens NOSSAS, se forem a última da conversa tiram o lead de "em atraso"
 * (a bola está com o cliente). Ver walkConversation.
 */
const REPLY_SENDERS = new Set(["seller", "agent"]);

export interface SlaConversation {
  id: string;
  last_seller_response_at: string | null;
  // ordem cronológica: cliente ('user') + TODAS as nossas mensagens (role assistant).
  // Inclui disparos — necessários para saber quem falou por último.
  messages: SlaMessage[];
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
 * Regras: rodada começa na primeira msg do cliente sem resposta; fecha (e entra no
 * tempo médio) na primeira resposta real (REPLY_SENDERS — vendedor ou IA — ou
 * Finalizar via last_seller_response_at); rajadas do cliente não reiniciam; disparos
 * são ignorados no cálculo de tempo. Só fica "em atraso" (rodada aberta) se o CLIENTE
 * foi o último a falar — se mandamos qualquer mensagem depois (disparo/follow-up),
 * a bola está com o cliente e o lead sai da fila.
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
    // Só é "em atraso" se o CLIENTE foi o último a falar. Qualquer mensagem nossa
    // depois (disparo/follow-up/etc.) significa que a bola está com o cliente.
    const last = conv.messages[conv.messages.length - 1];
    if (last && last.sent_by !== "user") {
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

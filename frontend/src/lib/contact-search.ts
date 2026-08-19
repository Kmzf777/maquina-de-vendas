import { UNREAD_TAB_KEY } from "@/lib/constants";
import { sortByLastMsgDesc } from "@/lib/conversations-live";
import type { Conversation } from "@/lib/types";

/** Abaixo disso a busca não vai ao servidor (ruído demais, resultado inútil). */
export const CONTACT_SEARCH_MIN_LEN = 2;

/**
 * True quando a conversa pertence à aba ativa. Extraído da lista para que os
 * resultados vindos do servidor passem pela MESMA regra dos locais — do
 * contrário a aba filtraria só metade da lista.
 */
export function conversationMatchesTab(conv: Conversation, activeTab: string): boolean {
  if (activeTab === UNREAD_TAB_KEY) return (conv.unread_count ?? 0) > 0;
  if (activeTab === "todos") return true;
  if (activeTab === "pessoal") return !conv.leads;
  return conv.leads?.stage === activeTab;
}

/**
 * Une os contatos já carregados na lista com os que só a busca server-side
 * encontrou (conversas fora do teto de 1.000 linhas do PostgREST).
 *
 * Em duplicata a cópia LOCAL vence: ela carrega o estado vivo (unread zerado por
 * mark-read, toggles otimistas, preview atualizado pelo realtime) que a resposta
 * do servidor desconhece.
 */
export function mergeContactResults(
  local: Conversation[],
  remote: Conversation[],
): Conversation[] {
  const seen = new Set(local.map((c) => c.id));
  const extra = remote.filter((c) => !seen.has(c.id));
  if (extra.length === 0) return sortByLastMsgDesc(local);
  return sortByLastMsgDesc([...local, ...extra]);
}

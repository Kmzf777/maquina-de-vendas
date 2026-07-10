import type { Message, QuotedMessage } from "@/lib/types";

// Janela de mensagens do chat: a thread carrega as N mais recentes e pagina
// para trás sob demanda ("Carregar anteriores"). Antes a query buscava a
// conversa INTEIRA (sem limit) — threads longas custavam egress e render.
export const MESSAGE_PAGE_SIZE = 100;

/** Página cheia ⇒ provavelmente há mais histórico atrás dela. */
export function pageHasMore(fetchedCount: number): boolean {
  return fetchedCount >= MESSAGE_PAGE_SIZE;
}

/**
 * Deduplica por id e ordena por created_at ascendente. INSERTs de tempo real chegam
 * fora de ordem (e podem colidir com o refetch), então normalizamos aqui para evitar
 * mensagens no lugar errado / duplicadas na thread.
 */
export function normalizeOrder(raw: Message[]): Message[] {
  const byId = new Map<string, Message>();
  for (const m of raw) byId.set(m.id, m);
  return [...byId.values()].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );
}

export function enrichWithQuotedMessages(raw: Message[]): Message[] {
  const wamidMap = new Map<string, Message>();
  const idMap = new Map<string, Message>();
  for (const msg of raw) {
    if (msg.wamid) wamidMap.set(msg.wamid, msg);
    idMap.set(msg.id, msg);
  }
  return raw.map((msg) => {
    const hasQuote = msg.quoted_wamid || msg.quoted_message_id;
    if (!hasQuote) return msg;
    const original =
      (msg.quoted_wamid ? wamidMap.get(msg.quoted_wamid) : undefined) ??
      (msg.quoted_message_id ? idMap.get(msg.quoted_message_id) : undefined);
    const quoted: QuotedMessage | null = original
      ? { id: original.id, content: original.content, role: original.role, message_type: original.message_type ?? null }
      : null;
    return { ...msg, quoted_message: quoted };
  });
}

/** Prepend de uma página mais antiga (asc) na janela atual, com dedup/ordenação. */
export function mergeOlderPage(current: Message[], olderAsc: Message[]): Message[] {
  return enrichWithQuotedMessages(normalizeOrder([...olderAsc, ...current]));
}

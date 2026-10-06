/**
 * Helpers puros do cache PAGINADO da lista de conversas (React Query infinite).
 *
 * A lista deixou de ser um array único (que o PostgREST cortava em 1.000 linhas) e
 * virou páginas por cursor. Os patches de tempo real continuam pensando em "a lista"
 * (`applyConversationUpdate`, `sortByLastMsgDesc`): aqui eles são aplicados sobre a
 * lista achatada e o resultado é redistribuído nas MESMAS páginas — o número de páginas
 * não muda, então um refetch traz de volta tudo o que o vendedor já tinha rolado, e o
 * cursor da última página continua sendo a fronteira do que foi carregado.
 */
import type { InfiniteData } from "@tanstack/react-query";
import type { Conversation } from "@/lib/types";
import { UNREAD_TAB_KEY } from "@/lib/constants";
import { conversationMatchesTab } from "@/lib/contact-search";
import type { ConversationRow } from "@/lib/conversations-live";
import { decodeCursor, type ConversationsPage } from "@/app/api/conversations/list-params";

// `pageParams` fica `unknown`: é o que o useInfiniteQuery infere, e nenhum helper o lê.
export type ConversationPages = InfiniteData<ConversationsPage<Conversation>, unknown>;

/** Chave do cache da lista: um cache por canal + aba. */
export function conversationsQueryKey(channelId: string, tab: string) {
  return ["conversations", channelId, tab] as const;
}

/** Lista achatada das páginas carregadas; em duplicata (conversa que mudou de página entre buscas) a primeira vence. */
export function flattenPages(data: ConversationPages | undefined): Conversation[] {
  if (!data) return [];
  const seen = new Set<string>();
  const out: Conversation[] = [];
  for (const page of data.pages) {
    for (const c of page.conversations) {
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      out.push(c);
    }
  }
  return out;
}

/**
 * Aplica `updater` à lista achatada e redistribui o resultado nas páginas existentes,
 * mantendo o tamanho de cada uma (a última absorve sobra/falta), os `next_cursor` e os
 * `pageParams`.
 */
export function patchPages(
  data: ConversationPages,
  updater: (list: Conversation[]) => Conversation[],
): ConversationPages {
  if (data.pages.length === 0) return data;
  const next = updater(flattenPages(data));
  const lastIndex = data.pages.length - 1;
  let offset = 0;
  const pages = data.pages.map((page, i) => {
    const size = i === lastIndex ? next.length : page.conversations.length;
    const slice = next.slice(offset, offset + size);
    offset += slice.length;
    return { ...page, conversations: slice };
  });
  return { ...data, pages };
}

/** Compara dois timestamps como INSTANTES ("Z" e "+00:00", frações); desc. */
function compareInstantsDesc(a: string, b: string): number {
  const x = Date.parse(a);
  const y = Date.parse(b);
  if (!Number.isNaN(x) && !Number.isNaN(y)) return y - x;
  return a < b ? 1 : a > b ? -1 : 0;
}

/**
 * Ordem da rota: `last_msg_at desc nulls last, id desc`. Negativo = `a` vem antes.
 */
export function compareConversationOrder(
  a: { id: string; last_msg_at?: string | null },
  b: { id: string; last_msg_at?: string | null },
): number {
  if (a.last_msg_at && b.last_msg_at) {
    const byTime = compareInstantsDesc(a.last_msg_at, b.last_msg_at);
    if (byTime !== 0) return byTime;
  } else if (a.last_msg_at) {
    return -1;
  } else if (b.last_msg_at) {
    return 1;
  }
  return a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
}

/**
 * `lastMsgAt` cai dentro do trecho já carregado? A fronteira é o cursor da última
 * página (o que o servidor entregou), não o último item da lista — que pode ser uma
 * conversa antiga injetada pela busca/seleção. Com `id`, o empate no timestamp da
 * fronteira é decidido como a rota decide (id desc); sem ele, empate conta como dentro.
 */
export function isWithinLoadedWindow(
  data: ConversationPages | undefined,
  lastMsgAt: string | null | undefined,
  id?: string,
): boolean {
  if (!data || data.pages.length === 0) return true;
  const boundary = decodeCursor(data.pages[data.pages.length - 1].next_cursor);
  if (!boundary) return true; // não há próxima página: tudo está carregado
  if (boundary.t === null) {
    // a fronteira já está na cauda de nulls
    if (lastMsgAt || id === undefined) return true;
    return id >= boundary.id;
  }
  if (!lastMsgAt) return false; // nulls vêm por último, depois da fronteira
  const at = Date.parse(lastMsgAt);
  const limit = Date.parse(boundary.t);
  if (Number.isNaN(at) || Number.isNaN(limit)) return true; // na dúvida, busca
  if (at !== limit) return at > limit;
  return id === undefined || id >= boundary.id;
}

/**
 * Insere `conv` na posição dela pela ordem da rota, sem reordenar o resto. Se ela já
 * está no cache, a cópia do cache vence (carrega mark-read/toggles otimistas). Mais
 * antiga que a fronteira carregada fica de fora: no fim da lista ela ficaria fora de
 * ordem (a próxima página entraria depois dela) — o fetchNextPage a trará.
 */
export function insertIntoPages(data: ConversationPages, conv: Conversation): ConversationPages {
  if (flattenPages(data).some((c) => c.id === conv.id)) return data;
  if (!isWithinLoadedWindow(data, conv.last_msg_at, conv.id)) return data;
  return patchPages(data, (list) => {
    const at = list.findIndex((c) => compareConversationOrder(conv, c) < 0);
    const next = [...list];
    next.splice(at < 0 ? next.length : at, 0, conv);
    return next;
  });
}

/**
 * UPDATE de uma conversa que NÃO está no cache da aba ativa: vale buscá-la por id?
 * A linha crua do Realtime não traz o lead, então só as abas que dependem de colunas
 * da própria conversa (não lidas, pessoal) decidem sem buscar.
 */
export function shouldFetchUnknownRow(row: ConversationRow, tab: string): boolean {
  if (tab === UNREAD_TAB_KEY) return (row.unread_count ?? 0) > 0;
  if (tab === "pessoal") return !row.lead_id;
  return true;
}

/** A conversa pertence à lista cacheada sob `key` (canal + aba)? */
export function conversationBelongsToKey(conv: Conversation, key: readonly unknown[]): boolean {
  const channelId = typeof key[1] === "string" ? key[1] : "";
  const tab = typeof key[2] === "string" ? key[2] : "todos";
  if (channelId && conv.channel_id !== channelId) return false;
  return conversationMatchesTab(conv, tab);
}

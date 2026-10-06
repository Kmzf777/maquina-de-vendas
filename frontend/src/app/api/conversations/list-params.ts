/**
 * Contrato da listagem paginada de `/api/conversations`.
 *
 * Por que existe: o PostgREST do Supabase self-hosted corta toda leitura em 1.000
 * linhas (`PGRST_DB_MAX_ROWS`), sem erro. A lista buscava tudo de uma vez e por isso
 * só cobria ~11 dias — conversas "sumiam" e a aba Não lidas mentia. Agora a lista é
 * paginada por keyset (`last_msg_at desc nulls last, id desc`), com a aba como filtro
 * de servidor.
 *
 * Puro (sem imports de servidor): usado pela rota e pela página.
 */
import { CONVERSATION_TABS, UNREAD_TAB_KEY } from "@/lib/constants";

/** Linhas por página da lista de conversas. */
export const CONVERSATIONS_PAGE_SIZE = 200;

/** Resposta de `GET /api/conversations`. */
export interface ConversationsPage<T> {
  conversations: T[];
  /** Cursor da próxima página, ou null quando não há mais nada. */
  next_cursor: string | null;
}

/** Resposta de `GET /api/conversations/counts`. */
export interface ConversationCounts {
  total: number;
  unread: number;
}

/** Posição da última linha entregue, na ordem `last_msg_at desc nulls last, id desc`. */
export interface ConversationCursor {
  /** `last_msg_at` da última linha; null = a página já está na cauda de nulls. */
  t: string | null;
  id: string;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}(:?\d{2})?)$/;

export function encodeCursor(cursor: ConversationCursor): string {
  return `${cursor.t ?? ""}|${cursor.id}`;
}

/**
 * Lê o cursor vindo da query string. Os dois pedaços são interpolados num filtro
 * PostgREST, então só passa timestamp ISO e uuid — qualquer outra coisa é null
 * (a rota responde 400).
 */
export function decodeCursor(raw: string | null | undefined): ConversationCursor | null {
  if (!raw) return null;
  const sep = raw.lastIndexOf("|");
  if (sep < 0) return null;
  const t = raw.slice(0, sep);
  const id = raw.slice(sep + 1);
  if (!UUID_RE.test(id)) return null;
  if (t && !TIMESTAMP_RE.test(t)) return null;
  return { t: t || null, id };
}

/**
 * Filtro `or=(...)` das linhas estritamente DEPOIS do cursor (com `t` não nulo):
 * mais antigas, ou empatadas no timestamp com id menor, ou da cauda de nulls.
 * O timestamp vai entre aspas porque carrega `:`, `.` e `+`.
 */
export function cursorOrFilter(t: string, id: string): string {
  return `last_msg_at.lt."${t}",and(last_msg_at.eq."${t}",id.lt.${id}),last_msg_at.is.null`;
}

export type ConversationTabFilter =
  | { kind: "all" }
  | { kind: "unread" }
  | { kind: "no_lead" }
  | { kind: "stage"; stage: string };

const STAGE_TAB_KEYS: ReadonlySet<string> = new Set(
  CONVERSATION_TABS.map((t) => t.key as string).filter((k) => k !== "todos" && k !== "pessoal"),
);

/**
 * Aba da lista → filtro de servidor. Espelha `conversationMatchesTab`
 * (`lib/contact-search.ts`), que continua no cliente para os patches de tempo real.
 * Aba desconhecida vira "todas" — nunca um filtro por valor arbitrário.
 */
export function parseTabFilter(tab: string | null | undefined): ConversationTabFilter {
  if (tab === UNREAD_TAB_KEY) return { kind: "unread" };
  if (tab === "pessoal") return { kind: "no_lead" };
  if (tab && STAGE_TAB_KEYS.has(tab)) return { kind: "stage", stage: tab };
  return { kind: "all" };
}

/**
 * Corta as linhas buscadas com `limit(pageSize + 1)`: a linha extra só prova que
 * existe próxima página; o cursor aponta para a última linha MANTIDA.
 */
export function splitPage<T extends { id: string; last_msg_at?: string | null }>(
  rows: T[],
  pageSize: number,
): { rows: T[]; next_cursor: string | null } {
  if (rows.length <= pageSize) return { rows, next_cursor: null };
  const kept = rows.slice(0, pageSize);
  const last = kept[kept.length - 1];
  return { rows: kept, next_cursor: encodeCursor({ t: last.last_msg_at ?? null, id: last.id }) };
}

/** URL de uma página da lista (cliente). */
export function conversationsListUrl(params: {
  channelId?: string;
  tab?: string;
  cursor?: string | null;
  leadId?: string;
}): string {
  const qs = new URLSearchParams();
  if (params.channelId) qs.set("channel_id", params.channelId);
  if (params.leadId) qs.set("lead_id", params.leadId);
  if (params.tab && params.tab !== "todos") qs.set("tab", params.tab);
  if (params.cursor) qs.set("cursor", params.cursor);
  const s = qs.toString();
  return s ? `/api/conversations?${s}` : "/api/conversations";
}

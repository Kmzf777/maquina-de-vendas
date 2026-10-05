# P5 — Conversas sem teto de 1000: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tela `/conversas` deixa de depender do `max-rows=1000` do PostgREST: lista
paginada por cursor com rolagem infinita, filtros de conjunto no servidor, contadores
server-side e busca por tokens que também olha e-mail e CNPJ.

**Architecture:** `GET /api/conversations` passa a devolver `{ conversations, next_cursor }`
(keyset `last_msg_at desc nulls last, id desc`, 200 por página) com a aba (`tab`) como
filtro de servidor. Um endpoint novo `GET /api/conversations/counts` dá `{ total, unread }`
por `count=exact, head=true` (não sofre o teto). A página troca `useQuery` por
`useInfiniteQuery`; os patches de tempo real passam a operar sobre as páginas
(`conversation-pages.ts`, puro e testado). A busca (`lib/search.ts`) casa por **todos os
termos em qualquer ordem**, com e-mail e CNPJ/telefone por dígitos (com ou sem máscara),
no cliente e no filtro PostgREST do `search-contacts`.

**Tech Stack:** Next.js 16 App Router (route handlers), React 19, @tanstack/react-query 5.101,
@supabase/postgrest-js 2.100 → PostgREST v14.12, vitest 2 (+ jsdom/@testing-library para
componente).

**Regras (plano mestre `2026-10-06-call-semanal-0110.md`):** todo `npx` dentro de
`flock /root/crm-wt/_heavy.lock`; sem `next build`, sem suíte completa, sem `tsc` do projeto
inteiro; produção só leitura; sem push; só arquivos do P5.

---

## Fatos verificados antes do plano (06/10)

- Produção (leitura): 5.570 conversas, 2 `blocked`, 10 com `last_msg_at` nulo (a mais nova de
  03/10), **1.573 com `unread_count > 0`** (a aba "Não lidas" também é truncada hoje), 0 sem
  lead. Só há canais `meta_cloud` ativos (nenhum Evolution). As 200 mais recentes cobrem ~3,5
  dias. Não há índice em `last_msg_at` (o sort de ~5,5k linhas é barato; índice fica como
  recomendação fora do pacote).
- `leads.cnpj`: 1.442 só dígitos, 11 com máscara; `leads.phone`: 261 com máscara.
- PostgREST v14.12 real (contêiner descartável `p5-postgrest` sobre o banco `p5` do
  `crm-scratch-pg`) aceitou, via `@supabase/postgrest-js`: o `or=(last_msg_at.lt."T",and(last_msg_at.eq."T",id.lt.ID),last_msg_at.is.null)`
  com empate de timestamp, `nullsFirst:false` + `id desc`, `leads!inner` + `eq("leads.stage")`,
  `count: "exact", head: true`, `leads.or=(and(or(...),or(...)))` para tokens e
  `imatch` com `[^0-9]?[^0-9]?` entre dígitos (CNPJ/telefone com máscara).

---

## Task 5.1 — Inventário dos filtros e contadores

Tudo que hoje é aplicado sobre a lista inteira carregada (truncada em 1000) e onde fica:

| # | Filtro / contador | Hoje | Depois do P5 |
|---|---|---|---|
| 1 | Canal ("Todos os canais"/um número) | servidor (`channel_id`) | **servidor** (inalterado; também nos contadores e nas irmãs) |
| 2 | Escopo de canais do usuário (`getAllowedChannelIds`) | servidor | **servidor** (inalterado) |
| 3 | Conversa bloqueada (`status='blocked'`) | servidor | **servidor** (inalterado) |
| 4 | Abas de segmento (Atacado, Private Label, Exportação, Consumo) = `leads.stage` | cliente | **servidor** (`tab=<stage>` → `leads!inner` + `eq leads.stage`); o cliente mantém `conversationMatchesTab` só para refletir patches de tempo real |
| 5 | Aba Pessoal (sem lead) | cliente | **servidor** (`tab=pessoal` → `lead_id is null`) + cliente idem |
| 6 | Aba Não lidas (`unread_count > 0`) | cliente | **servidor** (`tab=nao_lidas` → `unread_count > 0`) + cliente idem (mark-read some na hora) |
| 7 | Badge de "Não lidas" (`unreadTotal`) | cliente (conta a lista) | **servidor** (`/api/conversations/counts` → `unread`) |
| 8 | "N conversas abertas" (estado vazio) | cliente (`conversations.length`) | **servidor** (`counts.total`) |
| 9 | Ordenação `last_msg_at desc` | servidor + re-sort JS | **servidor** (keyset `last_msg_at desc nulls last, id desc`); cliente só re-ordena a janela carregada nos patches |
| 10 | Busca de contato por texto | cliente (lista) + servidor (`search-contacts`, 30) | **cliente + servidor**, por tokens + e-mail + CNPJ/telefone por dígitos |
| 11 | Busca de mensagens | servidor | **servidor** (inalterado) |
| 12 | Deep-link `?lead_id=` | cliente com fallback servidor | **servidor** (fallback já existia; só muda o formato da resposta) |
| 13 | Conversas irmãs (mesmo lead, outro canal) | cliente (lista) | **servidor** (`/api/conversations?lead_id=&channel_id=`) |
| 14 | Tags do lead aberto (`lead_tags` global, 5.479 linhas → truncado) | cliente | **servidor** (consulta só do lead aberto) |
| 15 | SLA "Atraso", fundo da janela 24h, badge de canal/persona | cliente | **cliente** (só realça a página carregada) |
| 16 | Conversa aberta fora da aba/página | cliente (cache único) | **cliente**: a página reinsere a conversa selecionada no cache da aba ativa |

Sem filtro de "vendedor" além do canal (o seletor de canal é o número do vendedor) nem de
`status` na UI (a API aceita `status`, nenhum chamador usa).

---

## Estrutura de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `frontend/src/app/api/conversations/list-params.ts` | criar | contrato puro da listagem: tamanho da página, cursor (encode/decode/validação), filtro keyset, aba→filtro, corte da página, URL do cliente, tipos `ConversationsPage`/`ConversationCounts` |
| `frontend/src/app/api/conversations/list-params.test.ts` | criar | testes do contrato |
| `frontend/src/app/api/conversations/route.ts` | modificar | GET paginado com `tab` e `cursor` |
| `frontend/src/app/api/conversations/route.test.ts` | criar | testes da rota com supabase falso |
| `frontend/src/app/api/conversations/counts/route.ts` | criar | contagens `total`/`unread` server-side |
| `frontend/src/app/api/conversations/counts/route.test.ts` | criar | testes |
| `frontend/src/lib/search.ts` | modificar | tokens, e-mail, CNPJ/telefone por dígitos (cliente + filtro PostgREST) |
| `frontend/src/lib/search.test.ts` | modificar | casos novos + ajuste do teste do termo de telefone |
| `frontend/src/app/api/conversations/search-contacts/route.ts` | modificar | só comentário (o filtro vem do `lib/search.ts`) |
| `frontend/src/app/api/conversations/search-contacts/route.test.ts` | criar | prova que a rota aplica o filtro por tokens em `leads` |
| `frontend/src/app/(authenticated)/conversas/conversation-pages.ts` | criar | helpers puros do cache paginado (achatar, patch preservando páginas, inserir, janela carregada, pertinência à aba) |
| `frontend/src/app/(authenticated)/conversas/conversation-pages.test.ts` | criar | testes |
| `frontend/src/components/conversas/chat-list.tsx` | modificar | `unreadTotal`, `hasMore`, `loadingMore`, `onLoadMore` + sentinela de rolagem infinita |
| `frontend/src/components/conversas/chat-list.test.tsx` | criar | teste de componente (jsdom) |
| `frontend/src/app/(authenticated)/conversas/page.tsx` | modificar | `useInfiniteQuery`, contadores, irmãs, tags por lead, tempo real sobre páginas |

`list-params.ts` e `conversation-pages.ts` são arquivos novos dentro dos diretórios do P5 (a
rota e a página não podem exportar nada além do contrato do Next).

---

## Task 5.2a — Contrato da listagem (`list-params.ts`)

**Files:**
- Create: `frontend/src/app/api/conversations/list-params.ts`
- Test: `frontend/src/app/api/conversations/list-params.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { describe, it, expect } from "vitest";
import {
  CONVERSATIONS_PAGE_SIZE,
  conversationsListUrl,
  cursorOrFilter,
  decodeCursor,
  encodeCursor,
  parseTabFilter,
  splitPage,
} from "./list-params";

const ID = "00000000-0000-0000-0000-000000000001";

describe("cursor", () => {
  it("round-trips timestamp and id", () => {
    const raw = encodeCursor({ t: "2026-10-06T12:00:00.123456+00:00", id: ID });
    expect(decodeCursor(raw)).toEqual({ t: "2026-10-06T12:00:00.123456+00:00", id: ID });
  });

  it("round-trips the null tail (conversations without last_msg_at)", () => {
    expect(decodeCursor(encodeCursor({ t: null, id: ID }))).toEqual({ t: null, id: ID });
  });

  it("rejects anything that could inject into the PostgREST filter", () => {
    expect(decodeCursor(null)).toBeNull();
    expect(decodeCursor("")).toBeNull();
    expect(decodeCursor("sem-separador")).toBeNull();
    expect(decodeCursor(`2026-10-06T12:00:00Z|${ID},status.eq.blocked`)).toBeNull();
    expect(decodeCursor(`2026-10-06),id.gt.0|${ID}`)).toBeNull();
    // `+` que virou espaço por falta de encode: inválido, não um timestamp truncado.
    expect(decodeCursor(`2026-10-06T12:00:00 00:00|${ID}`)).toBeNull();
  });
});

describe("cursorOrFilter", () => {
  it("selects rows strictly after the cursor in last_msg_at desc nulls last, id desc", () => {
    expect(cursorOrFilter("2026-10-06T12:00:00+00:00", ID)).toBe(
      `last_msg_at.lt."2026-10-06T12:00:00+00:00",and(last_msg_at.eq."2026-10-06T12:00:00+00:00",id.lt.${ID}),last_msg_at.is.null`,
    );
  });
});

describe("parseTabFilter", () => {
  it("maps every tab of the list to a server filter", () => {
    expect(parseTabFilter("todos")).toEqual({ kind: "all" });
    expect(parseTabFilter(null)).toEqual({ kind: "all" });
    expect(parseTabFilter("nao_lidas")).toEqual({ kind: "unread" });
    expect(parseTabFilter("pessoal")).toEqual({ kind: "no_lead" });
    for (const stage of ["atacado", "private_label", "exportacao", "consumo"]) {
      expect(parseTabFilter(stage)).toEqual({ kind: "stage", stage });
    }
  });

  it("ignores unknown tabs instead of filtering by an arbitrary stage", () => {
    expect(parseTabFilter("pending")).toEqual({ kind: "all" });
    expect(parseTabFilter("x,status.eq.blocked")).toEqual({ kind: "all" });
  });
});

describe("splitPage", () => {
  const rows = (n: number) =>
    Array.from({ length: n }, (_, i) => ({
      id: `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`,
      last_msg_at: i === n - 1 ? null : `2026-10-06T12:00:${String(59 - (i % 60)).padStart(2, "0")}+00:00`,
    }));

  it("returns everything and no cursor when the page is not full", () => {
    const r = rows(3);
    expect(splitPage(r, 5)).toEqual({ rows: r, next_cursor: null });
  });

  it("cuts at pageSize and points the cursor at the last kept row", () => {
    const r = rows(6);
    const out = splitPage(r, 5);
    expect(out.rows).toHaveLength(5);
    expect(decodeCursor(out.next_cursor)).toEqual({ t: r[4].last_msg_at, id: r[4].id });
  });

  it("uses a 200-row page", () => {
    expect(CONVERSATIONS_PAGE_SIZE).toBe(200);
  });
});

describe("conversationsListUrl", () => {
  it("omits defaults", () => {
    expect(conversationsListUrl({})).toBe("/api/conversations");
    expect(conversationsListUrl({ tab: "todos" })).toBe("/api/conversations");
  });

  it("encodes the cursor so '+' survives the query string", () => {
    const cursor = encodeCursor({ t: "2026-10-06T12:00:00+00:00", id: ID });
    const url = conversationsListUrl({ channelId: "c1", tab: "atacado", cursor });
    const qs = new URL(url, "http://x").searchParams;
    expect(qs.get("channel_id")).toBe("c1");
    expect(qs.get("tab")).toBe("atacado");
    expect(qs.get("cursor")).toBe(cursor);
  });

  it("supports the lead filter used by deep-link and sibling conversations", () => {
    expect(conversationsListUrl({ leadId: "l1" })).toBe("/api/conversations?lead_id=l1");
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/app/api/conversations/list-params.test.ts`
Expected: FAIL — `Failed to resolve import "./list-params"`.

- [ ] **Step 3: Implementar**

```ts
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/app/api/conversations/list-params.test.ts`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
cd /root/crm-wt/cs-p5 && git add frontend/src/app/api/conversations/list-params.ts frontend/src/app/api/conversations/list-params.test.ts
git commit -m "feat(conversas): contrato da lista paginada por cursor (P5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5.2b — `GET /api/conversations` paginado

**Files:**
- Modify: `frontend/src/app/api/conversations/route.ts:134-252`
- Test: `frontend/src/app/api/conversations/route.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));
vi.mock("@/lib/supabase/channel-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/supabase/channel-access")>()),
  getAllowedChannelIds: vi.fn(),
}));

import { GET } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds } from "@/lib/supabase/channel-access";
import { cursorOrFilter, decodeCursor, encodeCursor } from "./list-params";

type Chamada = { tabela: string; metodo: string; args: unknown[] };

const uuid = (i: number) => `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`;
const linha = (i: number) => ({
  id: uuid(i),
  channel_id: "c1",
  last_msg_at: new Date(Date.UTC(2026, 9, 6, 12) - i * 60_000).toISOString(),
  leads: { id: `l${i}`, phone: `55349${i}` },
  channels: { provider: "meta_cloud" },
});

/** supabase-js falso: todo método encadeia; `await` devolve as linhas da tabela. */
function instalar(linhasConversas: unknown[]) {
  const chamadas: Chamada[] = [];
  const tabelas: string[] = [];
  const from = (tabela: string) => {
    tabelas.push(tabela);
    const builder: Record<string, unknown> = {};
    for (const metodo of ["select", "eq", "neq", "in", "is", "gt", "lt", "or", "order", "limit"]) {
      builder[metodo] = (...args: unknown[]) => {
        chamadas.push({ tabela, metodo, args });
        return builder;
      };
    }
    builder.then = (ok: (r: unknown) => unknown) =>
      Promise.resolve({ data: tabela === "conversations" ? linhasConversas : [], error: null }).then(ok);
    return builder;
  };
  const rpc = vi.fn().mockResolvedValue({ data: [], error: null });
  vi.mocked(getServiceSupabase).mockResolvedValue({ from, rpc } as never);
  vi.mocked(getAllowedChannelIds).mockResolvedValue(null);
  const de = (metodo: string) =>
    chamadas.filter((c) => c.tabela === "conversations" && c.metodo === metodo).map((c) => c.args);
  return { chamadas, tabelas, de };
}

const chamar = (qs = "") => GET(new NextRequest(`http://localhost/api/conversations${qs}`));

afterEach(() => vi.clearAllMocks());

describe("GET /api/conversations — paginação", () => {
  it("asks for one row more than the page, in keyset order", async () => {
    const { de } = instalar([linha(1)]);
    await chamar();
    expect(de("limit")).toEqual([[201]]);
    expect(de("order")).toEqual([
      ["last_msg_at", { ascending: false, nullsFirst: false }],
      ["id", { ascending: false }],
    ]);
    expect(de("neq")).toContainEqual(["status", "blocked"]);
  });

  it("returns the page and no cursor when everything fits", async () => {
    instalar([linha(1), linha(2)]);
    const body = await (await chamar()).json();
    expect(body.conversations.map((c: { id: string }) => c.id)).toEqual([uuid(1), uuid(2)]);
    expect(body.next_cursor).toBeNull();
  });

  it("cuts at 200 and points next_cursor at the 200th row", async () => {
    const rows = Array.from({ length: 201 }, (_, i) => linha(i + 1));
    instalar(rows);
    const body = await (await chamar()).json();
    expect(body.conversations).toHaveLength(200);
    expect(decodeCursor(body.next_cursor)).toEqual({ t: rows[199].last_msg_at, id: rows[199].id });
  });

  it("applies the keyset filter for a cursor and skips the legacy Evolution merge", async () => {
    const { de, tabelas } = instalar([]);
    const t = "2026-10-06T12:00:00.123456+00:00";
    await chamar(`?cursor=${encodeURIComponent(encodeCursor({ t, id: uuid(9) }))}`);
    expect(de("or")).toEqual([[cursorOrFilter(t, uuid(9))]]);
    expect(tabelas).not.toContain("channels");
  });

  it("walks the null tail by id when the cursor is already there", async () => {
    const { de } = instalar([]);
    await chamar(`?cursor=${encodeURIComponent(encodeCursor({ t: null, id: uuid(9) }))}`);
    expect(de("is")).toContainEqual(["last_msg_at", null]);
    expect(de("lt")).toContainEqual(["id", uuid(9)]);
    expect(de("or")).toEqual([]);
  });

  it("rejects a malformed cursor with 400 instead of ignoring it", async () => {
    instalar([]);
    const res = await chamar("?cursor=lixo");
    expect(res.status).toBe(400);
  });
});

describe("GET /api/conversations — abas como filtro de servidor", () => {
  it("filters a segment tab by the lead stage with an inner join", async () => {
    const { de } = instalar([]);
    await chamar("?tab=atacado");
    expect(String(de("select")[0][0])).toContain("leads!inner(");
    expect(de("eq")).toContainEqual(["leads.stage", "atacado"]);
  });

  it("filters the unread tab by unread_count", async () => {
    const { de } = instalar([]);
    await chamar("?tab=nao_lidas");
    expect(de("gt")).toContainEqual(["unread_count", 0]);
    expect(String(de("select")[0][0])).not.toContain("leads!inner(");
  });

  it("filters the personal tab by missing lead", async () => {
    const { de } = instalar([]);
    await chamar("?tab=pessoal");
    expect(de("is")).toContainEqual(["lead_id", null]);
  });

  it("keeps channel and lead filters", async () => {
    const { de } = instalar([]);
    await chamar("?channel_id=c9&lead_id=l9");
    expect(de("eq")).toContainEqual(["channel_id", "c9"]);
    expect(de("eq")).toContainEqual(["lead_id", "l9"]);
  });

  it("answers an empty page for a user without channels", async () => {
    instalar([linha(1)]);
    vi.mocked(getAllowedChannelIds).mockResolvedValue([]);
    const body = await (await chamar()).json();
    expect(body).toEqual({ conversations: [], next_cursor: null });
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/app/api/conversations/route.test.ts`
Expected: FAIL (a rota ainda devolve array e não chama `limit`).

- [ ] **Step 3: Implementar** — substituir o `GET` (linhas 134-252) por:

```ts
export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");
  const status = searchParams.get("status");
  // Filtro por lead: usado pelo deep-link `/conversas?lead_id=...` e pelas conversas
  // irmãs (mesmo lead em outro canal).
  const leadId = searchParams.get("lead_id");
  // Aba da lista como filtro de SERVIDOR: filtrar no cliente só enxergava a página
  // carregada (e antes, o teto de 1.000 linhas do PostgREST).
  const tabFilter = parseTabFilter(searchParams.get("tab"));
  const rawCursor = searchParams.get("cursor");
  const cursor = decodeCursor(rawCursor);
  if (rawCursor && !cursor) {
    return NextResponse.json({ error: "invalid cursor" }, { status: 400 });
  }

  // Determina quais channel_ids o usuário logado pode ver.
  // Falha de auth lança ChannelAccessError → respondemos 401, NUNCA [] silencioso
  // (uma lista vazia em erro é indistinguível de "zero conversas" e apaga a lista na UI).
  let allowedChannelIds: string[] | null;
  try {
    allowedChannelIds = await getAllowedChannelIds(supabase);
  } catch (err) {
    if (err instanceof ChannelAccessError) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    throw err;
  }

  if (allowedChannelIds !== null && allowedChannelIds.length === 0) {
    // Usuário não tem nenhum canal — página vazia imediatamente
    return NextResponse.json({ conversations: [], next_cursor: null });
  }

  // 1. Página de conversas do banco. A aba por estágio filtra pelo lead embutido, o
  // que exige INNER JOIN (com o LEFT o filtro só esvaziaria `leads`).
  let dbQuery = supabase
    .from("conversations")
    .select(conversationSelect({ innerLead: tabFilter.kind === "stage" }));

  if (channelId) dbQuery = dbQuery.eq("channel_id", channelId);
  if (status) dbQuery = dbQuery.eq("status", status);
  if (leadId) dbQuery = dbQuery.eq("lead_id", leadId);
  // BLOQUEIO: a conversa de um lead bloqueado SOME do /conversas (decisão de produto).
  // `block_lead` carimba conversations.status = 'blocked'; o filtro fica aqui, na fonte
  // da listagem, para valer inclusive no deep-link ?lead_id=. O histórico não some do
  // sistema — continua acessível pelo funil Blacklist e pela tela de leads.
  dbQuery = dbQuery.neq("status", "blocked");
  // Restringe ao conjunto de canais permitidos para o usuário logado
  if (allowedChannelIds !== null) dbQuery = dbQuery.in("channel_id", allowedChannelIds);

  if (tabFilter.kind === "unread") dbQuery = dbQuery.gt("unread_count", 0);
  else if (tabFilter.kind === "no_lead") dbQuery = dbQuery.is("lead_id", null);
  else if (tabFilter.kind === "stage") dbQuery = dbQuery.eq("leads.stage", tabFilter.stage);

  // Keyset: só linhas DEPOIS da última entregue. Na cauda (last_msg_at nulo) a
  // ordem é só pelo id.
  if (cursor) {
    dbQuery = cursor.t
      ? dbQuery.or(cursorOrFilter(cursor.t, cursor.id))
      : dbQuery.is("last_msg_at", null).lt("id", cursor.id);
  }

  const { data: dbRows, error: dbError } = await dbQuery
    .order("last_msg_at", { ascending: false, nullsFirst: false })
    .order("id", { ascending: false })
    .limit(CONVERSATIONS_PAGE_SIZE + 1);
  // Não devolver lista vazia silenciosa em erro de query: a UI não distingue erro de
  // "zero conversas" e apagaria a lista. Responder 500 mantém o estado anterior.
  if (dbError) {
    return NextResponse.json({ error: dbError.message }, { status: 500 });
  }
  // O select é montado em runtime, então o supabase-js não infere a forma da
  // linha — o contrato real está em EnrichableConversation.
  const { rows: dbConversations, next_cursor } = splitPage(
    (dbRows ?? []) as unknown as EnrichableConversation[],
    CONVERSATIONS_PAGE_SIZE,
  );

  // Add last_message_text + deal info to DB conversations
  const dbWithLastMsg = await enrichConversations(supabase, dbConversations);

  // 2. Evolution (legado, CLAUDE.md §6): só na primeira página da aba "todos", como
  // antes — as conversas Evolution não têm cursor nem estágio/não lidas.
  if (cursor || tabFilter.kind !== "all" || leadId) {
    return NextResponse.json({ conversations: dbWithLastMsg, next_cursor });
  }

  let channelsQuery = supabase
    .from("channels")
    .select("id, name, phone, provider, provider_config, mode")
    .eq("provider", "evolution")
    .eq("is_active", true);

  if (channelId) channelsQuery = channelsQuery.eq("id", channelId);
  if (allowedChannelIds !== null && allowedChannelIds.length > 0) {
    channelsQuery = channelsQuery.in("id", allowedChannelIds);
  }

  const { data: evoChannels } = await channelsQuery;

  // Fetch Evolution chats in parallel (with error tolerance)
  const evoResults = await Promise.allSettled(
    (evoChannels || []).map((ch) =>
      fetchEvolutionConversations(
        ch as {
          id: string;
          name: string;
          phone: string;
          provider: string;
          provider_config: Record<string, string>;
          mode?: string;
        }
      )
    )
  );

  const evoConversations = evoResults.flatMap((r) =>
    r.status === "fulfilled" ? r.value : []
  );
  if (evoConversations.length === 0) {
    return NextResponse.json({ conversations: dbWithLastMsg, next_cursor });
  }

  // 3. Merge: DB conversations take priority (they have real IDs)
  const dbPhoneKeys = new Set(
    dbConversations.map((c) => {
      const lead = c.leads as { phone?: string } | null;
      return `${c.channel_id}_${lead?.phone || ""}`;
    })
  );
  const merged: EnrichableConversation[] = [...dbWithLastMsg];
  for (const evoConv of evoConversations) {
    if (!evoConv) continue;
    const key = `${evoConv.channel_id}_${(evoConv.leads as { phone: string }).phone}`;
    if (!dbPhoneKeys.has(key)) {
      merged.push(evoConv as unknown as EnrichableConversation);
    }
  }

  // Sort by last_msg_at descending, falling back to created_at to avoid
  // proactively-created conversations (null last_msg_at) sinking to 1970.
  const sortTs = (c: { last_msg_at?: string | null; created_at?: string | null }): number => {
    const t = c.last_msg_at ?? c.created_at;
    return t ? new Date(t).getTime() : 0;
  };
  merged.sort((a, b) => sortTs(b) - sortTs(a));

  return NextResponse.json({ conversations: merged, next_cursor });
}
```

E no topo, junto dos imports:

```ts
import {
  CONVERSATIONS_PAGE_SIZE,
  cursorOrFilter,
  decodeCursor,
  parseTabFilter,
  splitPage,
} from "./list-params";
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/app/api/conversations/route.test.ts src/app/api/conversations/list-params.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /root/crm-wt/cs-p5 && git add frontend/src/app/api/conversations/route.ts frontend/src/app/api/conversations/route.test.ts
git commit -m "feat(conversas): GET /api/conversations paginado por cursor, aba no servidor (P5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5.2c — Contadores server-side (`/api/conversations/counts`)

**Files:**
- Create: `frontend/src/app/api/conversations/counts/route.ts`
- Test: `frontend/src/app/api/conversations/counts/route.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));
vi.mock("@/lib/supabase/channel-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/supabase/channel-access")>()),
  getAllowedChannelIds: vi.fn(),
}));

import { GET } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";
import { ChannelAccessError, getAllowedChannelIds } from "@/lib/supabase/channel-access";

type Chamada = { metodo: string; args: unknown[] };

/** Cada `from()` é uma consulta; a contagem devolvida depende de ter `gt(unread_count)`. */
function instalar({ total = 0, unread = 0, erro = null as string | null } = {}) {
  const consultas: Chamada[][] = [];
  const from = () => {
    const chamadas: Chamada[] = [];
    consultas.push(chamadas);
    const builder: Record<string, unknown> = {};
    for (const metodo of ["select", "neq", "in", "gt"]) {
      builder[metodo] = (...args: unknown[]) => {
        chamadas.push({ metodo, args });
        return builder;
      };
    }
    builder.then = (ok: (r: unknown) => unknown) => {
      const ehUnread = chamadas.some((c) => c.metodo === "gt");
      return Promise.resolve({
        data: null,
        count: ehUnread ? unread : total,
        error: erro ? { message: erro } : null,
      }).then(ok);
    };
    return builder;
  };
  vi.mocked(getServiceSupabase).mockResolvedValue({ from } as never);
  vi.mocked(getAllowedChannelIds).mockResolvedValue(null);
  return { consultas };
}

const chamar = (qs = "") => GET(new NextRequest(`http://localhost/api/conversations/counts${qs}`));

afterEach(() => vi.clearAllMocks());

describe("GET /api/conversations/counts", () => {
  it("counts total and unread without fetching rows (no 1000-row cap)", async () => {
    const { consultas } = instalar({ total: 5568, unread: 1573 });
    const body = await (await chamar()).json();
    expect(body).toEqual({ total: 5568, unread: 1573 });
    for (const chamadas of consultas) {
      expect(chamadas[0]).toEqual({ metodo: "select", args: ["id", { count: "exact", head: true }] });
      expect(chamadas).toContainEqual({ metodo: "neq", args: ["status", "blocked"] });
    }
    expect(consultas.filter((c) => c.some((x) => x.metodo === "gt"))[0]).toContainEqual({
      metodo: "gt",
      args: ["unread_count", 0],
    });
  });

  it("restricts to the selected channel", async () => {
    const { consultas } = instalar();
    await chamar("?channel_id=c1");
    for (const chamadas of consultas) {
      expect(chamadas).toContainEqual({ metodo: "in", args: ["channel_id", ["c1"]] });
    }
  });

  it("restricts a seller to their own channels", async () => {
    const { consultas } = instalar();
    vi.mocked(getAllowedChannelIds).mockResolvedValue(["c1", "c2"]);
    await chamar();
    expect(consultas[0]).toContainEqual({ metodo: "in", args: ["channel_id", ["c1", "c2"]] });
  });

  it("answers zeros without querying when the channel is out of scope", async () => {
    const { consultas } = instalar({ total: 9 });
    vi.mocked(getAllowedChannelIds).mockResolvedValue(["c1"]);
    const body = await (await chamar("?channel_id=c9")).json();
    expect(body).toEqual({ total: 0, unread: 0 });
    expect(consultas).toHaveLength(0);
  });

  it("returns 401 on auth failure and 500 on query error", async () => {
    instalar();
    vi.mocked(getAllowedChannelIds).mockRejectedValue(new ChannelAccessError("x"));
    expect((await chamar()).status).toBe(401);
    instalar({ erro: "boom" });
    expect((await chamar()).status).toBe(500);
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/app/api/conversations/counts/route.test.ts`
Expected: FAIL — `Failed to resolve import "./route"`.

- [ ] **Step 3: Implementar**

```ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { resolveSearchChannelScope } from "@/lib/message-search";
import type { ConversationCounts } from "../list-params";

/**
 * Contadores da tela de conversas, contados NO BANCO.
 *
 * A lista agora é paginada (200 por página) e, antes disso, era cortada em 1.000
 * linhas pelo PostgREST: contar `unread_count > 0` sobre o que estava carregado
 * mentia. `count=exact` com `head=true` não devolve linhas, então não sofre o teto.
 * Mesmo escopo da listagem: canais do usuário, canal escolhido, sem bloqueadas.
 */
export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const channelId = new URL(request.url).searchParams.get("channel_id");

  let allowedChannelIds: string[] | null;
  try {
    allowedChannelIds = await getAllowedChannelIds(supabase);
  } catch (err) {
    if (err instanceof ChannelAccessError) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    throw err;
  }

  const scope = resolveSearchChannelScope(allowedChannelIds, channelId);
  if (scope.kind === "empty") {
    return NextResponse.json({ total: 0, unread: 0 } satisfies ConversationCounts);
  }

  const base = () => {
    let q = supabase
      .from("conversations")
      .select("id", { count: "exact", head: true })
      .neq("status", "blocked");
    if (scope.kind === "ids") q = q.in("channel_id", scope.ids);
    return q;
  };

  const [total, unread] = await Promise.all([base(), base().gt("unread_count", 0)]);
  const error = total.error ?? unread.error;
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    total: total.count ?? 0,
    unread: unread.count ?? 0,
  } satisfies ConversationCounts);
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/app/api/conversations/counts/route.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /root/crm-wt/cs-p5 && git add frontend/src/app/api/conversations/counts
git commit -m "feat(conversas): contadores total/não lidas contados no banco (P5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5.4a — Busca por tokens + e-mail + CNPJ (`lib/search.ts`)

**Files:**
- Modify: `frontend/src/lib/search.ts` (todo o arquivo abaixo da linha 4)
- Test: `frontend/src/lib/search.test.ts`

- [ ] **Step 1: Escrever os testes que falham** — acrescentar ao fim de `search.test.ts`:

```ts
describe("leadMatchesSearch — tokens, e-mail e CNPJ (P5)", () => {
  const hiago = {
    name: "Hiago Angelucci",
    phone: "5534999998888",
    email: "compras@vidanatural.com.br",
    cnpj: "25139264000151",
    company: "Vida Natural",
  };

  it("matches all terms in any order", () => {
    expect(leadMatchesSearch("angelucci hiago", hiago)).toBe(true);
    expect(leadMatchesSearch("Hiago   ANGELUCCI", hiago)).toBe(true);
  });

  it("requires every term", () => {
    expect(leadMatchesSearch("hiago souza", hiago)).toBe(false);
  });

  it("lets terms hit different fields", () => {
    expect(leadMatchesSearch("hiago natural", hiago)).toBe(true);
    expect(leadMatchesSearch("hiago 99999", hiago)).toBe(true);
  });

  it("matches by e-mail", () => {
    expect(leadMatchesSearch("compras@vidanatural", hiago)).toBe(true);
    expect(leadMatchesSearch("vidanatural.com", hiago)).toBe(true);
  });

  it("finds a CNPJ typed with mask by its digits", () => {
    expect(leadMatchesSearch("25.139.264/0001-51", hiago)).toBe(true);
    expect(leadMatchesSearch("25139264", hiago)).toBe(true);
  });

  it("finds a CNPJ stored with mask by the digits typed", () => {
    const masked = { name: "Loja", cnpj: "25.139.264/0001-51" };
    expect(leadMatchesSearch("25139264000151", masked)).toBe(true);
    expect(leadMatchesSearch("25.139.264/0001-51", masked)).toBe(true);
  });

  it("keeps matching a contiguous phrase (superset of the old behavior)", () => {
    expect(leadMatchesSearch("hiago ang", hiago)).toBe(true);
  });

  it("matches nothing for a query made only of punctuation", () => {
    expect(leadMatchesSearch("...", hiago)).toBe(false);
  });
});

describe("searchTokens", () => {
  it("folds, splits on anything that is not a letter or digit, drops empties", () => {
    expect(searchTokens("  Angelucci,  HIÁGO ")).toEqual(["angelucci", "hiago"]);
    expect(searchTokens("compras@vida.com")).toEqual(["compras", "vida", "com"]);
    expect(searchTokens("...")).toEqual([]);
  });
});

describe("buildDigitsPattern", () => {
  it("tolerates up to two separators between digits", () => {
    const re = new RegExp(buildDigitsPattern("25139264000151"));
    expect(re.test("25.139.264/0001-51")).toBe(true);
    expect(re.test("25139264000151")).toBe(true);
    expect(new RegExp(buildDigitsPattern("34988887777")).test("(34) 98888-7777")).toBe(true);
  });

  it("never emits characters that break the PostgREST or=() parser", () => {
    expect(buildDigitsPattern("123")).not.toMatch(/[.,()*\\"]/);
  });
});

describe("buildLeadSearchOrFilter — tokens (P5)", () => {
  it("ANDs one OR-group per term when there are several terms", () => {
    const filter = buildLeadSearchOrFilter("angelucci hiago") ?? "";
    expect(filter.startsWith("and(or(")).toBe(true);
    expect(filter).toContain("name.imatch.[aàáâãäå]ng");
    expect(filter).toContain("name.imatch.h[iìíîï][aàáâãäå]g[oòóôõö]");
  });

  it("looks at e-mail", () => {
    expect(buildLeadSearchOrFilter("compras")).toContain("email.imatch.");
  });

  it("matches the whole digit string on phone and cnpj, with or without mask", () => {
    const filter = buildLeadSearchOrFilter("25.139.264/0001-51") ?? "";
    const d = buildDigitsPattern("25139264000151");
    expect(filter).toContain(`phone.imatch.${d}`);
    expect(filter).toContain(`cnpj.imatch.${d}`);
  });

  it("keeps a single-term query flat (no and())", () => {
    const filter = buildLeadSearchOrFilter("cafe") ?? "";
    expect(filter).not.toContain("and(");
    expect(filter).not.toContain("phone.");
  });
});
```

E trocar o teste antigo do telefone (que fixava `phone.ilike`) por:

```ts
  it("adds a phone term only when the query carries digits", () => {
    expect(buildLeadSearchOrFilter("(34) 99999-8888")).toContain(
      `phone.imatch.${buildDigitsPattern("34999998888")}`,
    );
    expect(buildLeadSearchOrFilter("aisl")).not.toContain("phone.");
  });
```

E no import do topo, acrescentar `searchTokens, buildDigitsPattern`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/lib/search.test.ts`
Expected: FAIL — `searchTokens`/`buildDigitsPattern` não exportados; "angelucci hiago" falso.

- [ ] **Step 3: Implementar** — `leadMatchesSearch`, `LeadSearchFields`, `LEAD_TEXT_COLUMNS` e
`buildLeadSearchOrFilter` passam a ser:

```ts
export interface LeadSearchFields {
  name?: string | null;
  phone?: string | null;
  company?: string | null;
  razao_social?: string | null;
  nome_fantasia?: string | null;
  email?: string | null;
  cnpj?: string | null;
}

/**
 * Termos da busca: texto dobrado (sem acento, minúsculo), quebrado em tudo que não é
 * letra/dígito. "Angelucci, Hiágo" → ["angelucci", "hiago"]. É a MESMA quebra que o
 * servidor usa em {@link buildLeadSearchOrFilter}.
 */
export function searchTokens(query: string): string[] {
  return foldText(query)
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);
}

const digitsOf = (value: string | null | undefined): string => (value ?? "").replace(/\D/g, "");

/**
 * True quando a busca casa com o lead:
 *  1. os dígitos da busca inteira aparecem no telefone ou no CNPJ (com ou sem máscara
 *     dos dois lados — "(34) 99999-8888", "25.139.264/0001-51"); ou
 *  2. TODOS os termos aparecem, em qualquer ordem e em qualquer campo de texto
 *     (nome, empresa, razão social, fantasia, e-mail) — termo só de dígitos também
 *     vale no telefone/CNPJ. "angelucci hiago" acha "Hiago Angelucci".
 * É superconjunto da regra antiga (frase contígua). Busca vazia casa tudo.
 */
export function leadMatchesSearch(query: string, lead: LeadSearchFields): boolean {
  const raw = query.trim();
  if (!raw) return true;

  const phoneDigits = digitsOf(lead.phone);
  const cnpjDigits = digitsOf(lead.cnpj);
  const qDigits = digitsOf(raw);
  if (qDigits && (phoneDigits.includes(qDigits) || cnpjDigits.includes(qDigits))) return true;

  const tokens = searchTokens(raw);
  if (tokens.length === 0) return false;

  const text = [lead.name, lead.company, lead.razao_social, lead.nome_fantasia, lead.email]
    .filter((field): field is string => field != null)
    .map(foldText)
    .join("\n");

  return tokens.every(
    (token) =>
      text.includes(token) ||
      (/^\d+$/.test(token) && (phoneDigits.includes(token) || cnpjDigits.includes(token))),
  );
}
```

(`dealMatchesSearch`, `ACCENT_CLASSES` e `buildAccentInsensitivePattern` ficam como estão.)

```ts
/** Colunas de texto do lead cobertas pela busca — espelha {@link leadMatchesSearch}. */
const LEAD_TEXT_COLUMNS = ["name", "company", "razao_social", "nome_fantasia", "email"] as const;

/**
 * Padrão POSIX que casa a sequência de dígitos tolerando até dois separadores entre
 * eles — "25139264000151" casa "25.139.264/0001-51" e "(34) 98888-7777" casa
 * "34988887777". Só usa `[^0-9]?`: nada que quebre o parser do `or=()`.
 */
export function buildDigitsPattern(digits: string): string {
  return Array.from(digits).join("[^0-9]?[^0-9]?");
}

/** Termos `coluna.op.valor` de UM token: texto em todas as colunas, dígitos em telefone/CNPJ. */
function tokenTerms(token: string): string[] {
  const pattern = buildAccentInsensitivePattern(token) ?? token;
  const terms: string[] = LEAD_TEXT_COLUMNS.map((col) => `${col}.imatch.${pattern}`);
  if (/^\d+$/.test(token)) {
    const d = buildDigitsPattern(token);
    terms.push(`phone.imatch.${d}`, `cnpj.imatch.${d}`);
  }
  return terms;
}

/**
 * Monta o valor do filtro `or=(...)` que a busca de contatos aplica sobre a tabela
 * `leads` embutida — a mesma regra de {@link leadMatchesSearch}:
 *  - dígitos da busca inteira no telefone/CNPJ (tolerando máscara, via `imatch`);
 *  - OU todos os termos: `and(or(<termo1 em cada coluna>),or(<termo2 ...>))`.
 * Uma busca de um termo só fica plana (`col.imatch.x,...`).
 *
 * @returns o filtro, ou null quando não há nada pesquisável (o chamador deve
 *          responder lista vazia sem ir ao banco).
 */
export function buildLeadSearchOrFilter(query: string): string | null {
  const tokens = searchTokens(query);
  if (tokens.length === 0) return null;

  const terms: string[] = [];
  const digits = query.replace(/\D/g, "");
  const singleDigitToken = tokens.length === 1 && tokens[0] === digits;
  if (digits && !singleDigitToken) {
    const d = buildDigitsPattern(digits);
    terms.push(`phone.imatch.${d}`, `cnpj.imatch.${d}`);
  }

  if (tokens.length === 1) {
    terms.push(...tokenTerms(tokens[0]));
  } else {
    terms.push(`and(${tokens.map((t) => `or(${tokenTerms(t).join(",")})`).join(",")})`);
  }
  return terms.join(",");
}
```

Ajuste do teste "ANDs one OR-group per term": com o termo de dígitos ausente, o filtro de
"angelucci hiago" começa em `and(or(`.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/lib/search.test.ts src/lib/contact-search.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /root/crm-wt/cs-p5 && git add frontend/src/lib/search.ts frontend/src/lib/search.test.ts
git commit -m "feat(busca): termos em qualquer ordem, e-mail e CNPJ/telefone com máscara (P5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5.4b — `search-contacts` usa o filtro por tokens

**Files:**
- Modify: `frontend/src/app/api/conversations/search-contacts/route.ts:14-21` (comentário)
- Test: `frontend/src/app/api/conversations/search-contacts/route.test.ts`

- [ ] **Step 1: Escrever o teste** (a rota já delega a `buildLeadSearchOrFilter`; o teste
prova a integração e o escopo):

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));
vi.mock("@/lib/supabase/channel-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/supabase/channel-access")>()),
  getAllowedChannelIds: vi.fn(),
}));

import { GET } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds } from "@/lib/supabase/channel-access";
import { buildLeadSearchOrFilter } from "@/lib/search";

function instalar() {
  const chamadas: { metodo: string; args: unknown[] }[] = [];
  const builder: Record<string, unknown> = {};
  for (const metodo of ["select", "or", "order", "limit", "in"]) {
    builder[metodo] = (...args: unknown[]) => {
      chamadas.push({ metodo, args });
      return builder;
    };
  }
  builder.then = (ok: (r: unknown) => unknown) => Promise.resolve({ data: [], error: null }).then(ok);
  vi.mocked(getServiceSupabase).mockResolvedValue({ from: () => builder, rpc: vi.fn() } as never);
  vi.mocked(getAllowedChannelIds).mockResolvedValue(null);
  return chamadas;
}

const chamar = (q: string) =>
  GET(new NextRequest(`http://localhost/api/conversations/search-contacts?q=${encodeURIComponent(q)}`));

afterEach(() => vi.clearAllMocks());

describe("GET /api/conversations/search-contacts", () => {
  it("searches leads by every term, in any order", async () => {
    const chamadas = instalar();
    await chamar("angelucci hiago");
    const or = chamadas.find((c) => c.metodo === "or");
    expect(or?.args).toEqual([buildLeadSearchOrFilter("angelucci hiago"), { referencedTable: "leads" }]);
    expect(String(or?.args[0])).toContain("and(or(");
  });

  it("searches a masked CNPJ by its digits", async () => {
    const chamadas = instalar();
    await chamar("25.139.264/0001-51");
    const or = chamadas.find((c) => c.metodo === "or");
    expect(String(or?.args[0])).toContain("cnpj.imatch.2[^0-9]?[^0-9]?5");
  });

  it("uses an inner join so the filter drops non-matching conversations", async () => {
    const chamadas = instalar();
    await chamar("hiago");
    expect(String(chamadas.find((c) => c.metodo === "select")?.args[0])).toContain("leads!inner(");
  });
});
```

- [ ] **Step 2: Rodar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/app/api/conversations/search-contacts/route.test.ts`
Expected: PASS já com a Task 5.4a (a rota delega ao `lib/search.ts`). O teste "searches
leads by every term" exige `and(or(` e o de CNPJ exige `cnpj.imatch.`, que só a 5.4a produz —
rodado antes da 5.4a, ele falharia (ordem de execução: 5.4b logo depois de 5.4a).

- [ ] **Step 3: Atualizar o comentário da rota** (linhas 14-21):

```ts
/**
 * Busca de CONTATOS no servidor.
 *
 * A lista de `/api/conversations` é paginada (200 por página) e, antes, era cortada
 * em 1.000 linhas pelo PostgREST: filtrar só no cliente jurava "Nenhum contato
 * encontrado" com a conversa viva no banco. Aqui o filtro roda no banco, sobre a
 * base inteira, sempre dentro do escopo de canais do usuário — por TODOS os termos
 * em qualquer ordem, e-mail e CNPJ/telefone por dígitos (`buildLeadSearchOrFilter`).
 */
```

- [ ] **Step 4: Commit**

```bash
cd /root/crm-wt/cs-p5 && git add frontend/src/app/api/conversations/search-contacts
git commit -m "test(busca): search-contacts filtra leads por termos e CNPJ com máscara (P5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5.3a — Cache paginado da página (`conversation-pages.ts`)

**Files:**
- Create: `frontend/src/app/(authenticated)/conversas/conversation-pages.ts`
- Test: `frontend/src/app/(authenticated)/conversas/conversation-pages.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { describe, it, expect } from "vitest";
import type { Conversation } from "@/lib/types";
import { encodeCursor } from "@/app/api/conversations/list-params";
import {
  conversationBelongsToKey,
  conversationsQueryKey,
  flattenPages,
  insertIntoPages,
  isWithinLoadedWindow,
  patchPages,
  shouldFetchUnknownRow,
  type ConversationPages,
} from "./conversation-pages";

function conv(id: string, last: string | null, over: Partial<Conversation> = {}): Conversation {
  return {
    id,
    lead_id: "l1",
    channel_id: "c1",
    stage: "secretaria",
    status: "active",
    last_msg_at: last,
    created_at: "2026-01-01T00:00:00Z",
    agent_profile_id: null,
    last_message_text: null,
    unread_count: 0,
    last_customer_message_at: null,
    whatsapp_window_expires_at: null,
    followup_enabled: true,
    first_seller_response_at: null,
    last_seller_response_at: null,
    ...over,
  } as Conversation;
}

const ID_B = "00000000-0000-0000-0000-00000000000b";

function pages(): ConversationPages {
  return {
    pages: [
      {
        conversations: [conv("a", "2026-10-06T12:00:00+00:00"), conv("b", "2026-10-06T11:00:00+00:00")],
        next_cursor: encodeCursor({ t: "2026-10-06T11:00:00+00:00", id: ID_B }),
      },
      {
        conversations: [conv("c", "2026-10-06T10:00:00+00:00"), conv("d", "2026-10-06T09:00:00+00:00")],
        next_cursor: encodeCursor({ t: "2026-10-06T09:00:00+00:00", id: ID_B }),
      },
    ],
    pageParams: [null, "x"],
  };
}

describe("flattenPages", () => {
  it("concatenates pages and drops duplicates (first wins)", () => {
    const data = pages();
    data.pages[1].conversations.push(conv("a", "2026-10-06T08:00:00+00:00"));
    expect(flattenPages(data).map((c) => c.id)).toEqual(["a", "b", "c", "d"]);
    expect(flattenPages(undefined)).toEqual([]);
  });
});

describe("patchPages", () => {
  it("applies a whole-list updater and keeps page sizes, cursors and params", () => {
    const data = pages();
    const out = patchPages(data, (list) => [list[3], ...list.slice(0, 3)]);
    expect(out.pages.map((p) => p.conversations.map((c) => c.id))).toEqual([["d", "a"], ["b", "c"]]);
    expect(out.pages.map((p) => p.next_cursor)).toEqual(data.pages.map((p) => p.next_cursor));
    expect(out.pageParams).toBe(data.pageParams);
  });

  it("lets the last page absorb growth and shrinkage", () => {
    const grown = patchPages(pages(), (list) => [conv("n", null), ...list]);
    expect(grown.pages.map((p) => p.conversations.length)).toEqual([2, 3]);
    const shrunk = patchPages(pages(), (list) => list.slice(1));
    expect(shrunk.pages.map((p) => p.conversations.length)).toEqual([2, 1]);
  });
});

describe("insertIntoPages", () => {
  it("inserts in last_msg_at order", () => {
    const out = insertIntoPages(pages(), conv("x", "2026-10-06T10:30:00+00:00"));
    expect(flattenPages(out).map((c) => c.id)).toEqual(["a", "b", "x", "c", "d"]);
  });

  it("keeps the cached copy when the conversation is already there (it carries live state)", () => {
    const data = pages();
    const out = insertIntoPages(data, conv("a", "2026-10-06T12:00:00+00:00", { unread_count: 9 }));
    expect(out).toBe(data);
  });

  it("with respectWindow, skips a conversation older than the loaded window", () => {
    const data = pages();
    expect(insertIntoPages(data, conv("old", "2026-10-01T00:00:00+00:00"), { respectWindow: true })).toBe(data);
    const inside = insertIntoPages(data, conv("new", "2026-10-06T13:00:00+00:00"), { respectWindow: true });
    expect(flattenPages(inside)[0].id).toBe("new");
  });
});

describe("isWithinLoadedWindow", () => {
  it("is true for anything at or after the boundary of the last loaded page", () => {
    expect(isWithinLoadedWindow(pages(), "2026-10-06T09:00:00+00:00")).toBe(true);
    expect(isWithinLoadedWindow(pages(), "2026-10-06T13:00:00.5+00:00")).toBe(true);
  });

  it("is false for older rows and for the null tail while more pages exist", () => {
    expect(isWithinLoadedWindow(pages(), "2026-10-05T00:00:00+00:00")).toBe(false);
    expect(isWithinLoadedWindow(pages(), null)).toBe(false);
  });

  it("is true when everything is loaded or nothing is cached yet", () => {
    const data = pages();
    data.pages[1].next_cursor = null;
    expect(isWithinLoadedWindow(data, "2020-01-01T00:00:00+00:00")).toBe(true);
    expect(isWithinLoadedWindow(undefined, null)).toBe(true);
  });
});

describe("shouldFetchUnknownRow", () => {
  it("skips rows that cannot belong to the unread or personal tabs", () => {
    expect(shouldFetchUnknownRow({ id: "x", unread_count: 0 }, "nao_lidas")).toBe(false);
    expect(shouldFetchUnknownRow({ id: "x", unread_count: 2 }, "nao_lidas")).toBe(true);
    expect(shouldFetchUnknownRow({ id: "x", lead_id: "l1" }, "pessoal")).toBe(false);
  });

  it("fetches for 'todos' and segment tabs (the row has no lead stage)", () => {
    expect(shouldFetchUnknownRow({ id: "x" }, "todos")).toBe(true);
    expect(shouldFetchUnknownRow({ id: "x" }, "atacado")).toBe(true);
  });
});

describe("conversationBelongsToKey", () => {
  it("checks channel and tab of the cache key", () => {
    const atacado = conv("x", null, { leads: { id: "l1", stage: "atacado" } as never });
    expect(conversationBelongsToKey(atacado, conversationsQueryKey("", "atacado"))).toBe(true);
    expect(conversationBelongsToKey(atacado, conversationsQueryKey("", "consumo"))).toBe(false);
    expect(conversationBelongsToKey(atacado, conversationsQueryKey("c2", "todos"))).toBe(false);
    expect(conversationBelongsToKey(atacado, conversationsQueryKey("c1", "todos"))).toBe(true);
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd "/root/crm-wt/cs-p5/frontend" && flock /root/crm-wt/_heavy.lock npx vitest run "src/app/(authenticated)/conversas/conversation-pages.test.ts"`
Expected: FAIL — módulo inexistente.

- [ ] **Step 3: Implementar**

```ts
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
import { sortByLastMsgDesc, type ConversationRow } from "@/lib/conversations-live";
import { decodeCursor, type ConversationsPage } from "@/app/api/conversations/list-params";

export type ConversationPages = InfiniteData<ConversationsPage<Conversation>, string | null>;

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

/**
 * `lastMsgAt` cai dentro do trecho já carregado? A fronteira é o cursor da última
 * página (o que o servidor entregou), não o último item da lista — que pode ser uma
 * conversa antiga injetada pela busca/seleção.
 */
export function isWithinLoadedWindow(
  data: ConversationPages | undefined,
  lastMsgAt: string | null | undefined,
): boolean {
  if (!data || data.pages.length === 0) return true;
  const boundary = decodeCursor(data.pages[data.pages.length - 1].next_cursor);
  if (!boundary) return true; // não há próxima página: tudo está carregado
  if (boundary.t === null) return true; // a fronteira já está na cauda de nulls
  if (!lastMsgAt) return false; // nulls vêm por último, depois da fronteira
  const at = Date.parse(lastMsgAt);
  const limit = Date.parse(boundary.t);
  if (Number.isNaN(at) || Number.isNaN(limit)) return true; // na dúvida, busca
  return at >= limit;
}

/**
 * Insere `conv` em ordem de `last_msg_at`. Se ela já está no cache, a cópia do cache
 * vence (carrega mark-read/toggles otimistas). Com `respectWindow`, conversa mais
 * antiga que a fronteira carregada fica de fora — o fetchNextPage a trará.
 */
export function insertIntoPages(
  data: ConversationPages,
  conv: Conversation,
  { respectWindow = false }: { respectWindow?: boolean } = {},
): ConversationPages {
  if (flattenPages(data).some((c) => c.id === conv.id)) return data;
  if (respectWindow && !isWithinLoadedWindow(data, conv.last_msg_at)) return data;
  return patchPages(data, (list) => sortByLastMsgDesc([...list, conv]));
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd "/root/crm-wt/cs-p5/frontend" && flock /root/crm-wt/_heavy.lock npx vitest run "src/app/(authenticated)/conversas/conversation-pages.test.ts"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /root/crm-wt/cs-p5 && git add "frontend/src/app/(authenticated)/conversas/conversation-pages.ts" "frontend/src/app/(authenticated)/conversas/conversation-pages.test.ts"
git commit -m "feat(conversas): helpers do cache paginado da lista (P5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5.3b — `chat-list.tsx`: rolagem infinita e contador do servidor

**Files:**
- Modify: `frontend/src/components/conversas/chat-list.tsx` (props 20-34, 101-121, 183, 512-521)
- Test: `frontend/src/components/conversas/chat-list.test.tsx`

- [ ] **Step 1: Escrever o teste que falha**

```tsx
/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent, screen, act } from "@testing-library/react";
import type { Conversation } from "@/lib/types";
import { ChatList } from "./chat-list";

let ioCallback: ((entries: { isIntersecting: boolean }[]) => void) | null = null;

class FakeIntersectionObserver {
  constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
    ioCallback = cb;
  }
  observe() {}
  disconnect() {}
  unobserve() {}
}

function conv(id: string, unread = 0): Conversation {
  return {
    id,
    lead_id: `l-${id}`,
    channel_id: "c1",
    stage: "secretaria",
    status: "active",
    last_msg_at: "2026-10-06T12:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    agent_profile_id: null,
    last_message_text: null,
    unread_count: unread,
    last_customer_message_at: null,
    whatsapp_window_expires_at: null,
    followup_enabled: true,
    first_seller_response_at: null,
    last_seller_response_at: null,
    leads: { id: `l-${id}`, name: `Lead ${id}`, phone: "5534999990000", stage: "atacado" } as never,
  } as Conversation;
}

function renderList(over: Partial<Parameters<typeof ChatList>[0]> = {}) {
  const props = {
    conversations: [conv("a", 1), conv("b")],
    channels: [],
    activeTab: "todos",
    selectedConversationId: null,
    selectedChannelId: "",
    onSelectConversation: vi.fn(),
    onTabChange: vi.fn(),
    onChannelChange: vi.fn(),
    ...over,
  };
  return { ...render(<ChatList {...props} />), props };
}

beforeEach(() => {
  ioCallback = null;
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve([]) }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ChatList — contador de não lidas", () => {
  it("shows the server-side total instead of counting the loaded page", () => {
    renderList({ unreadTotal: 37 });
    expect(screen.getByLabelText("37 conversas não lidas").textContent).toBe("9+");
  });

  it("falls back to the loaded page when there is no server total", () => {
    renderList();
    expect(screen.getByLabelText("1 conversas não lidas")).toBeTruthy();
  });
});

describe("ChatList — rolagem infinita", () => {
  it("loads the next page when the end of the list becomes visible", () => {
    const onLoadMore = vi.fn();
    renderList({ hasMore: true, onLoadMore });
    act(() => ioCallback?.([{ isIntersecting: true }]));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("does not ask again while a page is loading", () => {
    const onLoadMore = vi.fn();
    renderList({ hasMore: true, loadingMore: true, onLoadMore });
    act(() => ioCallback?.([{ isIntersecting: true }]));
    expect(onLoadMore).not.toHaveBeenCalled();
    expect(screen.getByText("Carregando mais conversas...")).toBeTruthy();
  });

  it("offers a manual button as fallback", () => {
    const onLoadMore = vi.fn();
    renderList({ hasMore: true, onLoadMore });
    fireEvent.click(screen.getByText("Carregar mais conversas"));
    expect(onLoadMore).toHaveBeenCalled();
  });

  it("has no sentinel when everything is loaded", () => {
    renderList({ hasMore: false, onLoadMore: vi.fn() });
    expect(screen.queryByText("Carregar mais conversas")).toBeNull();
  });

  it("does not page while searching (search is server-side)", () => {
    const onLoadMore = vi.fn();
    renderList({ hasMore: true, onLoadMore });
    fireEvent.change(screen.getByPlaceholderText("Buscar conversa..."), { target: { value: "hiago" } });
    expect(screen.queryByText("Carregar mais conversas")).toBeNull();
    act(() => ioCallback?.([{ isIntersecting: true }]));
    expect(onLoadMore).not.toHaveBeenCalled();
  });
});

describe("ChatList — seleção", () => {
  it("still selects a conversation from the list", () => {
    const { props } = renderList();
    fireEvent.click(screen.getByText("Lead b"));
    expect(props.onSelectConversation).toHaveBeenCalledWith(expect.objectContaining({ id: "b" }));
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/components/conversas/chat-list.test.tsx`
Expected: FAIL — badge mostra "1" (sem `unreadTotal`), sem "Carregar mais conversas".

- [ ] **Step 3: Implementar**

Props novas em `ChatListProps`:

```ts
  /** Total de conversas não lidas contado no servidor (todas as páginas). Sem ele, conta a página carregada. */
  unreadTotal?: number;
  /** Há mais páginas no servidor depois da última carregada. */
  hasMore?: boolean;
  /** Uma próxima página está sendo buscada. */
  loadingMore?: boolean;
  /** Pede a próxima página (rolagem infinita). */
  onLoadMore?: () => void;
```

Desestruturar `unreadTotal: unreadTotalProp, hasMore = false, loadingMore = false, onLoadMore`
no componente. Trocar a linha 183 por:

```ts
  // Contador do servidor (todas as páginas); a contagem local é só fallback.
  const unreadTotal =
    unreadTotalProp ?? conversations.filter((c) => (c.unread_count ?? 0) > 0).length;
```

Depois de `const isServerSearching = ...` (linha 214), acrescentar a sentinela:

```ts
  // Rolagem infinita: quando o fim da lista entra na tela, pede a próxima página.
  // Enquanto a sentinela continuar visível (a aba esconde itens da página nova), o
  // efeito pede de novo assim que a página anterior termina de carregar.
  const sentinelRef = useRef<HTMLDivElement>(null);
  const [sentinelVisible, setSentinelVisible] = useState(false);
  const showSentinel = hasMore && !isServerSearching;
  useEffect(() => {
    const el = sentinelRef.current;
    if (!showSentinel || !el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => setSentinelVisible(entries.some((e) => e.isIntersecting)),
      { rootMargin: "400px 0px" },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      setSentinelVisible(false);
    };
  }, [showSentinel]);
  useEffect(() => {
    if (sentinelVisible && showSentinel && !loadingMore) onLoadMore?.();
  }, [sentinelVisible, showSentinel, loadingMore, onLoadMore]);
```

E no ramo sem busca (linhas 512-521), depois do `map`:

```tsx
            {showSentinel && (
              <div ref={sentinelRef} className="px-3 py-3 flex justify-center">
                {loadingMore ? (
                  <span className="flex items-center gap-2 text-[11px] text-[#7b7b78]">
                    <span className="w-3 h-3 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin flex-shrink-0" />
                    Carregando mais conversas...
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => onLoadMore?.()}
                    className="text-[12px] text-[#7b7b78] underline underline-offset-2 hover:text-[#111111]"
                  >
                    Carregar mais conversas
                  </button>
                )}
              </div>
            )}
```

E o "Nenhuma conversa encontrada." só aparece quando não há mais páginas:
`{filteredConversations.length === 0 && !hasMore && (...)}`.

Atualizar o comentário das linhas 123-126 ("A de contatos existe porque a lista carregada é
paginada: filtrar só o que está em memória jurava 'Nenhum contato encontrado'...") e o da
linha 222 ("Remoto: o que ainda não foi carregado (páginas seguintes)").

- [ ] **Step 4: Rodar e ver passar**

Run: `cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run src/components/conversas/chat-list.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /root/crm-wt/cs-p5 && git add frontend/src/components/conversas/chat-list.tsx frontend/src/components/conversas/chat-list.test.tsx
git commit -m "feat(conversas): lista com rolagem infinita e contador de não lidas do servidor (P5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5.3c — `page.tsx`: lista infinita, contadores, irmãs, tags por lead, tempo real

**Files:**
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx`

Sem teste unitário de página (o arquivo é a composição; a lógica testável foi para
`conversation-pages.ts`, `list-params.ts` e `chat-list.tsx`). Verificação: eslint + tsc
restrito aos arquivos do P5 + vitest dos helpers.

- [ ] **Step 1: Imports**

```ts
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
...
import {
  conversationsListUrl,
  type ConversationCounts,
  type ConversationsPage,
} from "@/app/api/conversations/list-params";
import {
  conversationBelongsToKey,
  conversationsQueryKey,
  flattenPages,
  insertIntoPages,
  isWithinLoadedWindow,
  patchPages,
  shouldFetchUnknownRow,
  type ConversationPages,
} from "./conversation-pages";
```

Constantes novas, junto de `REFETCH_DEBOUNCE_MS`:

```ts
// Conversa desconhecida que recebeu UPDATE: até este tanto, busca uma a uma pelo id
// (barato); acima, uma invalidação integral sai mais em conta.
const MAX_SINGLE_FETCHES = 10;
// Conversa buscada que não pertence à aba ativa: ignora novos UPDATEs dela por 1 min
// (aba de segmento não sabe o estágio do lead pela linha crua do Realtime).
const IGNORE_OUTSIDE_TAB_MS = 60_000;
```

- [ ] **Step 2: Lista paginada** — substituir o `useQuery` de conversas (linhas 75-96) por:

```ts
  // Lista PAGINADA por cursor (200 por página): o PostgREST corta toda leitura em
  // 1.000 linhas, então a lista inteira de uma vez cobria só ~11 dias. A aba é filtro
  // de servidor — um cache por canal + aba.
  const listKey = conversationsQueryKey(selectedChannelId, activeTab);
  const {
    data: pagesData,
    isPending: convPending,
    isError: listError,
    isPlaceholderData: isRefreshing,
    refetch: refetchConversations,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useInfiniteQuery({
    queryKey: listKey,
    queryFn: async ({ signal, pageParam }): Promise<ConversationsPage<Conversation>> => {
      const url = conversationsListUrl({
        channelId: selectedChannelId,
        tab: activeTab,
        cursor: pageParam,
      });
      const res = await fetch(url, { signal });
      if (!res.ok) throw new Error(`conversations ${res.status}`);
      const data = await res.json();
      const list: Conversation[] = Array.isArray(data?.conversations) ? data.conversations : [];
      return {
        conversations: applyOverrides(list),
        next_cursor: typeof data?.next_cursor === "string" ? data.next_cursor : null,
      };
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    placeholderData: keepPreviousData,
  });
  const conversations = useMemo(() => flattenPages(pagesData), [pagesData]);

  // Contadores do servidor: o badge de "Não lidas" e o total não podem contar só o
  // que está carregado.
  const { data: counts } = useQuery({
    queryKey: ["conversation-counts", selectedChannelId],
    queryFn: async ({ signal }): Promise<ConversationCounts | null> => {
      const qs = selectedChannelId ? `?channel_id=${encodeURIComponent(selectedChannelId)}` : "";
      const res = await fetch(`/api/conversations/counts${qs}`, { signal });
      if (!res.ok) return null;
      return (await res.json()) as ConversationCounts;
    },
    placeholderData: keepPreviousData,
  });

  const handleLoadMore = useCallback(() => {
    if (isRefreshing || !hasNextPage || isFetchingNextPage) return;
    void fetchNextPage();
  }, [isRefreshing, hasNextPage, isFetchingNextPage, fetchNextPage]);
```

Remover o `useQuery` de `lead-tags` global (linhas 117-127).

- [ ] **Step 3: Patches sobre páginas** — substituir `patchList`/`patchConversation`/`ensureInList`
(linhas 129-165) por:

```ts
  // Patch local em TODOS os caches da lista (um por canal + aba): a mesma conversa
  // pode estar na aba "Todos" e na de "Atacado", e a troca de aba não pode mostrar
  // um estado velho.
  const patchList = useCallback(
    (updater: (list: Conversation[]) => Conversation[]) => {
      queryClient.setQueriesData<ConversationPages>({ queryKey: ["conversations"] }, (old) =>
        old ? patchPages(old, updater) : old,
      );
    },
    [queryClient],
  );

  const patchConversation = useCallback(
    (id: string, patch: Partial<Conversation> | ((c: Conversation) => Conversation)) => {
      patchList((list) =>
        list.map((c) =>
          c.id === id ? (typeof patch === "function" ? patch(c) : { ...c, ...patch }) : c,
        ),
      );
    },
    [patchList],
  );

  /**
   * Injeta no cache da lista ATIVA uma conversa que veio de fora dela (busca de
   * contatos, resultado de mensagem, deep-link, irmã, ou a aberta depois de trocar de
   * aba). Sem isso a seleção é derivada de `conversations.find` e cairia no fallback
   * — que não recebe os patches (toggle de IA, mark-read).
   */
  const ensureInList = useCallback(
    (conv: Conversation) => {
      queryClient.setQueryData<ConversationPages>(
        conversationsQueryKey(selectedChannelId, activeTab),
        (old) => (old ? insertIntoPages(old, conv) : old),
      );
    },
    [queryClient, selectedChannelId, activeTab],
  );
```

- [ ] **Step 4: Seleção sobrevive à troca de aba/página** — depois do bloco de
`setActiveConversation` (linha 195), acrescentar:

```ts
  // A conversa aberta precisa estar no cache da aba ATIVA para receber os patches.
  // Antes havia um cache só com todas as abas; agora, ao trocar de aba (ou depois de
  // um refetch que não a traz mais), ela é reinjetada a partir do último objeto
  // conhecido. A aba continua escondendo-a da lista se não pertencer a ela.
  useEffect(() => {
    if (!selectedId || !pagesData || isRefreshing) return;
    if (conversations.some((c) => c.id === selectedId)) return;
    const last = lastSelectedRef.current;
    if (last && last.id === selectedId) ensureInList(last);
  }, [selectedId, pagesData, isRefreshing, conversations, ensureInList]);
```

- [ ] **Step 5: Deep-link** — no fallback (linhas 213-227) trocar a leitura da resposta:

```ts
        const res = await fetch(conversationsListUrl({ leadId }));
        if (!res.ok) return;
        const data = (await res.json()) as ConversationsPage<Conversation>;
        const conv = Array.isArray(data?.conversations) ? data.conversations[0] : null; // a rota já ordena por last_msg_at desc
```

- [ ] **Step 6: Tempo real sobre páginas** — substituir o `useEffect` do Realtime
(linhas 230-328) por:

```ts
  // A aba ativa é lida por ref no handler do Realtime: trocar de aba não pode
  // derrubar e refazer a inscrição (cada re-inscrição tem custo e janela cega).
  const activeTabRef = useRef(activeTab);
  useEffect(() => {
    activeTabRef.current = activeTab;
  }, [activeTab]);

  // Realtime SEM refetch integral por evento (corte de Egress): o payload do
  // UPDATE já traz a linha nova de `conversations` — aplicamos o delta no cache
  // e o preview vem do INSERT de `messages`. Conversa que não está na página
  // carregada é buscada sozinha pelo id (se couber na janela/aba); a invalidação
  // integral (debounced) fica para conversa nova (INSERT) e rajadas grandes.
  useEffect(() => {
    const invalidateAll = () => queryClient.invalidateQueries({ queryKey: ["conversations"] });
    const debouncedInvalidate = debounce(invalidateAll, REFETCH_DEBOUNCE_MS);
    const debouncedCounts = debounce(
      () => queryClient.invalidateQueries({ queryKey: ["conversation-counts"] }),
      REFETCH_DEBOUNCE_MS,
    );

    const pendingUnknown = new Set<string>();
    const ignoredUntil = new Map<string, number>();
    const flushUnknown = debounce(async () => {
      const ids = [...pendingUnknown];
      pendingUnknown.clear();
      if (ids.length === 0) return;
      if (ids.length > MAX_SINGLE_FETCHES) {
        void invalidateAll();
        return;
      }
      const fetched = await Promise.all(ids.map((id) => fetchConversationById(id)));
      const activeKey = conversationsQueryKey(selectedChannelId, activeTabRef.current);
      for (const conv of fetched) {
        if (!conv || isBlockedConversationRow(conv)) continue;
        const [fresh] = applyOverrides([conv]);
        for (const query of queryClient.getQueryCache().findAll({ queryKey: ["conversations"] })) {
          if (!conversationBelongsToKey(fresh, query.queryKey)) continue;
          queryClient.setQueryData<ConversationPages>(query.queryKey, (old) =>
            old ? insertIntoPages(old, fresh, { respectWindow: true }) : old,
          );
        }
        if (!conversationBelongsToKey(fresh, activeKey)) {
          ignoredUntil.set(fresh.id, Date.now() + IGNORE_OUTSIDE_TAB_MS);
        }
      }
    }, REFETCH_DEBOUNCE_MS);

    const applyRowPatch = (row: ConversationRow) => {
      const overrides = {
        forceUnreadZero: recentlyMarkedRef.current.has(row.id),
        pendingFollowup: recentlyToggledFollowupRef.current.get(row.id),
      };
      patchList((prev) => applyConversationUpdate(prev, row, overrides));
      // A regra de bloqueio REMOVE a linha (ver applyConversationUpdate), e a
      // removida pode ser justamente a aberta. A seleção é derivada do cache mas
      // tem fallback para o último objeto conhecido, então sem zerar o id o
      // operador ficaria olhando um chat fantasma — de um lead que acabou de
      // pedir para sair — com o composer ainda montado.
      if (isBlockedConversationRow(row)) {
        setSelectedId((cur) => (cur === row.id ? null : cur));
      }
    };

    const realtimeChannel = supabase
      .channel("conversations-updates")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "conversations" },
        (payload) => {
          debouncedCounts(); // não lidas/total podem ter mudado
          if (payload.eventType === "DELETE") {
            const oldId = (payload.old as { id?: string } | null)?.id;
            if (!oldId) return;
            patchList((prev) => prev.filter((c) => c.id !== oldId));
            // Sem isto a reinjeção da conversa aberta a ressuscitaria na lista.
            setSelectedId((cur) => (cur === oldId ? null : cur));
            return;
          }
          const row = payload.new as ConversationRow;
          // Filtro de canal ativo: eventos de outros canais não pertencem à lista.
          if (selectedChannelId && row.channel_id !== selectedChannelId) return;
          if (payload.eventType === "INSERT") {
            debouncedInvalidate(); // linha crua não tem lead/channel — precisa da API
            return;
          }
          // Patch em todo cache que já conhece a conversa (inclusive o bloqueio, que
          // remove a linha sem precisar dos joins da API).
          applyRowPatch(row);
          if (isBlockedConversationRow(row)) return;

          const activeTab = activeTabRef.current;
          const cached = queryClient.getQueryData<ConversationPages>(
            conversationsQueryKey(selectedChannelId, activeTab),
          );
          if (!cached) {
            debouncedInvalidate(); // aba ainda sem dados (fetch anterior falhou/em voo)
            return;
          }
          if (flattenPages(cached).some((c) => c.id === row.id)) return;
          // Desconhecida: fora da janela carregada → a próxima página a trará; aba que
          // não pode contê-la → ignora; senão busca só ela pelo id.
          if (!isWithinLoadedWindow(cached, row.last_msg_at)) return;
          if (!shouldFetchUnknownRow(row, activeTab)) return;
          if ((ignoredUntil.get(row.id) ?? 0) > Date.now()) return;
          pendingUnknown.add(row.id);
          flushUnknown();
        },
      )
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages" },
        (payload) => {
          // Atualiza só o preview da conversa afetada — paridade com a RPC
          // get_last_messages (última mensagem vence, com prefixo por autor).
          const msg = payload.new as {
            conversation_id?: string | null;
            role?: string | null;
            sent_by?: string | null;
            content?: string | null;
          };
          if (!msg.conversation_id) return;
          const preview = previewFromMessage(msg);
          patchList((prev) =>
            prev.map((c) =>
              c.id === msg.conversation_id
                ? { ...c, last_message_text: preview.text, last_message_direction: preview.direction }
                : c,
            ),
          );
        },
      )
      // Volta do canal = houve um buraco. `postgres_changes` não tem replay, e a
      // lista é mantida por patches em memória, então tudo que aconteceu com o
      // socket fora ficaria defasado para sempre (só o F5 corrigia). Invalidação
      // integral aqui, sem debounce: reconexão é rara e precisa reconciliar já.
      .subscribe(
        onResubscribe(() => {
          void invalidateAll();
          void queryClient.invalidateQueries({ queryKey: ["conversation-counts"] });
        }),
      );

    return () => {
      debouncedInvalidate.cancel();
      debouncedCounts.cancel();
      flushUnknown.cancel();
      supabase.removeChannel(realtimeChannel);
    };
  }, [selectedChannelId, queryClient, supabase, patchList, applyOverrides, fetchConversationById]);
```

(`fetchConversationById` precisa ser declarado ANTES deste efeito — já é, linha 168.)

- [ ] **Step 7: Seleção, mark-read** — `handleSelectConversation` grava o objeto como último
conhecido antes de selecionar:

```ts
  function handleSelectConversation(conv: Conversation) {
    // A lista pode entregar um resultado da busca server-side, que não está no
    // cache — sem injetar, a seleção derivada abriria o chat anterior.
    lastSelectedRef.current = conv;
    ensureInList(conv);
    setSelectedId(conv.id);
    setPendingScrollMessageId(null);
    setMobileView("chat");
  }
```

Em `handleSelectMessageResult`, depois do `ensureInList(conv)`: `lastSelectedRef.current = conv;`.

Em `handleMarkRead`, depois do `await fetch(...mark-read)` (dentro do `try`):

```ts
      void queryClient.invalidateQueries({ queryKey: ["conversation-counts"] });
```

- [ ] **Step 8: Tags do lead aberto e irmãs** — substituir `selectedLeadTags`,
`siblingConversations` e `handleTagToggle` (linhas 434-484) por:

```ts
  const selectedLead = selectedConversation?.leads as Lead | undefined | null;

  // Tags SÓ do lead aberto: o mapa global de `lead_tags` (5,4k linhas) era cortado
  // em 1.000 pelo PostgREST e mostrava tags erradas no painel.
  const { data: selectedLeadTagIds } = useQuery({
    queryKey: ["lead-tags", selectedLeadId],
    enabled: !!selectedLeadId,
    queryFn: async (): Promise<string[]> => {
      const { data, error } = await supabase
        .from("lead_tags")
        .select("tag_id")
        .eq("lead_id", selectedLeadId as string);
      if (error) throw error;
      return (data ?? []).map((row: { tag_id: string }) => row.tag_id);
    },
  });

  const selectedLeadTags = selectedLeadTagIds
    ? tags.filter((t) => selectedLeadTagIds.includes(t.id))
    : [];

  // Conversas irmãs (mesmo lead, outro canal) vêm do servidor: a lista paginada
  // não garante que elas estejam carregadas.
  const { data: siblingRows = [] } = useQuery({
    queryKey: ["conversation-siblings", selectedLeadId, selectedChannelId],
    enabled: !!selectedLeadId,
    queryFn: async ({ signal }): Promise<Conversation[]> => {
      const res = await fetch(
        conversationsListUrl({ channelId: selectedChannelId, leadId: selectedLeadId as string }),
        { signal },
      );
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data?.conversations) ? data.conversations : [];
    },
  });

  const siblingConversations: SiblingConversationSummary[] = selectedConversation
    ? siblingRows
        .filter(
          (c) =>
            c.lead_id === selectedConversation.lead_id &&
            c.id !== selectedConversation.id,
        )
        .map((c) => ({
          id: c.id,
          channelName: c.channels?.name ?? "Outro canal",
        }))
    : [];

  function handleSelectSibling(id: string) {
    const sibling =
      conversations.find((c) => c.id === id) ?? siblingRows.find((c) => c.id === id);
    if (sibling) handleSelectConversation(sibling);
  }

  function handleLeadUpdate(leadId: string, patch: Partial<Lead>) {
    patchList((prev) =>
      prev.map((c) =>
        (c.leads as Lead)?.id === leadId
          ? { ...c, leads: { ...(c.leads as Lead), ...patch } }
          : c,
      ),
    );
  }

  async function handleTagToggle(tagId: string, add: boolean) {
    // Tags do lead ainda não carregadas: gravar agora sobrescreveria as existentes.
    if (!selectedLead || !selectedLeadTagIds) return;

    const newTagIds = add
      ? [...selectedLeadTagIds, tagId]
      : selectedLeadTagIds.filter((id) => id !== tagId);

    const res = await fetch(`/api/leads/${selectedLead.id}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tagIds: newTagIds }),
    });

    if (res.ok) {
      queryClient.setQueryData<string[]>(["lead-tags", selectedLead.id], newTagIds);
    }
  }

  const initialLoading = channelsPending || tagsPending || (convPending && !isRefreshing);
```

Nos dois `<ChatView>`, `onSelectSibling={handleSelectSibling}`.

- [ ] **Step 9: Props da lista e total** — nos dois `<ChatList>`, acrescentar:

```tsx
          unreadTotal={counts?.unread}
          hasMore={!!hasNextPage && !isRefreshing}
          loadingMore={isFetchingNextPage}
          onLoadMore={handleLoadMore}
```

E o texto do estado vazio usa o total do servidor:

```tsx
  const openTotal = counts?.total ?? conversations.length;
  ...
                {openTotal} conversa{openTotal !== 1 ? "s" : ""} aberta{openTotal !== 1 ? "s" : ""}
```

- [ ] **Step 10: Verificar**

```bash
cd /root/crm-wt/cs-p5/frontend
flock /root/crm-wt/_heavy.lock npx eslint "src/app/(authenticated)/conversas/page.tsx" "src/app/(authenticated)/conversas/conversation-pages.ts"
```
Expected: 0 erros.

tsc restrito (não o projeto inteiro): `tsconfig` temporário no scratchpad que estende o do
frontend e inclui só os arquivos do P5 (o grafo de imports deles vem junto):

```bash
cat > /root/crm-wt/cs-p5/frontend/tsconfig.p5.json <<'EOF'
{ "extends": "./tsconfig.json", "compilerOptions": { "noEmit": true, "incremental": false },
  "include": ["next-env.d.ts", "src/app/(authenticated)/conversas/page.tsx",
    "src/app/(authenticated)/conversas/conversation-pages.ts",
    "src/app/api/conversations/route.ts", "src/app/api/conversations/counts/route.ts",
    "src/app/api/conversations/search-contacts/route.ts", "src/app/api/conversations/list-params.ts",
    "src/components/conversas/chat-list.tsx", "src/lib/search.ts"] }
EOF
flock /root/crm-wt/_heavy.lock npx tsc -p tsconfig.p5.json; rm -f tsconfig.p5.json
```
Expected: sem erros nos arquivos do P5 (erro em arquivo de fora do P5 vai para o relatório).

- [ ] **Step 11: Commit**

```bash
cd /root/crm-wt/cs-p5 && git add "frontend/src/app/(authenticated)/conversas/page.tsx"
git commit -m "feat(conversas): página com lista infinita, contadores do servidor, irmãs e tags por lead (P5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5.5 — Verificação final (verification-before-completion)

- [ ] Prova real dos filtros: script temporário (não commitado) que monta as consultas com
  `cursorOrFilter`/`parseTabFilter`/`buildLeadSearchOrFilter` via `@supabase/postgrest-js` contra o
  `p5-postgrest` (PostgREST v14.12 sobre o banco `p5` com seed) e confere linhas esperadas:
  paginação com empate de timestamp e cauda de nulls; aba atacado; "angelucci hiago";
  CNPJ com máscara nos dois sentidos; e-mail.
- [ ] Vitest dos testes do P5 + existentes de conversas/busca:

```bash
cd /root/crm-wt/cs-p5/frontend && flock /root/crm-wt/_heavy.lock npx vitest run \
  src/app/api/conversations src/lib/search.test.ts src/lib/contact-search.test.ts \
  src/lib/conversations-live.test.ts src/lib/message-search.test.ts \
  src/lib/universal-search.test.ts src/lib/active-conversation.test.ts \
  "src/app/(authenticated)/conversas" src/components/conversas
```

- [ ] eslint em todos os arquivos alterados/criados (0 erros; os 3 warnings antigos do
  `chat-list.tsx` são preexistentes).
- [ ] Derrubar o `p5-postgrest` (`docker rm -f p5-postgrest`); o banco `p5` do scratch fica.

## Fora do pacote (reportar, não editar)

- Índice `conversations (last_msg_at desc nulls last, id desc)` — migração (dono: integração/P0).
- `sale-create-modal.tsx`/`quote-create-modal.tsx` (P4), `leads/page.tsx`, `vendas/page.tsx`
  usam `leadMatchesSearch` e ganham a busca por tokens/e-mail/CNPJ sem mudança de código
  (comportamento é superconjunto do anterior).

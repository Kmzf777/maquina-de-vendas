# Busca de mensagens em /conversas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar busca por palavra-chave/frase no conteúdo das mensagens em `/conversas`, estilo WhatsApp (duas seções: Conversas e Mensagens), com pulo + destaque na mensagem ao clicar num resultado.

**Architecture:** Filtro de **contato** continua client-side sobre a lista já carregada. A busca de **conteúdo** (só mensagens do cliente, `role='user'`) é server-side: migration com índice trigram parcial + RPC `search_customer_messages`, e rota `GET /api/conversations/search` que escopa por `getAllowedChannelIds`. O pulo+destaque reusa o `MessageListHandle.scrollToMessage` já existente.

**Tech Stack:** Next.js 16 (App Router, Server Components), Supabase (Postgres + RPC), PostgreSQL `pg_trgm`/`unaccent`, Vitest (helpers puros).

**Spec:** `docs/superpowers/specs/2026-06-25-conversas-message-search-design.md`

**Convenção do projeto:** sem PRs; a migration é aplicada manualmente no Supabase após o merge (ver Task 7). Não usar `localhost` em código (CLAUDE.md §3).

---

## Mapa de arquivos

**Novos:**
- `supabase/migrations/20260625_search_customer_messages.sql` — extensões, `f_unaccent`, índice trigram parcial, RPC.
- `frontend/src/lib/message-search.ts` — helpers puros (escopo de canais, segmentação de destaque).
- `frontend/src/lib/message-search.test.ts` — testes Vitest dos helpers.
- `frontend/src/app/api/conversations/search/route.ts` — rota de busca server-side.
- `frontend/src/components/conversas/message-search-results.tsx` — seção "Mensagens".

**Alterados:**
- `frontend/src/components/conversas/chat-list.tsx` — fetch debounced, duas seções, callback de clique.
- `frontend/src/app/(authenticated)/conversas/page.tsx` — `pendingScrollMessageId` + handler + passar `targetMessageId` ao `ChatView` (desktop e mobile).
- `frontend/src/components/conversas/chat-view.tsx` — prop `targetMessageId` + efeito de scroll.
- `frontend/src/lib/types.ts` — tipo `MessageSearchResult` (se houver arquivo central de tipos).

---

## Task 1: Migration — extensões, índice e RPC

**Files:**
- Create: `supabase/migrations/20260625_search_customer_messages.sql`

- [ ] **Step 1: Escrever a migration completa**

```sql
-- Busca de mensagens do cliente em /conversas (estilo WhatsApp).
-- Substring acento-insensível sobre messages.content (role='user'), escopada por canal.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- unaccent não é IMMUTABLE por padrão; wrapper imutável permite indexar a expressão.
CREATE OR REPLACE FUNCTION f_unaccent(text)
  RETURNS text
  LANGUAGE sql
  IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT unaccent('unaccent', $1) $$;

-- Índice GIN trigram PARCIAL: só mensagens do cliente (casa com o filtro da busca).
CREATE INDEX IF NOT EXISTS idx_messages_content_trgm
  ON messages USING gin (f_unaccent(lower(content)) gin_trgm_ops)
  WHERE role = 'user';

-- RPC: uma linha por conversa, com a mensagem do cliente mais recente que casou.
-- channel_ids NULL => admin (sem restrição). Caso contrário, restringe a esses canais.
CREATE OR REPLACE FUNCTION search_customer_messages(
  search_query text,
  channel_ids uuid[],
  max_results int DEFAULT 50
)
RETURNS TABLE (
  conversation_id uuid,
  message_id uuid,
  snippet text,
  match_created_at timestamptz,
  match_count bigint,
  lead_name text,
  lead_phone text,
  channel_id uuid,
  channel_name text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH matches AS (
    SELECT
      m.id            AS message_id,
      m.conversation_id,
      m.content,
      m.created_at,
      ROW_NUMBER() OVER (
        PARTITION BY m.conversation_id ORDER BY m.created_at DESC
      ) AS rn,
      COUNT(*) OVER (PARTITION BY m.conversation_id) AS match_count
    FROM messages m
    JOIN conversations c ON c.id = m.conversation_id
    WHERE m.role = 'user'
      AND m.content IS NOT NULL
      AND f_unaccent(lower(m.content)) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      AND (channel_ids IS NULL OR c.channel_id = ANY (channel_ids))
  )
  SELECT
    mt.conversation_id,
    mt.message_id,
    mt.content                          AS snippet,
    mt.created_at                       AS match_created_at,
    mt.match_count,
    l.name                             AS lead_name,
    l.phone                            AS lead_phone,
    c.channel_id,
    ch.name                            AS channel_name
  FROM matches mt
  JOIN conversations c ON c.id = mt.conversation_id
  LEFT JOIN leads l    ON l.id = c.lead_id
  LEFT JOIN channels ch ON ch.id = c.channel_id
  WHERE mt.rn = 1
  ORDER BY mt.created_at DESC
  LIMIT GREATEST(max_results, 1);
$$;

GRANT EXECUTE ON FUNCTION search_customer_messages(text, uuid[], int) TO authenticated, service_role, anon;
```

- [ ] **Step 2: Validar a sintaxe localmente (revisão)**

Não há banco local garantido. Revisar manualmente: nomes de colunas (`messages.content`,
`messages.role`, `conversations.channel_id`, `conversations.lead_id`, `leads.name`,
`leads.phone`, `channels.name`) conferem com o schema usado em
`frontend/src/app/api/conversations/route.ts` e `backend/app/conversations/service.py`.
Expected: nomes batem (já confirmados na spec/código existente).

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260625_search_customer_messages.sql
git commit -m "feat(search): migration RPC search_customer_messages + índice trigram"
```

---

## Task 2: Helper puro — interseção de escopo de canais (TDD)

`getAllowedChannelIds` retorna `null` (admin), `string[]` (restrito) ou `[]` (sem canais).
A rota recebe um `channel_id` opcional do cliente e NUNCA pode deixar um vendedor buscar
fora dos seus canais. Esta função resolve o conjunto final de canais a passar ao RPC.

**Files:**
- Create: `frontend/src/lib/message-search.ts`
- Test: `frontend/src/lib/message-search.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { describe, it, expect } from "vitest";
import { resolveSearchChannelScope } from "./message-search";

describe("resolveSearchChannelScope", () => {
  it("admin sem channel_id => null (sem restrição)", () => {
    expect(resolveSearchChannelScope(null, null)).toEqual({ kind: "all" });
  });

  it("admin com channel_id => restringe a esse canal", () => {
    expect(resolveSearchChannelScope(null, "ch1")).toEqual({ kind: "ids", ids: ["ch1"] });
  });

  it("vendedor sem channel_id => seus canais", () => {
    expect(resolveSearchChannelScope(["a", "b"], null)).toEqual({ kind: "ids", ids: ["a", "b"] });
  });

  it("vendedor com channel_id permitido => só esse", () => {
    expect(resolveSearchChannelScope(["a", "b"], "a")).toEqual({ kind: "ids", ids: ["a"] });
  });

  it("vendedor com channel_id NÃO permitido => vazio (bloqueia)", () => {
    expect(resolveSearchChannelScope(["a", "b"], "c")).toEqual({ kind: "empty" });
  });

  it("vendedor sem canais => vazio", () => {
    expect(resolveSearchChannelScope([], null)).toEqual({ kind: "empty" });
  });
});
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd frontend && npm test -- message-search`
Expected: FAIL ("resolveSearchChannelScope is not a function" / módulo não exporta).

- [ ] **Step 3: Implementar o mínimo**

```ts
// frontend/src/lib/message-search.ts

/** Resultado da resolução de escopo de canais para a busca de mensagens. */
export type SearchChannelScope =
  | { kind: "all" }              // admin sem filtro => RPC recebe channel_ids = null
  | { kind: "ids"; ids: string[] } // restringe a esses canais
  | { kind: "empty" };          // nada a buscar (responder [] sem chamar o RPC)

/**
 * Resolve quais canais a busca pode cobrir, dado o escopo do usuário e um
 * channel_id opcional vindo do cliente. Um vendedor NUNCA busca fora dos seus
 * canais: channel_id não permitido => "empty".
 *
 * @param allowed null = admin (todos); string[] = restrito; [] = sem canais.
 * @param requested channel_id do query param (ou null).
 */
export function resolveSearchChannelScope(
  allowed: string[] | null,
  requested: string | null,
): SearchChannelScope {
  if (allowed === null) {
    return requested ? { kind: "ids", ids: [requested] } : { kind: "all" };
  }
  if (allowed.length === 0) return { kind: "empty" };
  if (requested) {
    return allowed.includes(requested)
      ? { kind: "ids", ids: [requested] }
      : { kind: "empty" };
  }
  return { kind: "ids", ids: allowed };
}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd frontend && npm test -- message-search`
Expected: PASS (6 testes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/message-search.ts frontend/src/lib/message-search.test.ts
git commit -m "feat(search): helper resolveSearchChannelScope com testes"
```

---

## Task 3: Helper puro — segmentação de destaque do termo (TDD)

Para destacar o termo no snippet (acento/caixa-insensível), o componente precisa de
segmentos `{text, match}`. Implementar uma busca de substring acento-insensível que
preserva o texto original (não muda acentos exibidos).

**Files:**
- Modify: `frontend/src/lib/message-search.ts`
- Test: `frontend/src/lib/message-search.test.ts`

- [ ] **Step 1: Acrescentar testes que falham**

```ts
import { highlightSegments } from "./message-search";

describe("highlightSegments", () => {
  it("sem query => um segmento não-match", () => {
    expect(highlightSegments("Olá mundo", "")).toEqual([{ text: "Olá mundo", match: false }]);
  });

  it("match simples preserva texto original", () => {
    expect(highlightSegments("Quero um café agora", "cafe")).toEqual([
      { text: "Quero um ", match: false },
      { text: "café", match: true },
      { text: " agora", match: false },
    ]);
  });

  it("case-insensitive", () => {
    expect(highlightSegments("PRECO bom", "preco")).toEqual([
      { text: "PRECO", match: true },
      { text: " bom", match: false },
    ]);
  });

  it("múltiplas ocorrências", () => {
    expect(highlightSegments("oi oi", "oi")).toEqual([
      { text: "oi", match: true },
      { text: " ", match: false },
      { text: "oi", match: true },
    ]);
  });

  it("sem ocorrência => um segmento", () => {
    expect(highlightSegments("nada", "xyz")).toEqual([{ text: "nada", match: false }]);
  });
});
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd frontend && npm test -- message-search`
Expected: FAIL ("highlightSegments is not a function").

- [ ] **Step 3: Implementar**

```ts
// Acrescentar a frontend/src/lib/message-search.ts

export interface HighlightSegment {
  text: string;
  match: boolean;
}

/** Remove acentos para comparação (NFD + strip das marcas combinantes), mantendo
 *  o índice 1:1. Use o range unicode EXPLÍCITO ̀-ͯ (não cole literais). */
function stripAccents(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "");
}

/**
 * Quebra `content` em segmentos marcando onde `query` casa (acento/caixa-insensível).
 * O texto de cada segmento é SEMPRE o original (acentos preservados na exibição).
 * NOTA: stripAccents preserva contagem de caracteres para os diacríticos combinantes
 * comuns do português (1 base + 1 combinante → base), mantendo os índices alinhados.
 */
export function highlightSegments(content: string, query: string): HighlightSegment[] {
  const q = query.trim();
  if (!q) return [{ text: content, match: false }];

  const haystack = stripAccents(content).toLowerCase();
  const needle = stripAccents(q).toLowerCase();
  if (!needle) return [{ text: content, match: false }];

  const segments: HighlightSegment[] = [];
  let from = 0;
  let idx = haystack.indexOf(needle, from);
  if (idx === -1) return [{ text: content, match: false }];

  while (idx !== -1) {
    if (idx > from) segments.push({ text: content.slice(from, idx), match: false });
    segments.push({ text: content.slice(idx, idx + needle.length), match: true });
    from = idx + needle.length;
    idx = haystack.indexOf(needle, from);
  }
  if (from < content.length) segments.push({ text: content.slice(from), match: false });
  return segments;
}
```

- [ ] **Step 4: Rodar e confirmar passagem**

Run: `cd frontend && npm test -- message-search`
Expected: PASS (todos os testes do arquivo).

> Nota sobre o caso "café"/"cafe": diacríticos combinantes (NFD) preservam o comprimento
> base, então `idx`/`length` em `haystack` alinham com `content`. Se algum teste de acento
> falhar por normalização pré-composta, o teste acima ("café") detecta — ajustar usando
> mapeamento de índices só se necessário (YAGNI: a maioria dos dados é NFC simples).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/message-search.ts frontend/src/lib/message-search.test.ts
git commit -m "feat(search): helper highlightSegments com testes"
```

---

## Task 4: Tipo do resultado de busca

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Localizar o arquivo de tipos**

Run: `cd frontend && npm run type-check`
Confirmar que `@/lib/types` existe (usado em `page.tsx`, `chat-list.tsx`).

- [ ] **Step 2: Adicionar o tipo**

```ts
// Acrescentar a frontend/src/lib/types.ts

/** Uma conversa com mensagem(ns) do cliente que casaram a busca por conteúdo. */
export interface MessageSearchResult {
  conversation_id: string;
  message_id: string;
  snippet: string;
  match_created_at: string;
  match_count: number;
  lead_name: string | null;
  lead_phone: string | null;
  channel_id: string;
  channel_name: string | null;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(search): tipo MessageSearchResult"
```

---

## Task 5: Rota de busca server-side

**Files:**
- Create: `frontend/src/app/api/conversations/search/route.ts`

- [ ] **Step 1: Implementar a rota**

```ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { resolveSearchChannelScope } from "@/lib/message-search";

const MIN_QUERY_LEN = 2;
const MAX_RESULTS = 50;

export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { searchParams } = new URL(request.url);
  const q = (searchParams.get("q") || "").trim();
  const channelId = searchParams.get("channel_id");

  // Query curta: nada a buscar (não chama o RPC).
  if (q.length < MIN_QUERY_LEN) {
    return NextResponse.json([]);
  }

  // Escopo de canais do usuário. Falha de auth => 401 (nunca [] silencioso).
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
    return NextResponse.json([]);
  }

  const { data, error } = await supabase.rpc("search_customer_messages", {
    search_query: q,
    channel_ids: scope.kind === "all" ? null : scope.ids,
    max_results: MAX_RESULTS,
  });

  // Erro do RPC: 500 (a UI mantém o estado anterior; nunca [] silencioso em erro).
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data ?? []);
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npm run type-check`
Expected: sem erros novos.

- [ ] **Step 3: Lint**

Run: `cd frontend && npm run lint`
Expected: sem erros novos no arquivo criado.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/api/conversations/search/route.ts
git commit -m "feat(search): rota GET /api/conversations/search escopada por canal"
```

---

## Task 6: Componente da seção "Mensagens"

**Files:**
- Create: `frontend/src/components/conversas/message-search-results.tsx`

- [ ] **Step 1: Implementar o componente**

```tsx
"use client";

import type { MessageSearchResult } from "@/lib/types";
import { highlightSegments } from "@/lib/message-search";
import { formatRelativeTime } from "@/lib/datetime";

interface MessageSearchResultsProps {
  query: string;
  results: MessageSearchResult[];
  loading: boolean;
  onSelect: (conversationId: string, messageId: string) => void;
}

function getInitial(name: string | null | undefined): string {
  if (!name) return "?";
  return name.charAt(0).toUpperCase();
}

export function MessageSearchResults({ query, results, loading, onSelect }: MessageSearchResultsProps) {
  if (loading) {
    return (
      <div className="px-3 py-3 flex items-center gap-2 text-[11px] text-[#7b7b78]">
        <span className="w-3 h-3 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin flex-shrink-0" />
        Buscando mensagens...
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <p className="text-[#7b7b78] text-xs px-3 py-3">Nenhuma mensagem encontrada.</p>
    );
  }

  return (
    <div>
      {results.map((r) => {
        const displayName = r.lead_name || r.lead_phone || "Desconhecido";
        const segments = highlightSegments(r.snippet, query);
        return (
          <button
            key={r.message_id}
            onClick={() => onSelect(r.conversation_id, r.message_id)}
            className="w-full flex items-start gap-3 px-3 py-2.5 text-left hover:bg-[#faf9f6] rounded-[6px] mx-2 cursor-pointer"
            style={{ width: "calc(100% - 16px)" }}
          >
            <div className="w-9 h-9 rounded-full bg-[#8a8a80] flex items-center justify-center text-white text-sm font-medium flex-shrink-0 mt-0.5">
              {getInitial(displayName)}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1">
                <span className="text-sm font-semibold text-[#111111] truncate">{displayName}</span>
                <span className="ml-auto text-[10px] text-[#7b7b78] flex-shrink-0">
                  {formatRelativeTime(r.match_created_at)}
                </span>
              </div>
              <p className="text-xs text-[#7b7b78] mt-0.5 line-clamp-2">
                {segments.map((seg, i) =>
                  seg.match ? (
                    <mark key={i} className="bg-yellow-200 text-[#111111] rounded-sm px-0.5">
                      {seg.text}
                    </mark>
                  ) : (
                    <span key={i}>{seg.text}</span>
                  ),
                )}
              </p>
              {r.match_count > 1 && (
                <span className="text-[10px] text-[#9b9b98]">{r.match_count} mensagens</span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Confirmar que `formatRelativeTime` aceita string ISO**

Verificar em `frontend/src/lib/datetime.ts` a assinatura (já usada em `chat-list.tsx` com
`conv.last_msg_at`). Se aceitar `string | null`, ok.
Expected: assinatura compatível.

- [ ] **Step 3: Type-check + lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: sem erros novos.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/message-search-results.tsx
git commit -m "feat(search): componente da seção Mensagens com destaque do termo"
```

---

## Task 7: Wiring no chat-list (duas seções + fetch debounced)

**Files:**
- Modify: `frontend/src/components/conversas/chat-list.tsx`

- [ ] **Step 1: Adicionar prop de callback à interface**

Em `ChatListProps`, adicionar:

```ts
  onSelectMessageResult?: (conversationId: string, messageId: string) => void;
```

E ao destructuring de `ChatList({ ... })`: `onSelectMessageResult,`.

- [ ] **Step 2: Adicionar imports e estado de busca server-side**

No topo do arquivo, importar:

```ts
import type { MessageSearchResult } from "@/lib/types";
import { MessageSearchResults } from "@/components/conversas/message-search-results";
```

Dentro do componente, abaixo de `const [search, setSearch] = useState("");`:

```ts
  const [msgResults, setMsgResults] = useState<MessageSearchResult[]>([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const searchAbortRef = useRef<AbortController | null>(null);

  // Busca server-side de conteúdo (>= 2 chars), debounced, latest-wins.
  useEffect(() => {
    const q = search.trim();
    if (q.length < 2) {
      setMsgResults([]);
      setMsgLoading(false);
      searchAbortRef.current?.abort();
      return;
    }
    setMsgLoading(true);
    const handle = setTimeout(async () => {
      searchAbortRef.current?.abort();
      const ac = new AbortController();
      searchAbortRef.current = ac;
      try {
        const url = selectedChannelId
          ? `/api/conversations/search?q=${encodeURIComponent(q)}&channel_id=${selectedChannelId}`
          : `/api/conversations/search?q=${encodeURIComponent(q)}`;
        const res = await fetch(url, { signal: ac.signal });
        if (!res.ok) { setMsgResults([]); return; }
        const data = await res.json();
        setMsgResults(Array.isArray(data) ? data : []);
      } catch (err) {
        if ((err as Error)?.name === "AbortError") return;
        setMsgResults([]);
      } finally {
        if (!ac.signal.aborted) setMsgLoading(false);
      }
    }, 300);
    return () => clearTimeout(handle);
  }, [search, selectedChannelId]);
```

- [ ] **Step 3: Renderizar as duas seções quando há query**

Substituir o bloco `{/* Chat list */}` (a `<div className="flex-1 overflow-y-auto py-1">`
que mapeia `filteredConversations`) para, quando `search.trim().length >= 2`, exibir:

```tsx
      {/* Lista / resultados de busca */}
      <div className="flex-1 overflow-y-auto py-1">
        {search.trim().length >= 2 ? (
          <>
            <p className="px-3 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-[#9b9b98]">
              Conversas
            </p>
            {filteredConversations.length === 0 ? (
              <p className="text-[#7b7b78] text-xs px-3 py-2">Nenhum contato encontrado.</p>
            ) : (
              filteredConversations.map((conv) => renderConversationRow(conv))
            )}
            <p className="px-3 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-[#9b9b98]">
              Mensagens
            </p>
            <MessageSearchResults
              query={search}
              results={msgResults}
              loading={msgLoading}
              onSelect={(cid, mid) => onSelectMessageResult?.(cid, mid)}
            />
          </>
        ) : (
          <>
            {filteredConversations.length === 0 && (
              <p className="text-[#7b7b78] text-sm text-center py-8">
                Nenhuma conversa encontrada.
              </p>
            )}
            {filteredConversations.map((conv) => renderConversationRow(conv))}
          </>
        )}
      </div>
```

- [ ] **Step 4: Extrair a renderização da linha para `renderConversationRow`**

Mover o corpo do `.map((conv) => { ... })` atual (todo o `<button>` da conversa) para uma
função interna `renderConversationRow(conv: Conversation)` declarada dentro do componente,
retornando o mesmo JSX (mantendo `key={conv.id}`). Isso evita duplicar o markup entre os
dois ramos. Não alterar a lógica de `filteredConversations`.

- [ ] **Step 5: Type-check + lint + build**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: sem erros novos.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/conversas/chat-list.tsx
git commit -m "feat(search): duas seções (Conversas/Mensagens) na lista com busca debounced"
```

---

## Task 8: Wiring página + ChatView (pulo + destaque)

**Files:**
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx`
- Modify: `frontend/src/components/conversas/chat-view.tsx`

- [ ] **Step 1: ChatView — aceitar `targetMessageId` e rolar**

Em `ChatViewProps` adicionar:

```ts
  targetMessageId?: string | null;
  onTargetConsumed?: () => void;
```

No destructuring do componente adicionar `targetMessageId, onTargetConsumed,`.
Depois do `const { messages, loading, refetch } = useRealtimeMessages(...)`, adicionar:

```ts
  // Pulo para a mensagem buscada: espera as mensagens carregarem (DOM populado) e
  // chama o scrollToMessage já existente; dispara uma única vez por alvo.
  useEffect(() => {
    if (!targetMessageId || loading) return;
    const raf = requestAnimationFrame(() => {
      messageListRef.current?.scrollToMessage(targetMessageId);
      onTargetConsumed?.();
    });
    return () => cancelAnimationFrame(raf);
  }, [targetMessageId, loading, conversation.id, onTargetConsumed]);
```

- [ ] **Step 2: page.tsx — estado e handler**

Abaixo de `const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);`:

```ts
  const [pendingScrollMessageId, setPendingScrollMessageId] = useState<string | null>(null);
```

Adicionar handler (perto de `handleSelectConversation`):

```ts
  function handleSelectMessageResult(conversationId: string, messageId: string) {
    const conv = conversations.find((c) => c.id === conversationId);
    if (!conv) return; // a lista vem completa; ausência => fora do escopo, ignora.
    setSelectedConversation(conv);
    setPendingScrollMessageId(messageId);
    setMobileView("chat");
  }
```

- [ ] **Step 3: page.tsx — passar props ao ChatList e ChatView (mobile e desktop)**

Em ambas as `<ChatList ... />` (mobile e desktop) adicionar:

```tsx
          onSelectMessageResult={handleSelectMessageResult}
```

Em ambas as `<ChatView ... />` (mobile e desktop) adicionar:

```tsx
            targetMessageId={pendingScrollMessageId}
            onTargetConsumed={() => setPendingScrollMessageId(null)}
```

- [ ] **Step 4: Limpar alvo ao trocar de conversa manualmente**

Em `handleSelectConversation`, adicionar `setPendingScrollMessageId(null);` para não rolar
para uma mensagem antiga ao abrir outra conversa pela lista.

- [ ] **Step 5: Type-check + lint + build**

Run: `cd frontend && npm run type-check && npm run lint && npm run build`
Expected: build conclui sem erros.

- [ ] **Step 6: Commit**

```bash
git add "frontend/src/app/(authenticated)/conversas/page.tsx" frontend/src/components/conversas/chat-view.tsx
git commit -m "feat(search): pulo + destaque na mensagem ao clicar num resultado"
```

---

## Task 9: Verificação final

- [ ] **Step 1: Rodar toda a suíte de testes do frontend**

Run: `cd frontend && npm test`
Expected: todos passam (inclui `message-search.test.ts`).

- [ ] **Step 2: Build de produção**

Run: `cd frontend && npm run build`
Expected: sucesso.

- [ ] **Step 3: Smoke manual (documentar resultado)**

Pré-requisito: aplicar `supabase/migrations/20260625_search_customer_messages.sql` no
Supabase de dev (a busca de Mensagens depende do RPC). Sem isso, a seção Conversas
funciona e a seção Mensagens retorna erro/vazio.

Checklist manual em `/conversas`:
- Digitar < 2 chars: comportamento atual (sem seção Mensagens).
- Digitar >= 2 chars: aparecem as seções "Conversas" e "Mensagens".
- Termo que existe numa mensagem do cliente: aparece resultado com snippet destacado.
- Clicar no resultado: abre a conversa e rola até a mensagem, com highlight amarelo.
- Trocar filtro de canal: resultados respeitam o canal.
- Mobile: clique no resultado leva à conversa (`mobileView = "chat"`).

- [ ] **Step 4: Atualizar a memória do projeto**

Registrar em `MEMORY.md` + arquivo próprio: feature de busca de mensagens, branch,
migration pendente no Supabase, estado (code-complete / pushed).

---

## Pós-merge (convenção do projeto)

1. `git pull origin master` e `git push origin feat/conversas-message-search:master` (com autorização do usuário).
2. Aplicar `supabase/migrations/20260625_search_customer_messages.sql` no Supabase de produção.
3. Smoke test em produção.

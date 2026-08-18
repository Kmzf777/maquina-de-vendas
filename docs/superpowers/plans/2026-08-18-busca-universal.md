# Busca Universal (`/busca`) + fix da busca em `/vendas` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir a busca local de deals em `/vendas` e criar `/busca`, uma página de busca universal (leads, deals,
vendas, conversas) no menu lateral, com abas por tipo, filtros e navegação para a página existente de cada item.

**Architecture:** Fan-out no servidor — uma rota `/api/search` chama 3 RPCs Postgres novas (`search_leads`,
`search_deals`, `search_sales`) em paralelo, mais o RPC `search_customer_messages` já existente (estendido com
`docs_only` e paginação). Escopo por role reaproveita `getAllowedPipelineIds`/`getAllowedChannelIds` já existentes.
Front: um hook com debounce (`useUniversalSearch`) alimenta uma página em abas; cliques navegam para `/leads`,
`/vendas`, `/painel-vendas`, `/conversas` via query param (deep-link), mecanismo que hoje só `/conversas` tem.

**Tech Stack:** Next.js App Router (client components), Supabase Postgres (RPCs `SECURITY DEFINER`, `pg_trgm` +
`unaccent`), Vitest para testes de lógica pura em `lib/`.

**Referência:** spec completa em `docs/superpowers/specs/2026-08-18-busca-universal-design.md`.

**Nota de implementação (desvio consciente do texto da spec, mesmo comportamento):** a spec menciona `GET
/api/leads/[id]` como pré-requisito de deep-link. Investigação mostrou que `useRealtimeLeads()` já carrega a tabela
`leads` inteira sem paginação (loop até `data.length < pageSize`) — o lead buscado já está na lista carregada, então
o deep-link de `/leads` não precisa de rota nova (mesmo padrão que `/conversas` já usa: achar no array já carregado).
`/vendas` (deals por pipeline) e `/painel-vendas` (vendas paginadas por período) continuam precisando de rota `GET`
nova, pois suas listas são filtradas/paginadas.

**Correções descobertas durante a execução (incorporadas às tasks abaixo):**

1. **`proxy.ts` faz parte do escopo.** `frontend/src/lib/auth/proxy-coverage.test.ts` enumera automaticamente os
   diretórios de `src/app/api` e `src/app/(authenticated)` e falha se algum não estiver no `config.matcher` de
   `frontend/src/proxy.ts`. Criar `app/api/search/` (Task 5) e `app/(authenticated)/busca/` (Task 8) **quebra a
   suíte** e, pior, deixa as rotas novas fora do gating de auth do proxy, se o matcher não for atualizado junto.
   Task 5 adiciona `"/api/search/:path*"`; Task 9 adiciona `"/busca/:path*"`. (`/api/sales/:path*` e
   `/api/deals/:path*` já estão no matcher — verificado.)
2. **Grants das RPCs: `service_role` apenas.** A auditoria de 2026-07-04
   (`20260704_revoke_search_customer_messages_public.sql`) revogou `EXECUTE` de `PUBLIC`/`anon`/`authenticated` em
   `search_customer_messages` porque a função é `SECURITY DEFINER` e trata escopo `NULL` como "sem restrição". Como
   a migration da Task 2 faz `DROP`+`CREATE` dessa função, o OID novo perde aquele revoke e o `CREATE FUNCTION`
   reconcede `EXECUTE` a `PUBLIC` por padrão. A Task 2 portanto reaplica `REVOKE ... FROM PUBLIC, anon,
   authenticated` + `GRANT ... TO service_role` nas **quatro** funções. O único chamador é `/api/search`, que usa
   `getServiceSupabase()` (service role key) — verificado em `frontend/src/lib/supabase/api.ts`.
3. **`GET /api/deals/[id]` precisa de guarda de escopo.** `PATCH`/`DELETE` nesse arquivo já validam permissão de
   funil; o `GET` novo (Task 3) sem guarda deixaria um vendedor ler deal de funil alheio por id. Task 3 aplica
   `getAllowedPipelineIds()` e devolve **404** (não 403) quando fora do escopo, para não confirmar existência por
   enumeração. `GET /api/sales/[id]` fica **sem** guarda de propósito — vendas são globais hoje (spec §5).

---

### Task 1: Fix da busca local em `/vendas`

**Files:**
- Modify: `frontend/src/lib/search.ts`
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx:258-271`
- Test: `frontend/src/lib/search.test.ts`

- [ ] **Step 1: Escrever o teste que falha para `dealMatchesSearch`**

Adicione ao final de `frontend/src/lib/search.test.ts`:

```ts
describe("dealMatchesSearch", () => {
  const deal = {
    title: "Kit Canastra Atacado",
    leads: {
      name: "José da Silva",
      company: "Café Canastra",
      phone: "5534999998888",
      nome_fantasia: "Canastra Grãos",
    },
  };

  it("returns true for empty query", () => {
    expect(dealMatchesSearch("", deal)).toBe(true);
  });

  it("matches deal title accent-insensitively", () => {
    expect(dealMatchesSearch("atacado", deal)).toBe(true);
    expect(dealMatchesSearch("CANASTRA", deal)).toBe(true);
  });

  it("matches lead name, company and nome_fantasia accent-insensitively", () => {
    expect(dealMatchesSearch("jose", deal)).toBe(true);
    expect(dealMatchesSearch("cafe", deal)).toBe(true);
    expect(dealMatchesSearch("graos", deal)).toBe(true);
  });

  it("matches phone typed with formatting", () => {
    expect(dealMatchesSearch("(34) 99999-8888", deal)).toBe(true);
  });

  it("returns false when nothing matches", () => {
    expect(dealMatchesSearch("zzz", deal)).toBe(false);
  });

  it("tolerates missing leads join", () => {
    expect(dealMatchesSearch("x", { title: "Sem lead" })).toBe(false);
  });
});
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/search.test.ts`
Expected: FAIL com `dealMatchesSearch is not a function` (ou erro de import).

- [ ] **Step 3: Implementar `dealMatchesSearch` em `lib/search.ts`**

Adicione ao final de `frontend/src/lib/search.ts` (depois de `leadMatchesSearch`):

```ts
export interface DealSearchFields {
  title: string;
  leads?: LeadSearchFields | null;
}

/**
 * True when `query` matches o deal pelo título OU pelos campos do lead vinculado
 * (mesma lógica de `leadMatchesSearch`, accent-insensitive + telefone por dígitos).
 * Empty/whitespace query matches everything.
 */
export function dealMatchesSearch(query: string, deal: DealSearchFields): boolean {
  const raw = query.trim();
  if (!raw) return true;

  const q = foldText(raw);
  if (foldText(deal.title).includes(q)) return true;

  if (deal.leads && leadMatchesSearch(query, deal.leads)) return true;

  return false;
}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/search.test.ts`
Expected: PASS (todos os `describe` blocks, incluindo `dealMatchesSearch`).

- [ ] **Step 5: Trocar o predicado em `vendas/page.tsx`**

Em `frontend/src/app/(authenticated)/vendas/page.tsx`, adicione o import (perto dos outros imports de `@/lib`,
por exemplo logo abaixo de `import type { Deal, Pipeline, PipelineStage } from "@/lib/types";`):

```ts
import { dealMatchesSearch } from "@/lib/search";
```

Troque o bloco (linhas 258-271, dentro de `filteredDeals`):

```ts
    if (search) {
      const q = search.toLowerCase();
      const lead = d.leads;
      const match =
        d.title.toLowerCase().includes(q) ||
        (lead?.name || "").toLowerCase().includes(q) ||
        (lead?.company || "").toLowerCase().includes(q) ||
        (lead?.phone || "").includes(q);
      if (!match) return false;
    }
```

por:

```ts
    if (search && !dealMatchesSearch(search, d)) return false;
```

- [ ] **Step 6: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo.

Rode o app (`Run All Dev (CRM & Backend)` no VS Code, ou `npm run dev` em `frontend/`), abra `/vendas`, digite um nome
com acento (ex.: "jose") e confirme que deals cujo lead se chama "José" aparecem mesmo sem digitar o acento; digite um
telefone formatado (`(34) 99999-8888`) e confirme que casa com o telefone salvo sem formatação.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/search.ts frontend/src/lib/search.test.ts "frontend/src/app/(authenticated)/vendas/page.tsx"
git commit -m "fix(vendas): busca de deal ignora acento e aceita telefone formatado

Reusa o mesmo foldText/phone-match que /leads já usa. Continua um
filtro client-side (só o funil aberto) — a busca cross-funil de
verdade é resolvida pela nova /busca.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Migration — RPCs de busca (leads, deals, sales, extensão de mensagens)

**Files:**
- Create: `supabase/migrations/20260818_universal_search.sql`

- [ ] **Step 1: Escrever a migration completa**

Crie `supabase/migrations/20260818_universal_search.sql`:

```sql
-- Busca universal (/busca): 3 RPCs novas (leads, deals, sales) seguindo o
-- mesmo padrão de unaccent+trigram de 20260812_search_all_messages.sql, mais
-- uma extensão não-destrutiva de search_customer_messages (docs_only + paginação
-- + lead_id, necessário para o deep-link /conversas?lead_id=).

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- f_unaccent já existe (criado em 20260812_search_all_messages.sql); CREATE OR
-- REPLACE aqui é só defensivo caso esta migration rode isolada num ambiente novo.
CREATE OR REPLACE FUNCTION f_unaccent(text)
  RETURNS text
  LANGUAGE sql
  IMMUTABLE PARALLEL SAFE STRICT
  SET search_path = extensions, public, pg_catalog
AS $$ SELECT unaccent('unaccent', $1) $$;

-- ============================================================
-- search_leads
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_leads_name_trgm
  ON leads USING gin (f_unaccent(lower(name)) gin_trgm_ops) WHERE name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_company_trgm
  ON leads USING gin (f_unaccent(lower(company)) gin_trgm_ops) WHERE company IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_razao_social_trgm
  ON leads USING gin (f_unaccent(lower(razao_social)) gin_trgm_ops) WHERE razao_social IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_nome_fantasia_trgm
  ON leads USING gin (f_unaccent(lower(nome_fantasia)) gin_trgm_ops) WHERE nome_fantasia IS NOT NULL;

DROP FUNCTION IF EXISTS search_leads(text, text, timestamptz, timestamptz, int, int);

-- Leads não têm dono (ver spec §5): sem parâmetro de escopo por role.
-- p_stage filtra pelo mesmo campo `stage` (segmento: secretaria/atacado/
-- private_label/exportacao/consumo) que a página /leads já usa como filtro.
CREATE OR REPLACE FUNCTION search_leads(
  search_query text,
  p_stage text DEFAULT NULL,
  p_created_after timestamptz DEFAULT NULL,
  p_created_before timestamptz DEFAULT NULL,
  max_results int DEFAULT 20,
  p_offset int DEFAULT 0
)
RETURNS TABLE (
  id uuid,
  name text,
  company text,
  phone text,
  status text,
  stage text,
  nome_fantasia text,
  cnpj text,
  created_at timestamptz,
  total_count bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH matches AS (
    SELECT l.*
    FROM leads l
    WHERE (
      f_unaccent(lower(coalesce(l.name, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.company, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.razao_social, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.nome_fantasia, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR (
        regexp_replace(search_query, '\D', '', 'g') <> ''
        AND regexp_replace(l.phone, '\D', '', 'g') LIKE '%' || regexp_replace(search_query, '\D', '', 'g') || '%'
      )
    )
    AND (p_stage IS NULL OR l.stage = p_stage)
    AND (p_created_after IS NULL OR l.created_at >= p_created_after)
    AND (p_created_before IS NULL OR l.created_at <= p_created_before)
  )
  SELECT
    m.id, m.name, m.company, m.phone, m.status, m.stage, m.nome_fantasia, m.cnpj, m.created_at,
    COUNT(*) OVER() AS total_count
  FROM matches m
  ORDER BY m.created_at DESC
  LIMIT GREATEST(max_results, 1)
  OFFSET GREATEST(p_offset, 0);
$$;

GRANT EXECUTE ON FUNCTION search_leads(text, text, timestamptz, timestamptz, int, int) TO authenticated, service_role;

-- ============================================================
-- search_deals
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_deals_title_trgm
  ON deals USING gin (f_unaccent(lower(title)) gin_trgm_ops);

DROP FUNCTION IF EXISTS search_deals(text, uuid[], uuid, uuid, timestamptz, timestamptz, int, int);

-- pipeline_ids = NULL -> admin, sem restrição. Vendedor: array de pipelines
-- próprios+universais (mesmo getAllowedPipelineIds() de /api/pipelines).
CREATE OR REPLACE FUNCTION search_deals(
  search_query text,
  pipeline_ids uuid[],
  p_pipeline_id uuid DEFAULT NULL,
  p_stage_id uuid DEFAULT NULL,
  p_created_after timestamptz DEFAULT NULL,
  p_created_before timestamptz DEFAULT NULL,
  max_results int DEFAULT 20,
  p_offset int DEFAULT 0
)
RETURNS TABLE (
  id uuid,
  title text,
  value numeric,
  pipeline_id uuid,
  pipeline_name text,
  stage_id uuid,
  stage_label text,
  lead_id uuid,
  lead_name text,
  lead_phone text,
  created_at timestamptz,
  total_count bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH matches AS (
    SELECT d.*
    FROM deals d
    JOIN leads l ON l.id = d.lead_id
    WHERE (
      f_unaccent(lower(d.title)) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.name, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.company, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.nome_fantasia, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR (
        regexp_replace(search_query, '\D', '', 'g') <> ''
        AND regexp_replace(l.phone, '\D', '', 'g') LIKE '%' || regexp_replace(search_query, '\D', '', 'g') || '%'
      )
    )
    AND (pipeline_ids IS NULL OR d.pipeline_id = ANY(pipeline_ids))
    AND (p_pipeline_id IS NULL OR d.pipeline_id = p_pipeline_id)
    AND (p_stage_id IS NULL OR d.stage_id = p_stage_id)
    AND (p_created_after IS NULL OR d.created_at >= p_created_after)
    AND (p_created_before IS NULL OR d.created_at <= p_created_before)
  )
  SELECT
    m.id, m.title, m.value, m.pipeline_id, p.name AS pipeline_name,
    m.stage_id, ps.label AS stage_label,
    m.lead_id, l.name AS lead_name, l.phone AS lead_phone,
    m.created_at,
    COUNT(*) OVER() AS total_count
  FROM matches m
  JOIN leads l ON l.id = m.lead_id
  LEFT JOIN pipelines p ON p.id = m.pipeline_id
  LEFT JOIN pipeline_stages ps ON ps.id = m.stage_id
  ORDER BY m.created_at DESC
  LIMIT GREATEST(max_results, 1)
  OFFSET GREATEST(p_offset, 0);
$$;

GRANT EXECUTE ON FUNCTION search_deals(text, uuid[], uuid, uuid, timestamptz, timestamptz, int, int) TO authenticated, service_role;

-- ============================================================
-- search_sales
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_sales_product_trgm
  ON sales USING gin (f_unaccent(lower(product)) gin_trgm_ops) WHERE product IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sales_notes_trgm
  ON sales USING gin (f_unaccent(lower(notes)) gin_trgm_ops) WHERE notes IS NOT NULL;

DROP FUNCTION IF EXISTS search_sales(text, timestamptz, timestamptz, int, int);

-- Vendas não têm dono (ver spec §5): sem parâmetro de escopo por role.
CREATE OR REPLACE FUNCTION search_sales(
  search_query text,
  p_sold_after timestamptz DEFAULT NULL,
  p_sold_before timestamptz DEFAULT NULL,
  max_results int DEFAULT 20,
  p_offset int DEFAULT 0
)
RETURNS TABLE (
  id uuid,
  product text,
  value numeric,
  sold_at timestamptz,
  notes text,
  lead_id uuid,
  lead_name text,
  lead_phone text,
  deal_id uuid,
  deal_title text,
  total_count bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH matches AS (
    SELECT s.*
    FROM sales s
    JOIN leads l ON l.id = s.lead_id
    WHERE (
      f_unaccent(lower(coalesce(s.product, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(s.notes, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.name, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.company, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR (
        regexp_replace(search_query, '\D', '', 'g') <> ''
        AND regexp_replace(l.phone, '\D', '', 'g') LIKE '%' || regexp_replace(search_query, '\D', '', 'g') || '%'
      )
    )
    AND (p_sold_after IS NULL OR s.sold_at >= p_sold_after)
    AND (p_sold_before IS NULL OR s.sold_at <= p_sold_before)
  )
  SELECT
    m.id, m.product, m.value, m.sold_at, m.notes,
    m.lead_id, l.name AS lead_name, l.phone AS lead_phone,
    m.deal_id, d.title AS deal_title,
    COUNT(*) OVER() AS total_count
  FROM matches m
  JOIN leads l ON l.id = m.lead_id
  LEFT JOIN deals d ON d.id = m.deal_id
  ORDER BY m.sold_at DESC
  LIMIT GREATEST(max_results, 1)
  OFFSET GREATEST(p_offset, 0);
$$;

GRANT EXECUTE ON FUNCTION search_sales(text, timestamptz, timestamptz, int, int) TO authenticated, service_role;

-- ============================================================
-- search_customer_messages: extensão não-destrutiva
-- (docs_only, paginação via p_offset, e lead_id p/ o deep-link /conversas?lead_id=)
-- ============================================================

DROP FUNCTION IF EXISTS search_customer_messages(text, uuid[], int);

CREATE OR REPLACE FUNCTION search_customer_messages(
  search_query text,
  channel_ids uuid[],
  max_results int DEFAULT 50,
  docs_only boolean DEFAULT false,
  p_offset int DEFAULT 0
)
RETURNS TABLE (
  conversation_id uuid,
  message_id uuid,
  snippet text,
  match_created_at timestamptz,
  match_count bigint,
  lead_id uuid,
  lead_name text,
  lead_phone text,
  channel_id uuid,
  channel_name text,
  sent_by text,
  total_count bigint
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
      COALESCE(NULLIF(btrim(m.content), ''), m.document_name) AS snippet,
      m.created_at,
      m.sent_by,
      ROW_NUMBER() OVER (
        PARTITION BY m.conversation_id ORDER BY m.created_at DESC
      ) AS rn,
      COUNT(*) OVER (PARTITION BY m.conversation_id) AS match_count
    FROM messages m
    JOIN conversations c ON c.id = m.conversation_id
    WHERE m.role IN ('user', 'assistant')
      AND (
        CASE WHEN docs_only THEN
          m.document_name IS NOT NULL
          AND f_unaccent(lower(m.document_name)) LIKE '%' || f_unaccent(lower(search_query)) || '%'
        ELSE
          (m.content IS NOT NULL
            AND f_unaccent(lower(m.content)) LIKE '%' || f_unaccent(lower(search_query)) || '%')
          OR (m.document_name IS NOT NULL
            AND f_unaccent(lower(m.document_name)) LIKE '%' || f_unaccent(lower(search_query)) || '%')
        END
      )
      AND (channel_ids IS NULL OR c.channel_id = ANY (channel_ids))
  ),
  deduped AS (
    SELECT *, COUNT(*) OVER() AS total_count
    FROM matches
    WHERE rn = 1
  )
  SELECT
    d.conversation_id, d.message_id, d.snippet, d.created_at AS match_created_at,
    d.match_count,
    c.lead_id, l.name AS lead_name, l.phone AS lead_phone,
    c.channel_id, ch.name AS channel_name, d.sent_by, d.total_count
  FROM deduped d
  JOIN conversations c  ON c.id = d.conversation_id
  LEFT JOIN leads l     ON l.id = c.lead_id
  LEFT JOIN channels ch ON ch.id = c.channel_id
  ORDER BY d.created_at DESC
  LIMIT GREATEST(max_results, 1)
  OFFSET GREATEST(p_offset, 0);
$$;

-- anon permanece SEM acesso (revogado em 20260704_revoke_search_customer_messages_public.sql).
GRANT EXECUTE ON FUNCTION search_customer_messages(text, uuid[], int, boolean, int) TO authenticated, service_role;
```

- [ ] **Step 2: Revisar a sintaxe**

Não há harness de teste de SQL/Postgres neste repo (migrations são aplicadas manualmente no Supabase — ver
`CLAUDE.md` e o padrão de "migration pendente" nas demais specs do projeto). Revise o arquivo lendo-o de volta
inteiro, conferindo:
- Todo `CREATE OR REPLACE FUNCTION` tem `$$ ... $$` balanceado.
- Todo `DROP FUNCTION IF EXISTS` bate exatamente com a assinatura antiga (tipos e ordem dos parâmetros) antes do
  `CREATE OR REPLACE` daquela função — assinatura errada faz o `DROP` silenciosamente não achar a função antiga e
  o `CREATE OR REPLACE` falhar por conflito de retorno.
- Todo `GRANT EXECUTE` referencia a assinatura nova (com todos os parâmetros na ordem certa).

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260818_universal_search.sql
git commit -m "feat(busca): RPCs de busca universal (leads, deals, sales) + extensão de mensagens

search_leads/search_deals/search_sales seguem o padrão unaccent+trigram
de 20260812_search_all_messages.sql. search_customer_messages ganha
docs_only, paginação (p_offset) e lead_id (p/ deep-link /conversas).

Migration PENDENTE de aplicação manual no Supabase (mesmo fluxo das
demais migrations do projeto).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

**IMPORTANTE:** esta migration precisa ser aplicada manualmente no Supabase (SQL Editor ou `supabase db push`,
conforme o fluxo já usado nas outras migrations do projeto) antes das Tasks 5-8 funcionarem de ponta a ponta. Sem
ela, `/api/search` responde 500 (RPC inexistente) — isso é esperado até a aplicação manual.

---

### Task 3: `GET` em `/api/deals/[id]` e `/api/sales/[id]` (pré-requisito de deep-link)

**Files:**
- Modify: `frontend/src/app/api/deals/[id]/route.ts`
- Modify: `frontend/src/app/api/sales/[id]/route.ts`

- [ ] **Step 1: Adicionar `GET` em `deals/[id]/route.ts`**

Leia o arquivo primeiro para confirmar os imports atuais, depois adicione, logo após os imports e antes de
`export async function PATCH(`:

```ts
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("deals")
    .select("*, leads(id, name, company, phone, nome_fantasia, notes), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
    .eq("id", id)
    .maybeSingle();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  if (!data) return NextResponse.json({ error: "Deal não encontrado." }, { status: 404 });
  return NextResponse.json(data);
}
```

- [ ] **Step 2: Adicionar `GET` em `sales/[id]/route.ts`**

Mesma coisa, logo após os imports e antes de `export async function PATCH(`:

```ts
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sales")
    .select("*, leads(id, name, phone, company), deals(id, title)")
    .eq("id", id)
    .maybeSingle();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  if (!data) return NextResponse.json({ error: "Venda não encontrada." }, { status: 404 });
  return NextResponse.json(data);
}
```

- [ ] **Step 3: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo.

Com o backend rodando, pegue um `id` real de deal e de venda (via UI ou Supabase) e confira:
`curl http://127.0.0.1:3000/api/deals/<id>` e `curl http://127.0.0.1:3000/api/sales/<id>` devolvem JSON 200; um id
inexistente (`curl http://127.0.0.1:3000/api/deals/00000000-0000-0000-0000-000000000000`) devolve 404.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/api/deals/[id]/route.ts frontend/src/app/api/sales/[id]/route.ts
git commit -m "feat(api): GET em /api/deals/[id] e /api/sales/[id]

Pré-requisito p/ deep-link da /busca: o item buscado pode estar fora
do funil/período atualmente carregado na página de destino, então a
página precisa poder buscar por id diretamente.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: `lib/universal-search.ts` (lógica pura, testada) + tipos em `lib/types.ts`

**Files:**
- Create: `frontend/src/lib/universal-search.ts`
- Test: `frontend/src/lib/universal-search.test.ts`
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Escrever o teste que falha**

Crie `frontend/src/lib/universal-search.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { parseSearchParams, limitForTab, offsetFor, startOfDayIso, endOfDayIso } from "./universal-search";

describe("parseSearchParams", () => {
  it("defaults to tab=all and page=1 when absent", () => {
    const parsed = parseSearchParams(new URLSearchParams("q=jose"));
    expect(parsed).toEqual({
      q: "jose", tab: "all", dateFrom: null, dateTo: null,
      pipelineId: null, stageId: null, leadStage: null, docsOnly: false, page: 1,
    });
  });

  it("trims q and falls back to 'all' for an invalid tab", () => {
    const parsed = parseSearchParams(new URLSearchParams("q= jose &tab=bogus"));
    expect(parsed.q).toBe("jose");
    expect(parsed.tab).toBe("all");
  });

  it("parses every optional filter", () => {
    const parsed = parseSearchParams(
      new URLSearchParams(
        "q=x&tab=deals&date_from=2026-01-01&date_to=2026-01-31&pipeline_id=p1&stage_id=s1&lead_stage=atacado&docs_only=true&page=3"
      )
    );
    expect(parsed).toEqual({
      q: "x", tab: "deals", dateFrom: "2026-01-01", dateTo: "2026-01-31",
      pipelineId: "p1", stageId: "s1", leadStage: "atacado", docsOnly: true, page: 3,
    });
  });

  it("clamps page to at least 1", () => {
    expect(parseSearchParams(new URLSearchParams("q=x&page=0")).page).toBe(1);
    expect(parseSearchParams(new URLSearchParams("q=x&page=-5")).page).toBe(1);
    expect(parseSearchParams(new URLSearchParams("q=x&page=abc")).page).toBe(1);
  });
});

describe("limitForTab", () => {
  it("returns 5 for the 'all' preview tab", () => {
    expect(limitForTab("all")).toBe(5);
  });
  it("returns 20 for a specific tab", () => {
    expect(limitForTab("leads")).toBe(20);
    expect(limitForTab("deals")).toBe(20);
    expect(limitForTab("sales")).toBe(20);
    expect(limitForTab("conversations")).toBe(20);
  });
});

describe("offsetFor", () => {
  it("computes 0-indexed Postgres OFFSET from a 1-indexed page", () => {
    expect(offsetFor(1, 20)).toBe(0);
    expect(offsetFor(2, 20)).toBe(20);
    expect(offsetFor(3, 5)).toBe(10);
  });
  it("never returns negative", () => {
    expect(offsetFor(0, 20)).toBe(0);
  });
});

describe("startOfDayIso / endOfDayIso", () => {
  it("expands a yyyy-mm-dd date to UTC start/end of day", () => {
    expect(startOfDayIso("2026-08-18")).toBe("2026-08-18T00:00:00.000Z");
    expect(endOfDayIso("2026-08-18")).toBe("2026-08-18T23:59:59.999Z");
  });
  it("passes through an already-full ISO timestamp unchanged", () => {
    expect(startOfDayIso("2026-08-18T10:00:00.000Z")).toBe("2026-08-18T10:00:00.000Z");
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/universal-search.test.ts`
Expected: FAIL (`Cannot find module './universal-search'`).

- [ ] **Step 3: Implementar `lib/universal-search.ts`**

```ts
export type SearchTab = "all" | "leads" | "deals" | "sales" | "conversations";

const VALID_TABS: SearchTab[] = ["all", "leads", "deals", "sales", "conversations"];

export interface ParsedSearchParams {
  q: string;
  tab: SearchTab;
  dateFrom: string | null;
  dateTo: string | null;
  pipelineId: string | null;
  stageId: string | null;
  leadStage: string | null;
  docsOnly: boolean;
  page: number;
}

/** Parses and validates the /api/search query string. Unknown/invalid `tab` falls back to "all". */
export function parseSearchParams(searchParams: URLSearchParams): ParsedSearchParams {
  const rawTab = searchParams.get("tab") ?? "all";
  const tab = (VALID_TABS as string[]).includes(rawTab) ? (rawTab as SearchTab) : "all";
  const page = Math.max(1, parseInt(searchParams.get("page") ?? "1", 10) || 1);
  return {
    q: (searchParams.get("q") || "").trim(),
    tab,
    dateFrom: searchParams.get("date_from") || null,
    dateTo: searchParams.get("date_to") || null,
    pipelineId: searchParams.get("pipeline_id") || null,
    stageId: searchParams.get("stage_id") || null,
    leadStage: searchParams.get("lead_stage") || null,
    docsOnly: searchParams.get("docs_only") === "true",
    page,
  };
}

/** Page size por aba: preview pequeno (5) na aba "Tudo", página cheia (20) numa aba específica. */
export function limitForTab(tab: SearchTab): number {
  return tab === "all" ? 5 : 20;
}

/** OFFSET (0-indexed) do Postgres a partir de uma página 1-indexed. */
export function offsetFor(page: number, limit: number): number {
  return Math.max(0, (page - 1) * limit);
}

/** Data yyyy-mm-dd -> timestamp UTC de início do dia (p/ filtro `>=`). Timestamps completos passam direto. */
export function startOfDayIso(date: string): string {
  return date.length === 10 ? `${date}T00:00:00.000Z` : date;
}

/** Data yyyy-mm-dd -> timestamp UTC de fim do dia (p/ filtro `<=`). Timestamps completos passam direto. */
export function endOfDayIso(date: string): string {
  return date.length === 10 ? `${date}T23:59:59.999Z` : date;
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/universal-search.test.ts`
Expected: PASS.

- [ ] **Step 5: Adicionar os tipos de resultado em `lib/types.ts`**

Adicione ao final de `frontend/src/lib/types.ts`:

```ts
export interface LeadSearchResult {
  id: string;
  name: string | null;
  company: string | null;
  phone: string;
  status: string;
  stage: string;
  nome_fantasia: string | null;
  cnpj: string | null;
  created_at: string;
  total_count: number;
}

export interface DealSearchResult {
  id: string;
  title: string;
  value: number;
  pipeline_id: string | null;
  pipeline_name: string | null;
  stage_id: string | null;
  stage_label: string | null;
  lead_id: string;
  lead_name: string | null;
  lead_phone: string;
  created_at: string;
  total_count: number;
}

export interface SaleSearchResult {
  id: string;
  product: string;
  value: number;
  sold_at: string;
  notes: string | null;
  lead_id: string;
  lead_name: string | null;
  lead_phone: string;
  deal_id: string | null;
  deal_title: string | null;
  total_count: number;
}

export interface ConversationSearchResult {
  conversation_id: string;
  message_id: string;
  snippet: string;
  match_created_at: string;
  match_count: number;
  lead_id: string | null;
  lead_name: string | null;
  lead_phone: string | null;
  channel_id: string | null;
  channel_name: string | null;
  sent_by: string;
  total_count: number;
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/universal-search.ts frontend/src/lib/universal-search.test.ts frontend/src/lib/types.ts
git commit -m "feat(busca): lib/universal-search.ts (parsing/paginação puros) + tipos de resultado

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `GET /api/search`

**Files:**
- Create: `frontend/src/app/api/search/route.ts`
- Modify: `frontend/src/proxy.ts` (adicionar `"/api/search/:path*"` ao `config.matcher`)

**Depende de:** Task 2 (RPCs precisam existir no banco) e Task 4 (`lib/universal-search.ts`).

**Obrigatório:** adicione `"/api/search/:path*"` ao array `matcher` em `frontend/src/proxy.ts` (junto dos demais
`"/api/..."`). Sem isso, `proxy-coverage.test.ts` falha e a rota fica fora do gating de auth do proxy.

- [ ] **Step 1: Implementar a rota**

Crie `frontend/src/app/api/search/route.ts`:

```ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { getAllowedPipelineIds, PipelineAccessError } from "@/lib/supabase/pipeline-access";
import { parseSearchParams, limitForTab, offsetFor, startOfDayIso, endOfDayIso } from "@/lib/universal-search";

const MIN_QUERY_LEN = 2;
const EMPTY_RESULT = { data: [] as unknown[], count: 0 };
const EMPTY_RESPONSE = {
  leads: EMPTY_RESULT, deals: EMPTY_RESULT, sales: EMPTY_RESULT, conversations: EMPTY_RESULT,
};

interface RpcResult {
  data: Array<Record<string, unknown>> | null;
  error: { message: string } | null;
}

function shape(res: RpcResult) {
  const rows = res.data ?? [];
  const count = rows.length > 0 ? Number(rows[0].total_count ?? rows.length) : 0;
  return { data: rows, count };
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const params = parseSearchParams(searchParams);

  if (params.q.length < MIN_QUERY_LEN) {
    return NextResponse.json(EMPTY_RESPONSE);
  }

  const supabase = await getServiceSupabase();

  let allowedPipelineIds: string[] | null;
  try {
    allowedPipelineIds = await getAllowedPipelineIds(supabase);
  } catch (err) {
    if (err instanceof PipelineAccessError) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    throw err;
  }

  let allowedChannelIds: string[] | null;
  try {
    allowedChannelIds = await getAllowedChannelIds(supabase);
  } catch (err) {
    if (err instanceof ChannelAccessError) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    throw err;
  }

  const limit = limitForTab(params.tab);
  const offset = offsetFor(params.page, limit);
  const wantsAll = params.tab === "all";
  const dateAfter = params.dateFrom ? startOfDayIso(params.dateFrom) : null;
  const dateBefore = params.dateTo ? endOfDayIso(params.dateTo) : null;

  const noop: RpcResult = { data: [], error: null };

  const [leadsRes, dealsRes, salesRes, conversationsRes]: RpcResult[] = await Promise.all([
    wantsAll || params.tab === "leads"
      ? supabase.rpc("search_leads", {
          search_query: params.q,
          p_stage: params.leadStage,
          p_created_after: dateAfter,
          p_created_before: dateBefore,
          max_results: limit,
          p_offset: offset,
        })
      : Promise.resolve(noop),
    wantsAll || params.tab === "deals"
      ? supabase.rpc("search_deals", {
          search_query: params.q,
          pipeline_ids: allowedPipelineIds,
          p_pipeline_id: params.pipelineId,
          p_stage_id: params.stageId,
          p_created_after: dateAfter,
          p_created_before: dateBefore,
          max_results: limit,
          p_offset: offset,
        })
      : Promise.resolve(noop),
    wantsAll || params.tab === "sales"
      ? supabase.rpc("search_sales", {
          search_query: params.q,
          p_sold_after: dateAfter,
          p_sold_before: dateBefore,
          max_results: limit,
          p_offset: offset,
        })
      : Promise.resolve(noop),
    wantsAll || params.tab === "conversations"
      ? supabase.rpc("search_customer_messages", {
          search_query: params.q,
          channel_ids: allowedChannelIds,
          max_results: limit,
          docs_only: params.docsOnly,
          p_offset: offset,
        })
      : Promise.resolve(noop),
  ]);

  for (const res of [leadsRes, dealsRes, salesRes, conversationsRes]) {
    if (res.error) return NextResponse.json({ error: res.error.message }, { status: 500 });
  }

  return NextResponse.json({
    leads: shape(leadsRes),
    deals: shape(dealsRes),
    sales: shape(salesRes),
    conversations: shape(conversationsRes),
  });
}
```

- [ ] **Step 2: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo.

Pré-requisito: migration da Task 2 já aplicada no Supabase (senão o passo abaixo devolve 500 com "function
search_leads(...) does not exist" — nesse caso, aplique a migration primeiro e repita).

Com o backend rodando e logado (cookie de sessão válido no browser), abra
`http://127.0.0.1:3000/api/search?q=jose&tab=all` — deve devolver `{leads:{...}, deals:{...}, sales:{...},
conversations:{...}}`. Teste também `?q=a` (1 caractere) — deve devolver a resposta vazia sem erro.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/search/route.ts
git commit -m "feat(busca): rota GET /api/search com fan-out server-side nas 4 entidades

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Hook `useUniversalSearch`

**Files:**
- Create: `frontend/src/hooks/use-universal-search.ts`

- [ ] **Step 1: Implementar o hook**

```ts
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { debounce } from "@/lib/debounce";
import type { SearchTab } from "@/lib/universal-search";
import type {
  LeadSearchResult, DealSearchResult, SaleSearchResult, ConversationSearchResult,
} from "@/lib/types";

export interface UniversalSearchFilters {
  dateFrom: string;
  dateTo: string;
  pipelineId: string;
  stageId: string;
  leadStage: string;
  docsOnly: boolean;
}

export const EMPTY_FILTERS: UniversalSearchFilters = {
  dateFrom: "", dateTo: "", pipelineId: "", stageId: "", leadStage: "", docsOnly: false,
};

interface EntityResult<T> { data: T[]; count: number; }

export interface UniversalSearchResults {
  leads: EntityResult<LeadSearchResult>;
  deals: EntityResult<DealSearchResult>;
  sales: EntityResult<SaleSearchResult>;
  conversations: EntityResult<ConversationSearchResult>;
}

const EMPTY_RESULTS: UniversalSearchResults = {
  leads: { data: [], count: 0 },
  deals: { data: [], count: 0 },
  sales: { data: [], count: 0 },
  conversations: { data: [], count: 0 },
};

/** Busca ao vivo com debounce (400ms) na /busca. Mínimo 2 caracteres. Ignora respostas fora de ordem. */
export function useUniversalSearch(
  query: string,
  tab: SearchTab,
  filters: UniversalSearchFilters,
  page: number,
) {
  const [results, setResults] = useState<UniversalSearchResults>(EMPTY_RESULTS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

  const runSearch = useMemo(
    () =>
      debounce(
        async (q: string, t: SearchTab, f: UniversalSearchFilters, p: number) => {
          const generation = ++generationRef.current;
          if (q.trim().length < 2) {
            setResults(EMPTY_RESULTS);
            setLoading(false);
            setError(null);
            return;
          }
          setLoading(true);
          const params = new URLSearchParams({ q, tab: t, page: String(p) });
          if (f.dateFrom) params.set("date_from", f.dateFrom);
          if (f.dateTo) params.set("date_to", f.dateTo);
          if (f.pipelineId) params.set("pipeline_id", f.pipelineId);
          if (f.stageId) params.set("stage_id", f.stageId);
          if (f.leadStage) params.set("lead_stage", f.leadStage);
          if (f.docsOnly) params.set("docs_only", "true");
          try {
            const res = await fetch(`/api/search?${params}`);
            if (generation !== generationRef.current) return;
            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              setError(body.error || "Erro ao buscar.");
              setLoading(false);
              return;
            }
            const data = (await res.json()) as UniversalSearchResults;
            setResults(data);
            setError(null);
          } catch {
            if (generation !== generationRef.current) return;
            setError("Erro ao buscar.");
          } finally {
            if (generation === generationRef.current) setLoading(false);
          }
        },
        400,
      ),
    [],
  );

  useEffect(() => {
    runSearch(query, tab, filters, page);
    return () => runSearch.cancel();
  }, [query, tab, filters, page, runSearch]);

  return { results, loading, error };
}
```

- [ ] **Step 2: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo. (Este hook não tem teste automatizado — o repo não testa hooks React em vitest, só
`lib/*.ts` puro; será validado via a página `/busca` na Task 8.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/use-universal-search.ts
git commit -m "feat(busca): hook useUniversalSearch (debounce 400ms, min 2 chars, anti-race)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Componentes de busca (abas, filtros, resultados)

**Files:**
- Create: `frontend/src/components/search/search-tabs.tsx`
- Create: `frontend/src/components/search/search-filters-bar.tsx`
- Create: `frontend/src/components/search/search-results.tsx`

**Depende de:** Task 4 (tipos), Task 6 (tipos de filtro).

- [ ] **Step 1: `search-tabs.tsx`**

```tsx
"use client";

import type { SearchTab } from "@/lib/universal-search";
import type { UniversalSearchResults } from "@/hooks/use-universal-search";

const TAB_LABELS: Record<SearchTab, string> = {
  all: "Tudo",
  leads: "Leads",
  deals: "Deals",
  sales: "Vendas",
  conversations: "Conversas",
};

function countFor(tab: SearchTab, results: UniversalSearchResults): number | null {
  switch (tab) {
    case "leads": return results.leads.count;
    case "deals": return results.deals.count;
    case "sales": return results.sales.count;
    case "conversations": return results.conversations.count;
    default: return null;
  }
}

export function SearchTabs({
  active, onChange, results,
}: {
  active: SearchTab;
  onChange: (tab: SearchTab) => void;
  results: UniversalSearchResults;
}) {
  const tabs: SearchTab[] = ["all", "leads", "deals", "sales", "conversations"];
  return (
    <div className="flex items-center gap-1 border-b border-[#dedbd6]">
      {tabs.map((tab) => {
        const count = countFor(tab, results);
        const isActive = tab === active;
        return (
          <button
            key={tab}
            type="button"
            onClick={() => onChange(tab)}
            className={`px-3.5 py-2.5 text-[13px] font-medium border-b-2 -mb-px transition-colors ${
              isActive
                ? "border-[#111111] text-[#111111]"
                : "border-transparent text-[#7b7b78] hover:text-[#111111]"
            }`}
          >
            {TAB_LABELS[tab]}
            {count !== null && count > 0 && (
              <span className="ml-1.5 text-[11px] text-[#7b7b78]">{count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: `search-filters-bar.tsx`**

```tsx
"use client";

import { AGENT_STAGES } from "@/lib/constants";
import { usePipelines, usePipelineStages } from "@/hooks/use-pipelines";
import type { SearchTab } from "@/lib/universal-search";
import type { UniversalSearchFilters } from "@/hooks/use-universal-search";

const selectClass =
  "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none cursor-pointer";
const dateClass =
  "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none";

export function SearchFiltersBar({
  tab, filters, onChange,
}: {
  tab: SearchTab;
  filters: UniversalSearchFilters;
  onChange: (filters: UniversalSearchFilters) => void;
}) {
  const { pipelines } = usePipelines();
  const { stages } = usePipelineStages(filters.pipelineId || null);

  const showPeriod = true; // toda aba filtra por período
  const showLeadStage = tab === "leads";
  const showPipelineStage = tab === "deals";
  const showDocsOnly = tab === "conversations";

  function update(patch: Partial<UniversalSearchFilters>) {
    onChange({ ...filters, ...patch });
  }

  return (
    <div className="flex flex-wrap items-center gap-2 py-3">
      {showPeriod && (
        <>
          <input
            type="date"
            value={filters.dateFrom}
            onChange={(e) => update({ dateFrom: e.target.value })}
            className={dateClass}
            aria-label="Data inicial"
          />
          <span className="text-[13px] text-[#7b7b78]">até</span>
          <input
            type="date"
            value={filters.dateTo}
            onChange={(e) => update({ dateTo: e.target.value })}
            className={dateClass}
            aria-label="Data final"
          />
        </>
      )}

      {showLeadStage && (
        <select
          value={filters.leadStage}
          onChange={(e) => update({ leadStage: e.target.value })}
          className={selectClass}
        >
          <option value="">Todos os segmentos</option>
          {AGENT_STAGES.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>
      )}

      {showPipelineStage && (
        <>
          <select
            value={filters.pipelineId}
            onChange={(e) => update({ pipelineId: e.target.value, stageId: "" })}
            className={selectClass}
          >
            <option value="">Todos os funis</option>
            {pipelines.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <select
            value={filters.stageId}
            onChange={(e) => update({ stageId: e.target.value })}
            disabled={!filters.pipelineId}
            className={`${selectClass} disabled:opacity-40 disabled:cursor-not-allowed`}
          >
            <option value="">Todas as etapas</option>
            {stages.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </>
      )}

      {showDocsOnly && (
        <label className="flex items-center gap-1.5 text-[13px] text-[#313130] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={filters.docsOnly}
            onChange={(e) => update({ docsOnly: e.target.checked })}
            className="cursor-pointer"
          />
          Só documentos/mídia
        </label>
      )}
    </div>
  );
}
```

- [ ] **Step 3: `search-results.tsx`**

```tsx
"use client";

import { useRouter } from "next/navigation";
import type { SearchTab } from "@/lib/universal-search";
import type { UniversalSearchResults } from "@/hooks/use-universal-search";
import type {
  LeadSearchResult, DealSearchResult, SaleSearchResult, ConversationSearchResult,
} from "@/lib/types";

const rowClass =
  "flex items-center justify-between gap-3 px-3 py-2.5 rounded-[6px] hover:bg-[#f4f3ef] cursor-pointer transition-colors";
const primaryText = "text-[14px] text-[#111111] font-medium truncate";
const secondaryText = "text-[12px] text-[#7b7b78] truncate";
const sectionTitle = "text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78] px-3 pt-4 pb-1.5";

function currency(value: number): string {
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function LeadRow({ lead, onOpen }: { lead: LeadSearchResult; onOpen: () => void }) {
  return (
    <div className={rowClass} onClick={onOpen}>
      <div className="min-w-0">
        <p className={primaryText}>{lead.name || lead.phone}</p>
        <p className={secondaryText}>{lead.company || lead.nome_fantasia || lead.phone}</p>
      </div>
      <span className={secondaryText}>{lead.phone}</span>
    </div>
  );
}

function DealRow({ deal, onOpen }: { deal: DealSearchResult; onOpen: () => void }) {
  return (
    <div className={rowClass} onClick={onOpen}>
      <div className="min-w-0">
        <p className={primaryText}>{deal.title}</p>
        <p className={secondaryText}>{deal.lead_name || deal.lead_phone} · {deal.pipeline_name} / {deal.stage_label}</p>
      </div>
      <span className={secondaryText}>{currency(deal.value)}</span>
    </div>
  );
}

function SaleRow({ sale, onOpen }: { sale: SaleSearchResult; onOpen: () => void }) {
  return (
    <div className={rowClass} onClick={onOpen}>
      <div className="min-w-0">
        <p className={primaryText}>{sale.product}</p>
        <p className={secondaryText}>{sale.lead_name || sale.lead_phone} · {new Date(sale.sold_at).toLocaleDateString("pt-BR")}</p>
      </div>
      <span className={secondaryText}>{currency(sale.value)}</span>
    </div>
  );
}

function ConversationRow({ item, onOpen }: { item: ConversationSearchResult; onOpen: () => void }) {
  const prefix = item.sent_by ? "Você: " : "";
  return (
    <div className={rowClass} onClick={onOpen}>
      <div className="min-w-0">
        <p className={primaryText}>{item.lead_name || item.lead_phone || "Contato"}</p>
        <p className={secondaryText}>{prefix}{item.snippet}</p>
      </div>
      <span className={secondaryText}>{item.channel_name}</span>
    </div>
  );
}

export function SearchResults({
  tab, results, onTabChange,
}: {
  tab: SearchTab;
  results: UniversalSearchResults;
  onTabChange: (tab: SearchTab) => void;
}) {
  const router = useRouter();
  const showAll = tab === "all";
  const isEmpty =
    results.leads.count === 0 && results.deals.count === 0 &&
    results.sales.count === 0 && results.conversations.count === 0;

  if (isEmpty) {
    return <p className="text-[13px] text-[#7b7b78] px-3 py-8 text-center">Nada encontrado.</p>;
  }

  return (
    <div className="divide-y divide-[#f0ede8]">
      {(showAll || tab === "leads") && results.leads.data.length > 0 && (
        <section>
          <div className="flex items-center justify-between px-3">
            <p className={sectionTitle}>Leads</p>
            {showAll && results.leads.count > results.leads.data.length && (
              <button type="button" onClick={() => onTabChange("leads")} className="text-[12px] text-[#7b7b78] hover:text-[#111111] pt-3">
                ver todos ({results.leads.count}) &gt;
              </button>
            )}
          </div>
          {results.leads.data.map((lead) => (
            <LeadRow key={lead.id} lead={lead} onOpen={() => router.push(`/leads?lead_id=${lead.id}`)} />
          ))}
        </section>
      )}

      {(showAll || tab === "deals") && results.deals.data.length > 0 && (
        <section>
          <div className="flex items-center justify-between px-3">
            <p className={sectionTitle}>Deals</p>
            {showAll && results.deals.count > results.deals.data.length && (
              <button type="button" onClick={() => onTabChange("deals")} className="text-[12px] text-[#7b7b78] hover:text-[#111111] pt-3">
                ver todos ({results.deals.count}) &gt;
              </button>
            )}
          </div>
          {results.deals.data.map((deal) => (
            <DealRow key={deal.id} deal={deal} onOpen={() => router.push(`/vendas?deal_id=${deal.id}`)} />
          ))}
        </section>
      )}

      {(showAll || tab === "sales") && results.sales.data.length > 0 && (
        <section>
          <div className="flex items-center justify-between px-3">
            <p className={sectionTitle}>Vendas</p>
            {showAll && results.sales.count > results.sales.data.length && (
              <button type="button" onClick={() => onTabChange("sales")} className="text-[12px] text-[#7b7b78] hover:text-[#111111] pt-3">
                ver todos ({results.sales.count}) &gt;
              </button>
            )}
          </div>
          {results.sales.data.map((sale) => (
            <SaleRow key={sale.id} sale={sale} onOpen={() => router.push(`/painel-vendas?sale_id=${sale.id}`)} />
          ))}
        </section>
      )}

      {(showAll || tab === "conversations") && results.conversations.data.length > 0 && (
        <section>
          <div className="flex items-center justify-between px-3">
            <p className={sectionTitle}>Conversas</p>
            {showAll && results.conversations.count > results.conversations.data.length && (
              <button type="button" onClick={() => onTabChange("conversations")} className="text-[12px] text-[#7b7b78] hover:text-[#111111] pt-3">
                ver todos ({results.conversations.count}) &gt;
              </button>
            )}
          </div>
          {results.conversations.data.map((item) => (
            <ConversationRow
              key={item.message_id}
              item={item}
              onOpen={() => router.push(item.lead_id ? `/conversas?lead_id=${item.lead_id}` : "/conversas")}
            />
          ))}
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo. (Componentes sem teste automatizado — repo não testa `.tsx`; validados na Task 8.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/search/
git commit -m "feat(busca): componentes de abas, filtros e resultados

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Página `/busca`

**Files:**
- Create: `frontend/src/app/(authenticated)/busca/page.tsx`

**Depende de:** Tasks 5, 6, 7.

- [ ] **Step 1: Implementar a página**

```tsx
"use client";

import { useState } from "react";
import { useUniversalSearch, EMPTY_FILTERS } from "@/hooks/use-universal-search";
import { SearchTabs } from "@/components/search/search-tabs";
import { SearchFiltersBar } from "@/components/search/search-filters-bar";
import { SearchResults } from "@/components/search/search-results";
import type { SearchTab } from "@/lib/universal-search";

export default function BuscaPage() {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<SearchTab>("all");
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);

  const { results, loading, error } = useUniversalSearch(query, tab, filters, page);

  function handleTabChange(next: SearchTab) {
    setTab(next);
    setPage(1);
  }

  const showEmptyPrompt = query.trim().length < 2;

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-3 md:py-5 flex-shrink-0">
        <h1 className="text-[18px] font-semibold text-[#111111] tracking-tight mb-3">Busca</h1>
        <input
          type="text"
          autoFocus
          value={query}
          onChange={(e) => { setQuery(e.target.value); setPage(1); }}
          placeholder="Buscar leads, deals, vendas, conversas..."
          className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3.5 py-2.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
        />
      </div>

      <div className="px-4 md:px-8 flex-shrink-0 bg-white">
        <SearchTabs active={tab} onChange={handleTabChange} results={results} />
        <SearchFiltersBar tab={tab} filters={filters} onChange={setFilters} />
      </div>

      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-2">
        {showEmptyPrompt && (
          <p className="text-[13px] text-[#7b7b78] px-3 py-8 text-center">
            Digite ao menos 2 caracteres para buscar.
          </p>
        )}
        {!showEmptyPrompt && loading && (
          <div className="flex items-center gap-3 px-3 py-8">
            <div className="w-4 h-4 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin" />
            <span className="text-[13px] text-[#7b7b78]">Buscando...</span>
          </div>
        )}
        {!showEmptyPrompt && !loading && error && (
          <p className="text-[13px] text-[#c41c1c] px-3 py-8 text-center">{error}</p>
        )}
        {!showEmptyPrompt && !loading && !error && (
          <SearchResults tab={tab} results={results} onTabChange={handleTabChange} />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo.

Com o app rodando (`npm run dev` em `frontend/`) e a migration da Task 2 já aplicada no Supabase, abra
`http://127.0.0.1:3000/busca` diretamente pela URL (a página ainda não está no menu — isso é a Task 9), digite um
nome de lead conhecido e confira: aparecem resultados nas seções corretas, a aba "Deals" mostra o filtro de
funil/etapa, a aba "Conversas" mostra "Só documentos/mídia", clicar num resultado navega para a página certa.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/(authenticated)/busca/page.tsx"
git commit -m "feat(busca): página /busca (abas, filtros, busca ao vivo)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Sidebar + roles

**Files:**
- Modify: `frontend/src/components/sidebar.tsx`
- Modify: `frontend/src/lib/auth/roles.ts`
- Modify: `frontend/src/proxy.ts` (adicionar `"/busca/:path*"` ao `config.matcher`)

**Obrigatório:** adicione `"/busca/:path*"` ao array `matcher` em `frontend/src/proxy.ts` (junto das demais páginas,
logo após `"/painel-vendas/:path*"`). Sem isso, `proxy-coverage.test.ts` falha e a página fica fora do gating de auth.

- [ ] **Step 1: Adicionar o item no sidebar**

Em `frontend/src/components/sidebar.tsx`, dentro de `NAV_GROUPS`, no grupo `"Vendas"`, logo depois do item
`/painel-vendas` (fim do array `items` desse grupo):

```tsx
      {
        href: "/painel-vendas",
        label: "Painel de Vendas",
        icon: <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" /></svg>,
      },
```

vira:

```tsx
      {
        href: "/painel-vendas",
        label: "Painel de Vendas",
        icon: <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" /></svg>,
      },
      {
        href: "/busca",
        label: "Busca",
        icon: <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0015.607 10.607z" /></svg>,
      },
```

- [ ] **Step 2: Adicionar `/busca` em `ROLE_PAGES`**

Em `frontend/src/lib/auth/roles.ts`, adicione `"/busca"` na lista de `admin` (logo após `"/painel-vendas"`) e na
lista de `vendedor` (logo após `"/painel-vendas"`):

```ts
export const ROLE_PAGES: Record<UserRole, string[]> = {
  admin: [
    "/dashboard",
    "/leads",
    "/conversas",
    "/campanhas",
    "/qualificacao",
    "/vendas",
    "/painel-vendas",
    "/busca",
    "/canais",
    "/estatisticas",
    "/trafego",
    "/config",
  ],
  vendedor: [
    "/dashboard",
    "/leads",
    "/conversas",
    "/campanhas",
    "/qualificacao",
    "/vendas",
    "/painel-vendas",
    "/busca",
  ],
};
```

- [ ] **Step 3: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo.

Se existir um teste de cobertura de rotas por role (`frontend/src/lib/auth/proxy-coverage.test.ts`), rode:
`cd frontend && npx vitest run src/lib/auth/proxy-coverage.test.ts` — se ele enumera rotas de `frontend/src/app`
automaticamente, deve passar sem mudança; se ele mantém uma lista própria de rotas esperadas, adicione `/busca`
nela para não quebrar.

Com o app rodando, confirme visualmente que "Busca" aparece no menu lateral logo abaixo de "Painel de Vendas", e
que o clique navega pra `/busca`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/sidebar.tsx frontend/src/lib/auth/roles.ts
git commit -m "feat(busca): adiciona /busca ao menu lateral (grupo Vendas) e às rotas permitidas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Deep-link em `/leads`

**Files:**
- Modify: `frontend/src/app/(authenticated)/leads/page.tsx`

- [ ] **Step 1: Renomear o componente e envolver em `Suspense`**

Leia o arquivo inteiro primeiro. Troque a linha de import do React (topo do arquivo):

```ts
import { useState, useMemo, useEffect } from "react";
```

por:

```ts
import { useState, useMemo, useEffect, useRef, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
```

Troque `export default function LeadsPage() {` por `function LeadsPageInner() {`.

No final do arquivo, depois do fechamento da função (a última `}` que fecha `LeadsPageInner`), adicione:

```tsx
export default function LeadsPage() {
  return (
    <Suspense>
      <LeadsPageInner />
    </Suspense>
  );
}
```

- [ ] **Step 2: Adicionar o deep-link**

Dentro de `LeadsPageInner`, logo após a declaração de `const [mobileSelectedLead, setMobileSelectedLead] = useState<Lead | null>(null);`,
adicione:

```ts
  const searchParams = useSearchParams();
  const router = useRouter();
  const deepLinkApplied = useRef(false);

  // Deep-link: pré-seleciona o lead vindo de /busca?lead_id=. `leads` já carrega
  // a tabela inteira (useRealtimeLeads pagina até o fim), então o lead buscado
  // já está na lista assim que ela terminar de carregar.
  useEffect(() => {
    if (deepLinkApplied.current || loading) return;
    const leadId = searchParams.get("lead_id");
    if (!leadId) return;
    const match = leads.find((l) => l.id === leadId);
    if (match) {
      setSelectedLead(match);
      deepLinkApplied.current = true;
      router.replace("/leads");
    }
  }, [leads, loading, searchParams, router]);
```

- [ ] **Step 3: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo.

Com o app rodando, abra `/leads?lead_id=<id de um lead real>` diretamente na URL — o modal do lead deve abrir
sozinho e a URL deve voltar para `/leads` limpa.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/(authenticated)/leads/page.tsx"
git commit -m "feat(leads): deep-link /leads?lead_id= (mesmo padrão de /conversas)

Necessário p/ a /busca poder abrir um lead na página existente.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: Deep-link em `/vendas`

**Files:**
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx`

**Depende de:** Task 3 (`GET /api/deals/[id]`).

- [ ] **Step 1: Envolver em `Suspense` e importar navigation**

Troque a linha de import do React (topo do arquivo):

```ts
import { useState, useEffect, useRef } from "react";
```

por:

```ts
import { useState, useEffect, useRef, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
```

Troque `export default function VendasPage() {` por `function VendasPageInner() {`.

No final do arquivo, depois do fechamento da função `VendasPageInner`, adicione:

```tsx
export default function VendasPage() {
  return (
    <Suspense>
      <VendasPageInner />
    </Suspense>
  );
}
```

- [ ] **Step 2: Adicionar o deep-link**

Dentro de `VendasPageInner`, logo após `const [bulkMoveStage, setBulkMoveStage] = useState<PipelineStage | null>(null);`,
adicione:

```ts
  const searchParams = useSearchParams();
  const router = useRouter();
  const deepLinkDealId = useRef<string | null>(null);
  const deepLinkApplied = useRef(false);

  // Deep-link: /busca?deal_id= pode apontar pra um deal fora do pipeline aberto.
  // 1º efeito: descobre o pipeline do deal e troca o pipeline selecionado.
  useEffect(() => {
    const dealId = searchParams.get("deal_id");
    if (!dealId || deepLinkApplied.current) return;
    deepLinkDealId.current = dealId;
    fetch(`/api/deals/${dealId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((deal) => {
        if (deal?.pipeline_id) setSelectedPipelineId(deal.pipeline_id);
      });
  }, [searchParams]);

  // 2º efeito: quando o pipeline certo estiver selecionado e `deals` (já
  // filtrado por ele) tiver carregado, abre o deal e limpa a URL.
  useEffect(() => {
    if (deepLinkApplied.current || !deepLinkDealId.current || dealsLoading) return;
    const match = deals.find((d) => d.id === deepLinkDealId.current);
    if (match) {
      setSelectedDealId(match.id);
      deepLinkApplied.current = true;
      router.replace("/vendas");
    }
  }, [deals, dealsLoading, router]);
```

- [ ] **Step 3: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo.

Com o app rodando, abra `/vendas?deal_id=<id de um deal que esteja num funil diferente do que abre por padrão>` —
confirme que o funil troca sozinho, o painel do deal abre, e a URL volta pra `/vendas` limpa.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/(authenticated)/vendas/page.tsx"
git commit -m "feat(vendas): deep-link /vendas?deal_id= (troca de funil automática)

Necessário p/ a /busca poder abrir um deal de qualquer funil.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: Deep-link em `/painel-vendas`

**Files:**
- Modify: `frontend/src/app/(authenticated)/painel-vendas/page.tsx`

**Depende de:** Task 3 (`GET /api/sales/[id]`).

- [ ] **Step 1: Envolver em `Suspense` e importar navigation**

Troque a linha de import do topo:

```ts
import { useState, useEffect } from "react";
```

por:

```ts
import { useState, useEffect, useRef, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
```

Troque `export default function PainelVendasPage() {` por `function PainelVendasPageInner() {`.

No final do arquivo, depois do fechamento da função `PainelVendasPageInner`, adicione:

```tsx
export default function PainelVendasPage() {
  return (
    <Suspense>
      <PainelVendasPageInner />
    </Suspense>
  );
}
```

- [ ] **Step 2: Adicionar o deep-link**

Dentro de `PainelVendasPageInner`, logo após `const [editingSale, setEditingSale] = useState<Sale | null>(null);`,
adicione:

```ts
  const searchParams = useSearchParams();
  const router = useRouter();
  const deepLinkApplied = useRef(false);

  // Deep-link: /busca?sale_id= pode apontar pra uma venda fora do período/página
  // atual da listagem, então busca direto por id em vez de depender de `sales`.
  useEffect(() => {
    if (deepLinkApplied.current) return;
    const saleId = searchParams.get("sale_id");
    if (!saleId) return;
    deepLinkApplied.current = true;
    fetch(`/api/sales/${saleId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((sale) => {
        if (sale) setEditingSale(sale);
        router.replace("/painel-vendas");
      });
  }, [searchParams, router]);
```

- [ ] **Step 3: Verificar manualmente**

Run: `cd frontend && npm run type-check`
Expected: sem erros de tipo.

Com o app rodando, abra `/painel-vendas?sale_id=<id de uma venda de um mês anterior ao atual>` — confirme que o
modal de edição da venda abre mesmo estando fora do filtro padrão de período (mês corrente), e a URL volta limpa.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/(authenticated)/painel-vendas/page.tsx"
git commit -m "feat(painel-vendas): deep-link /painel-vendas?sale_id= (busca direta por id)

Necessário p/ a /busca poder abrir uma venda fora do período padrão.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Pós-implementação (não automatizável por subagent)

- **Aplicar `supabase/migrations/20260818_universal_search.sql` manualmente no Supabase** — mesmo fluxo de todas
  as outras migrations do projeto (SQL Editor ou `supabase db push`). Sem isso, `/api/search` responde 500.
- **Rodar a suíte completa** (`cd frontend && npx vitest run`) e `npm run type-check` no repo inteiro depois da
  última task, para pegar qualquer regressão cruzada entre tasks.
- **Smoke test end-to-end manual**: com a migration aplicada, logar como vendedor (não-admin) e como admin, buscar
  um termo que exista em pelo menos um lead, um deal, uma venda e uma conversa, e confirmar que cada aba mostra o
  resultado certo e que vendedor não vê deals/conversas de outro vendedor.

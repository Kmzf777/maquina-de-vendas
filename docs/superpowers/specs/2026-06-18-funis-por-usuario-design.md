# Funis de vendas por usuário — Design

**Data:** 2026-06-18
**Branch:** `feat/funis-por-usuario`
**Status:** Aprovado (aguardando revisão do spec)

---

## 1. Problema

Hoje os funis de vendas (`pipelines`) são **universais**: qualquer usuário autenticado
vê e edita todos os funis e todos os deals. Queremos funis **por usuário**, como em
CRMs profissionais: cada vendedor enxerga apenas os seus funis; o admin enxerga todos.

## 2. Decisões de produto (confirmadas)

1. **A unidade com dono é o funil** (`pipelines.owner_user_id`), não o deal. Stages e
   deals herdam o dono via `pipeline_id`.
2. **Isolamento puro:** todo funil tem exatamente um dono. **Não existe funil global**
   (sem dono visível a todos). O admin vê todos os funis por ser admin, não por posse.
3. **Migração:** o usuário fornecerá o mapa `funil → dono`. Funis sem mapeamento
   recaem para o admin principal.
4. **Admin pode reatribuir o dono pela UI** (seletor de "Dono" nos modais de funil).

## 3. Abordagem escolhida — C (Híbrida: RLS para leitura + guarda na API para escrita)

Existem dois caminhos de acesso aos dados de funis/deals:

- **Leitura (browser):** `usePipelines`, `usePipelineStages`, `useRealtimeDeals` leem o
  Supabase **diretamente** com o JWT do usuário → governado por **RLS**.
- **Escrita (API):** rotas `/api/pipelines`, `/api/deals` usam `getServiceSupabase()`
  (service role) → **ignoram RLS** → exigem checagem de posse no código.

**Decisão:** ativar **RLS** em `pipelines`, `pipeline_stages` e `deals` para escopar
leitura e realtime automaticamente, **e** adicionar guardas de posse explícitas nas
rotas de escrita (que usam service role).

### Alternativas rejeitadas
- **B — só API:** vaza pelo realtime (assinaturas leem direto do Postgres; sem RLS, o
  vendedor recebe eventos de deals de outros). Exigiria refazer todo o realtime via API.
- **Funil global / compartilhamento multiusuário:** descartados por decisão de produto
  (isolamento puro) e YAGNI.

## 4. Modelo de dados

```sql
ALTER TABLE pipelines
  ADD COLUMN IF NOT EXISTS owner_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_pipelines_owner_user_id ON pipelines(owner_user_id);
```

- Backfill conforme o mapa do usuário; restante → admin principal.
- Após o backfill, `ALTER TABLE pipelines ALTER COLUMN owner_user_id SET NOT NULL`
  (isolamento puro = todo funil tem dono).
- `pipeline_stages` e `deals` **não** ganham coluna nova — herdam via `pipeline_id`.
- Espelha exatamente o precedente `channels.owner_user_id` (migration `20260610`).

## 5. Enforcement — RLS

Hoje `pipelines`, `pipeline_stages` e `deals` estão **sem RLS** (tudo liberado). Ao
ativar, é *deny-by-default*: é obrigatório criar as policies de SELECT abaixo, senão a
leitura no browser quebra. As rotas de API (service role) continuam funcionando porque
ignoram RLS.

```sql
-- Helper: admin pelo claim do JWT (app_metadata.role)
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT COALESCE((auth.jwt() -> 'app_metadata' ->> 'role') = 'admin', false);
$$;

ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;
CREATE POLICY pipelines_select ON pipelines FOR SELECT TO authenticated
  USING (public.is_admin() OR owner_user_id = auth.uid());

ALTER TABLE pipeline_stages ENABLE ROW LEVEL SECURITY;
CREATE POLICY pipeline_stages_select ON pipeline_stages FOR SELECT TO authenticated
  USING (public.is_admin() OR EXISTS (
    SELECT 1 FROM pipelines p
    WHERE p.id = pipeline_stages.pipeline_id AND p.owner_user_id = auth.uid()
  ));

ALTER TABLE deals ENABLE ROW LEVEL SECURITY;
CREATE POLICY deals_select ON deals FOR SELECT TO authenticated
  USING (public.is_admin() OR EXISTS (
    SELECT 1 FROM pipelines p
    WHERE p.id = deals.pipeline_id AND p.owner_user_id = auth.uid()
  ));
```

**Sem policies de INSERT/UPDATE/DELETE** — de propósito. Sem elas, *deny-by-default*
bloqueia escrita direta pelo client (anon key); **toda escrita passa obrigatoriamente
pela API** (service role), que é onde aplicamos a guarda de posse. Isso fecha o caminho
de um vendedor escrever direto via PostgREST.

### Notas de comportamento
- **Admin primeiro** em todas as policies (curto-circuito; admin também vê deals órfãos
  com `pipeline_id` NULL).
- **Realtime INSERT/UPDATE** respeitam RLS (linha completa) → escopados corretamente.
- **Realtime DELETE** transmite apenas a PK e pode chegar a assinantes fora do escopo;
  porém os hooks só disparam um `fetch` re-escopado por RLS → **sem vazamento de dados**,
  no máximo um refetch extra inócuo.

## 6. Rotas de API — guarda de posse na escrita

Novo helper `frontend/src/lib/supabase/pipeline-access.ts` (irmão de `channel-access.ts`,
fail-closed em erro de auth):

```ts
// null  => admin (sem restrição)
// string[] => apenas esses pipeline_ids
export async function getAllowedPipelineIds(supabase): Promise<string[] | null>;

// 403 se não for admin nem dono do funil; 401 se auth falhar
export async function assertCanWritePipeline(pipelineId: string): Promise<...>;
```

Alterações nas rotas (todas via service role hoje):

- **`POST /api/pipelines`** — resolver dono: vendedor → `owner_user_id = self`;
  admin → `owner_user_id = (body.owner_user_id || self)`. Lê o usuário via
  `createServerClient().auth.getUser()`.
- **`PATCH/DELETE /api/pipelines/[id]`** — exigir admin ou dono. Trocar `owner_user_id`
  só é permitido para admin.
- **`/api/pipelines/[id]/stages` (POST) e `/stages/[stageId]` (PATCH/DELETE)** — validar
  posse do funil-pai.
- **`POST /api/deals`** — validar que o chamador pode escrever no `body.pipeline_id`.
- **`PATCH/DELETE /api/deals/[id]`** — carregar o deal → seu funil → validar posse.

`requireAdmin()` (`lib/admin-auth.ts`) já existe e é reusado onde a ação é estritamente
admin (ex.: trocar dono).

## 7. Frontend

- **Tipos** (`lib/types.ts`): adicionar `owner_user_id: string` em `Pipeline`.
- **Detecção de role no client:** extrair um hook compartilhado `useCurrentRole()`
  (espelha o `useUser()` privado de `sidebar.tsx`, que lê `session.user.app_metadata.role`).
- **`PipelineCreateModal` e `PipelineEditModal`:** seletor **"Dono"** visível **apenas
  para admin** (lista usuários via `GET /api/users`). Vendedor não vê o seletor — vira
  dono automaticamente no backend.
- **`PipelineSwitcher`:** para admin, exibir o nome do dono ao lado de cada funil
  (mapa `id→nome` a partir de `/api/users`). Vendedor não precisa (só vê os seus).
- **Leitura/realtime:** sem mudança — RLS escopa. `usePipelines` usa `select("*")`, que
  já trará `owner_user_id` assim que a coluna existir.

## 8. Migração / rollout

- Arquivo: `backend/migrations/20260618_pipelines_owner_user.sql` (mesmo diretório do
  precedente `20260610_channel_owner_user.sql`).
- Aplicado **manualmente no Supabase SQL Editor** (padrão do repo para mudanças de schema).
- Conteúdo: `ADD COLUMN` + índice → backfill pelo mapa do usuário (`UPDATE ... WHERE
  name = ...`) + fallback admin para o restante → `SET NOT NULL` → `is_admin()` +
  policies + `ENABLE ROW LEVEL SECURITY`.
- **Deals órfãos** (`pipeline_id` NULL): verificar a contagem antes; admin continua
  vendo-os pela policy. Decidir com o usuário se limpa/atribui (provavelmente irrelevante,
  pois `013` já removeu os deals do "Funil Principal").
- Antes de gerar o mapa, fornecer ao usuário uma query para listar `pipelines` atuais e
  os `user_id`/email dos vendedores.

## 9. Testes

- **Vitest (unit):** `getAllowedPipelineIds` — admin → `null`; vendedor → ids dos funis
  próprios; falha de auth → lança `PipelineAccessError`. (Mock do supabase, no padrão de
  `import-deals.test.ts`.)
- **Vitest (unit):** lógica de resolução de dono no `POST /api/pipelines` (vendedor=self;
  admin=selecionado||self) e a guarda `assertCanWritePipeline`.
- **Checklist manual de RLS no Supabase** (não há Postgres no CI):
  - Login como vendedor A → vê só os funis/deals de A; não vê os de B; realtime não traz
    eventos de B.
  - Login como admin → vê todos.
  - Tentativa de escrita direta via client (anon key) é negada.

## 10. Premissas validadas e riscos

- ✅ `leads` **não tem RLS** → o join `deals→leads` continua funcionando após ligar RLS
  em `deals`.
- ✅ `pipelines/pipeline_stages/deals` **sem RLS hoje** → ativar é deny-by-default
  (policies de SELECT obrigatórias).
- ✅ JWT carrega `app_metadata.role` (já usado em `channel-access.ts` e `sidebar.tsx`).
- ⚠️ **Auditar outras leituras no browser** de `deals`/`pipelines` (ex.: dashboard) para
  garantir que nenhuma feature dependa de um vendedor ver tudo. Com RLS, leituras em
  contexto de vendedor passam a escopar (comportamento desejado); confirmar caso a caso.
- ⚠️ Deals órfãos (`pipeline_id` NULL) — tratados pela policy (admin vê) e verificados na
  migração.

## 11. Fora de escopo (YAGNI)

- Funil global/compartilhado entre vendedores.
- Compartilhamento de um funil com múltiplos usuários (tabela de membros).
- Posse no nível do deal independente do funil.
- Reatribuição em massa de funis.

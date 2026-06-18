# Funis de vendas por usuário — Design

**Data:** 2026-06-18
**Branch:** `feat/funis-por-usuario`
**Status:** Aprovado (aguardando revisão do spec — v2)

---

## 1. Problema

Hoje os funis de vendas (`pipelines`) são **universais**: qualquer usuário autenticado
vê e edita todos os funis e todos os deals. Queremos funis **por usuário**, como em
CRMs profissionais: cada vendedor enxerga apenas os seus funis; o admin enxerga todos;
e um funil de sistema (Blacklist) permanece visível e utilizável por todos.

## 2. Decisões de produto (confirmadas)

1. **A unidade com dono é o funil** (`pipelines.owner_user_id`), não o deal. Stages e
   deals herdam o dono via `pipeline_id`.
2. **Três tipos de funil:**
   - **Pessoal** — `owner_user_id = <vendedor>`. Visível/editável pelo dono **+** admins.
   - **Administrativo** — `owner_user_id = NULL`. Visível/editável **só por admins**.
     Espelha exatamente a semântica de `channels.owner_user_id` (NULL = administrativo).
   - **Universal** — `is_universal = true`. Visível **e editável por todos** os usuários
     autenticados. Reservado ao **Blacklist** (funil de sistema que bloqueia leads).
3. **Migração** (mapa fornecido pelo usuário):
   - Funis com "João" no nome → `joao@cafecanastra.com`.
   - **Blacklist** (`id = 8988e852-2836-4add-b023-4db4d6cd0e6e`) → `is_universal = true`.
   - Todos os demais → **administrativo** (`owner_user_id = NULL`).
4. **Admin pode definir/trocar o dono pela UI** (seletor de "Dono" nos modais de funil,
   com a opção "Administrativo" = NULL e a lista de vendedores).

## 3. Abordagem escolhida — C (Híbrida: RLS para leitura + guarda na API para escrita)

Existem dois caminhos de acesso aos dados de funis/deals:

- **Leitura (browser):** `usePipelines`, `usePipelineStages`, `useRealtimeDeals` leem o
  Supabase **diretamente** com o JWT do usuário → governado por **RLS**.
- **Escrita (API/backend):** rotas `/api/pipelines`, `/api/deals` e o backend de opt-out
  usam **service role** → **ignoram RLS** → exigem checagem de posse no código.

**Decisão:** ativar **RLS** em `pipelines`, `pipeline_stages` e `deals` para escopar
leitura e realtime automaticamente, **e** adicionar guardas de posse explícitas nas
rotas de escrita.

### Alternativas rejeitadas
- **B — só API:** vaza pelo realtime (assinaturas leem direto do Postgres; sem RLS, o
  vendedor recebe eventos de deals de outros). Exigiria refazer todo o realtime via API.
- **Compartilhamento multiusuário** (um funil com vários donos): descartado por YAGNI.

## 4. Modelo de dados

```sql
ALTER TABLE pipelines
  ADD COLUMN IF NOT EXISTS owner_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE pipelines
  ADD COLUMN IF NOT EXISTS is_universal boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_pipelines_owner_user_id ON pipelines(owner_user_id);
```

- `owner_user_id` é **nullable**: NULL = funil administrativo (igual a `channels`).
  **Não** aplicamos `SET NOT NULL` (o tipo "administrativo" depende de NULL).
- `is_universal` é a flag explícita do funil de sistema (segue o padrão de `is_protected`
  nas stages). Mais claro que sobrecarregar a semântica de NULL.
- `pipeline_stages` e `deals` **não** ganham coluna nova — herdam via `pipeline_id`.

## 5. Enforcement — RLS

Hoje `pipelines`, `pipeline_stages` e `deals` estão **sem RLS** (tudo liberado). Ao
ativar, é *deny-by-default*: é obrigatório criar as policies de SELECT abaixo, senão a
leitura no browser quebra. As rotas de API/backend (service role) continuam funcionando
porque ignoram RLS.

```sql
-- Helper: admin pelo claim do JWT (app_metadata.role)
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT COALESCE((auth.jwt() -> 'app_metadata' ->> 'role') = 'admin', false);
$$;

ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;
CREATE POLICY pipelines_select ON pipelines FOR SELECT TO authenticated
  USING (public.is_admin() OR owner_user_id = auth.uid() OR is_universal);

ALTER TABLE pipeline_stages ENABLE ROW LEVEL SECURITY;
CREATE POLICY pipeline_stages_select ON pipeline_stages FOR SELECT TO authenticated
  USING (public.is_admin() OR EXISTS (
    SELECT 1 FROM pipelines p
    WHERE p.id = pipeline_stages.pipeline_id
      AND (p.owner_user_id = auth.uid() OR p.is_universal)
  ));

ALTER TABLE deals ENABLE ROW LEVEL SECURITY;
CREATE POLICY deals_select ON deals FOR SELECT TO authenticated
  USING (public.is_admin() OR EXISTS (
    SELECT 1 FROM pipelines p
    WHERE p.id = deals.pipeline_id
      AND (p.owner_user_id = auth.uid() OR p.is_universal)
  ));
```

**Sem policies de INSERT/UPDATE/DELETE** — de propósito. Sem elas, *deny-by-default*
bloqueia escrita direta pelo client (anon key); **toda escrita passa pela API/backend**
(service role), onde aplicamos a guarda de posse. Fecha o caminho de um vendedor escrever
direto via PostgREST.

### Notas de comportamento
- **Admin primeiro** (curto-circuito); admin vê tudo, inclusive deals órfãos (`pipeline_id`
  NULL) e funis administrativos.
- **Funil administrativo (owner NULL, não universal):** o `EXISTS` falha (NULL ≠ uid e
  `is_universal` false) → só o ramo `is_admin()` libera → **visível apenas a admins**. ✔
- **Realtime INSERT/UPDATE** respeitam RLS (linha completa) → escopados.
- **Realtime DELETE** transmite só a PK e pode chegar fora do escopo; os hooks só fazem
  `fetch` re-escopado por RLS → **sem vazamento de dados**, no máximo um refetch inócuo.

## 6. Enforcement — guarda de posse na escrita (API)

Novo helper `frontend/src/lib/supabase/pipeline-access.ts` (irmão de `channel-access.ts`,
fail-closed em erro de auth):

```ts
// null  => admin (sem restrição)
// string[] => apenas esses pipeline_ids (pessoais do vendedor + universais)
export async function getAllowedPipelineIds(supabase): Promise<string[] | null>;

// Pode escrever se: admin OU dono OU funil universal. Senão 403; 401 se auth falhar.
export async function assertCanWritePipeline(pipelineId: string): Promise<...>;
```

Regra de escrita: **`is_admin() OR owner_user_id = auth.uid() OR is_universal`**.
Isso atende à decisão do Blacklist ("todos podem mover cards"): por ser universal, é
gravável por qualquer autenticado.

Alterações nas rotas (todas via service role hoje):

- **`POST /api/pipelines`** — resolver dono lendo o usuário via
  `createServerClient().auth.getUser()`:
  - vendedor → `owner_user_id = self`;
  - admin → `owner_user_id = body.owner_user_id` (pode ser um vendedor **ou NULL** =
    administrativo).
- **`PATCH/DELETE /api/pipelines/[id]`** — exigir admin ou dono. Trocar `owner_user_id`
  (e `is_universal`) só é permitido para admin.
- **`/api/pipelines/[id]/stages` (POST) e `/stages/[stageId]` (PATCH/DELETE)** — validar
  posse do funil-pai (`assertCanWritePipeline`).
- **`POST /api/deals`** — validar escrita no `body.pipeline_id`.
- **`PATCH/DELETE /api/deals/[id]`** — carregar o deal → seu funil → validar posse. Em
  movimentação entre funis (ex.: arrastar para o Blacklist), validar origem **e** destino.

`requireAdmin()` (`lib/admin-auth.ts`) já existe e é reusado nas ações estritamente admin
(trocar dono, marcar universal).

### Blacklist / opt-out (não muda)
O bloqueio do dia a dia roda no **backend com service role**, imune a RLS:
`move_lead_deals_to_blacklist()` em `backend/app/leads/service.py`
(`BLACKLIST_PIPELINE_ID = 8988e852-…`, `BLACKLIST_STAGE_ID = fbace13d-…`), disparado pelo
tool `registrar_optout` e pelo botão **"Parar mensagens"** (`POST /api/leads/{id}/optout`).
Continua funcionando para todos.

## 7. Frontend

- **Tipos** (`lib/types.ts`): em `Pipeline`, adicionar `owner_user_id: string | null` e
  `is_universal: boolean`.
- **Detecção de role no client:** extrair um hook compartilhado `useCurrentRole()`
  (espelha o `useUser()` privado de `sidebar.tsx`, que lê `session.user.app_metadata.role`).
- **`GET /api/users`:** estender o retorno para incluir `role` (de `app_metadata`), para o
  seletor listar/agrupar vendedores e oferecer a opção "Administrativo".
- **`PipelineCreateModal` e `PipelineEditModal`:** seletor **"Dono"** visível **apenas
  para admin**. Opções: **"Administrativo (todos os admins)"** (= NULL) + cada vendedor.
  Vendedor não vê o seletor — vira dono automaticamente no backend. `is_universal` **não**
  é exposto na UI (só o Blacklist é universal, e já existe; criar novos universais = SQL).
- **`PipelineSwitcher`:** para admin, exibir rótulo do tipo/dono de cada funil —
  "Universal" (Blacklist), "Administrativo" (NULL) ou o nome do vendedor.
- **Leitura/realtime:** sem mudança — RLS escopa. `usePipelines` usa `select("*")`, que já
  trará as novas colunas.

## 8. Migração / rollout

- Arquivo: `backend/migrations/20260618_pipelines_owner_user.sql` (mesmo diretório do
  precedente `20260610_channel_owner_user.sql`). Aplicado **manualmente no Supabase SQL
  Editor** (padrão do repo). Idempotente.
- **Pré-check** (rodar antes, conferir à mão): listar funis e marcar quais casam com
  "João" e qual é o Blacklist.
  ```sql
  SELECT id, name FROM pipelines ORDER BY order_index;
  ```
- **Backfill:**
  ```sql
  -- 1. João: falha alto se o usuário não existir (evita virar administrativo silencioso)
  DO $$
  DECLARE v_joao uuid;
  BEGIN
    SELECT id INTO v_joao FROM auth.users WHERE email = 'joao@cafecanastra.com';
    IF v_joao IS NULL THEN
      RAISE EXCEPTION 'Usuário joao@cafecanastra.com não encontrado em auth.users';
    END IF;
    UPDATE pipelines
      SET owner_user_id = v_joao
      WHERE (name ILIKE '%joão%' OR name ILIKE '%joao%')
        AND id <> '8988e852-2836-4add-b023-4db4d6cd0e6e';
  END $$;

  -- 2. Blacklist: universal (dono permanece NULL)
  UPDATE pipelines
    SET is_universal = true, owner_user_id = NULL
    WHERE id = '8988e852-2836-4add-b023-4db4d6cd0e6e';

  -- 3. Demais: já nascem com owner_user_id = NULL (= administrativo). Nada a fazer.
  ```
- **Deals órfãos** (`pipeline_id` NULL): admin continua vendo-os pela policy; verificar a
  contagem antes (provavelmente irrelevante — `013` removeu os deals do "Funil Principal").

## 9. Testes

- **Vitest (unit):** `getAllowedPipelineIds` — admin → `null`; vendedor → ids dos próprios
  + universais; falha de auth → lança `PipelineAccessError`. (Mock do supabase, no padrão
  de `import-deals.test.ts`.)
- **Vitest (unit):** resolução de dono no `POST /api/pipelines` (vendedor=self;
  admin=selecionado||NULL) e a guarda `assertCanWritePipeline` (admin / dono / universal /
  negado).
- **Checklist manual de RLS no Supabase** (não há Postgres no CI):
  - Vendedor A → vê só os funis/deals de A **+ o Blacklist**; não vê funis de B nem
    administrativos; realtime não traz eventos de B.
  - Admin → vê todos (pessoais, administrativos, universal).
  - Vendedor consegue mover cards no Blacklist (universal gravável por todos); não consegue
    escrever em funil administrativo.
  - Escrita direta via client (anon key) é negada.
  - Opt-out ("Parar mensagens") continua movendo deals ao Blacklist normalmente.

## 10. Premissas validadas e riscos

- ✅ `leads` **não tem RLS** → o join `deals→leads` continua funcionando após ligar RLS.
- ✅ `pipelines/pipeline_stages/deals` **sem RLS hoje** → ativar é deny-by-default
  (policies de SELECT obrigatórias).
- ✅ JWT carrega `app_metadata.role` (já usado em `channel-access.ts` e `sidebar.tsx`).
- ✅ Blacklist/opt-out roda no backend (service role) → imune a RLS.
- ⚠️ **Auditar outras leituras no browser** de `deals`/`pipelines` (ex.: dashboard) para
  garantir que nenhuma feature dependa de um vendedor ver tudo. Com RLS, leituras em
  contexto de vendedor passam a escopar (comportamento desejado); confirmar caso a caso.
- ⚠️ **Visibilidade no Blacklist:** por ser universal, todo vendedor vê os deals de leads
  bloqueados de **todos** os vendedores (com nome/telefone via join). Aceitável para um
  blocklist compartilhado; registrado aqui por transparência.
- ⚠️ Nome dos funis do João: o backfill casa por `ILIKE '%joão%'/'%joao%'`. Conferir o
  pré-check para não casar/escapar nada por engano.

## 11. Fora de escopo (YAGNI)

- Marcar funis arbitrários como universais pela UI (só Blacklist; novos = SQL).
- Compartilhamento de um funil com múltiplos usuários específicos (tabela de membros).
- Posse no nível do deal independente do funil.
- Reatribuição em massa de funis.

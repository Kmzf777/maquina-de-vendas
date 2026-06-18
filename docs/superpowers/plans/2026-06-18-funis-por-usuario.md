# Funis por usuário — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar os funis de vendas (`pipelines`) por usuário — cada vendedor vê/edita só os seus, admin vê todos, e o Blacklist permanece universal — via RLS para leitura e guarda de posse na API para escrita.

**Architecture:** `pipelines` ganha `owner_user_id` (nullable; NULL = administrativo, igual a `channels`) e `is_universal` (Blacklist). RLS escopa leitura/realtime (browser lê direto). As rotas de escrita usam service role (ignoram RLS) e aplicam guardas. **Dois predicados** de escrita: mover *deals* (admin/dono/universal) ≠ gerenciar *estrutura* do funil (admin/dono — sem universal, para o Blacklist não ser excluído/renomeado por vendedor).

**Tech Stack:** Next.js 16 (App Router, Server Components), Supabase (Postgres + RLS + Realtime), TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-06-18-funis-por-usuario-design.md`

---

## Notas de execução (ler antes de começar)

- Todos os comandos rodam a partir da raiz do repo. O front fica em `frontend/`; use `npm --prefix frontend run <script>`.
- Scripts disponíveis (`frontend/package.json`): `type-check` (`tsc --noEmit`), `lint` (`eslint`), `test` (`vitest run`).
- **A migration (Task 1) NÃO é aplicada por estes passos.** É aplicada manualmente no Supabase pelo usuário, em sequência coordenada com o deploy (a Parte B liga RLS e é um corte que afeta produção no ato). Os subagents só criam o arquivo `.sql` e validam código/tipos/lint/testes.
- Padrão de acesso já existente para espelhar: `frontend/src/lib/supabase/channel-access.ts`.

---

## File Structure

**Criar:**
- `backend/migrations/20260618_pipelines_owner_user.sql` — colunas + backfill + RLS.
- `frontend/src/lib/supabase/pipeline-access.ts` — predicados puros + guardas de IO.
- `frontend/src/lib/supabase/pipeline-access.test.ts` — testes Vitest dos predicados puros.
- `frontend/src/hooks/use-current-role.ts` — hook client `useCurrentRole()`.

**Modificar:**
- `frontend/src/lib/types.ts` — `Pipeline` += `owner_user_id`, `is_universal`.
- `frontend/src/app/api/users/route.ts` — incluir `role` no retorno.
- `frontend/src/app/api/pipelines/route.ts` — POST resolve dono; GET escopa.
- `frontend/src/app/api/pipelines/[id]/route.ts` — PATCH/DELETE guarda + troca de dono (admin).
- `frontend/src/app/api/pipelines/[id]/stages/route.ts` — POST guarda.
- `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts` — PATCH/DELETE guarda.
- `frontend/src/app/api/deals/route.ts` — POST guarda; GET escopa.
- `frontend/src/app/api/deals/[id]/route.ts` — PATCH/DELETE guarda.
- `frontend/src/components/deals/pipeline-create-modal.tsx` — seletor de dono (admin).
- `frontend/src/components/deals/pipeline-edit-modal.tsx` — seletor de dono (admin).
- `frontend/src/components/deals/pipeline-switcher.tsx` — rótulo de tipo/dono (admin).
- `frontend/src/app/(authenticated)/vendas/page.tsx` — fiação (create com dono, props do switcher/edit).

---

## Task 1: Migration SQL (colunas + backfill + RLS)

**Files:**
- Create: `backend/migrations/20260618_pipelines_owner_user.sql`

- [ ] **Step 1: Criar o arquivo de migração**

```sql
-- 20260618_pipelines_owner_user.sql
-- Funis por usuário: owner_user_id (NULL = administrativo, igual a channels) + is_universal (Blacklist).
-- Idempotente. Aplicar manualmente no Supabase SQL Editor.
--
-- SEQUÊNCIA DE ROLLOUT:
--   PARTE A (colunas + backfill) — segura, pode aplicar a qualquer momento.
--   Deploy do frontend (cria funis com dono, guardas na API, UI).
--   PARTE B (RLS) — CORTE: passa a escopar leitura/realtime no ato. Aplicar após o deploy do frontend.

-- ============================================================
-- PARTE A — Colunas + índice + backfill
-- ============================================================
ALTER TABLE pipelines
  ADD COLUMN IF NOT EXISTS owner_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE pipelines
  ADD COLUMN IF NOT EXISTS is_universal boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_pipelines_owner_user_id ON pipelines(owner_user_id);

COMMENT ON COLUMN pipelines.owner_user_id IS
  'Dono do funil. NULL = administrativo (visível só a admins, igual a channels.owner_user_id).';
COMMENT ON COLUMN pipelines.is_universal IS
  'Funil de sistema visível e gravável (deals) por todos. Reservado ao Blacklist.';

-- 1. Funis do João → joao@cafecanastra.com (falha alto se o usuário não existir)
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

-- 2. Blacklist → universal (dono permanece NULL)
UPDATE pipelines
  SET is_universal = true, owner_user_id = NULL
  WHERE id = '8988e852-2836-4add-b023-4db4d6cd0e6e';

-- 3. Demais funis já têm owner_user_id = NULL (= administrativo). Nada a fazer.

-- ============================================================
-- PARTE B — RLS (CORTE: aplicar após deploy do frontend)
-- ============================================================
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT COALESCE((auth.jwt() -> 'app_metadata' ->> 'role') = 'admin', false);
$$;

ALTER TABLE pipelines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pipelines_select ON pipelines;
CREATE POLICY pipelines_select ON pipelines FOR SELECT TO authenticated
  USING (public.is_admin() OR owner_user_id = auth.uid() OR is_universal);

ALTER TABLE pipeline_stages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pipeline_stages_select ON pipeline_stages;
CREATE POLICY pipeline_stages_select ON pipeline_stages FOR SELECT TO authenticated
  USING (public.is_admin() OR EXISTS (
    SELECT 1 FROM pipelines p
    WHERE p.id = pipeline_stages.pipeline_id
      AND (p.owner_user_id = auth.uid() OR p.is_universal)
  ));

ALTER TABLE deals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS deals_select ON deals;
CREATE POLICY deals_select ON deals FOR SELECT TO authenticated
  USING (public.is_admin() OR EXISTS (
    SELECT 1 FROM pipelines p
    WHERE p.id = deals.pipeline_id
      AND (p.owner_user_id = auth.uid() OR p.is_universal)
  ));

-- Sem policies de INSERT/UPDATE/DELETE: escrita direta pelo client fica bloqueada;
-- toda escrita passa pela API/backend (service role).
```

- [ ] **Step 2: Validar a sintaxe SQL por revisão**

Não há Postgres no CI. Conferir à mão: dois `ADD COLUMN IF NOT EXISTS`, o bloco `DO` com `RAISE EXCEPTION`, o id do Blacklist `8988e852-2836-4add-b023-4db4d6cd0e6e`, e as 3 policies de SELECT com `DROP POLICY IF EXISTS` antes (idempotência).

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/20260618_pipelines_owner_user.sql
git commit -m "feat(funis): migration owner_user_id + is_universal + RLS de pipelines"
```

---

## Task 2: Tipos — Pipeline += owner_user_id, is_universal

**Files:**
- Modify: `frontend/src/lib/types.ts:32-38`

- [ ] **Step 1: Adicionar os campos à interface Pipeline**

Substituir a interface `Pipeline` por:

```ts
export interface Pipeline {
  id: string;
  name: string;
  order_index: number;
  owner_user_id: string | null;
  is_universal: boolean;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 2: Type-check**

Run: `npm --prefix frontend run type-check`
Expected: PASS (sem erros). Se algum consumidor exigir os campos, será resolvido nas tasks seguintes.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(funis): Pipeline ganha owner_user_id e is_universal"
```

---

## Task 3: pipeline-access — predicados puros + testes (TDD)

**Files:**
- Create: `frontend/src/lib/supabase/pipeline-access.ts`
- Test: `frontend/src/lib/supabase/pipeline-access.test.ts`

- [ ] **Step 1: Escrever os testes que falham**

Criar `frontend/src/lib/supabase/pipeline-access.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  canWriteDealsInPipeline,
  canManagePipeline,
  resolvePipelineOwnerOnCreate,
} from "@/lib/supabase/pipeline-access";

const admin = { userId: "u-admin", role: "admin" };
const joao = { userId: "u-joao", role: "vendedor" };
const maria = { userId: "u-maria", role: "vendedor" };

const joaoPipeline = { owner_user_id: "u-joao", is_universal: false };
const adminPipeline = { owner_user_id: null, is_universal: false };
const blacklist = { owner_user_id: null, is_universal: true };

describe("canWriteDealsInPipeline", () => {
  it("admin escreve em qualquer funil", () => {
    expect(canWriteDealsInPipeline(admin, joaoPipeline)).toBe(true);
    expect(canWriteDealsInPipeline(admin, adminPipeline)).toBe(true);
    expect(canWriteDealsInPipeline(admin, blacklist)).toBe(true);
  });
  it("vendedor escreve no próprio funil", () => {
    expect(canWriteDealsInPipeline(joao, joaoPipeline)).toBe(true);
  });
  it("vendedor NÃO escreve no funil de outro vendedor", () => {
    expect(canWriteDealsInPipeline(maria, joaoPipeline)).toBe(false);
  });
  it("vendedor NÃO escreve em funil administrativo", () => {
    expect(canWriteDealsInPipeline(joao, adminPipeline)).toBe(false);
  });
  it("qualquer vendedor escreve no funil universal (Blacklist)", () => {
    expect(canWriteDealsInPipeline(maria, blacklist)).toBe(true);
  });
});

describe("canManagePipeline", () => {
  it("admin gerencia qualquer funil", () => {
    expect(canManagePipeline(admin, blacklist)).toBe(true);
    expect(canManagePipeline(admin, adminPipeline)).toBe(true);
  });
  it("vendedor gerencia o próprio funil", () => {
    expect(canManagePipeline(joao, joaoPipeline)).toBe(true);
  });
  it("vendedor NÃO gerencia funil universal (não exclui/renomeia Blacklist)", () => {
    expect(canManagePipeline(maria, blacklist)).toBe(false);
  });
  it("vendedor NÃO gerencia funil de outro nem administrativo", () => {
    expect(canManagePipeline(maria, joaoPipeline)).toBe(false);
    expect(canManagePipeline(joao, adminPipeline)).toBe(false);
  });
});

describe("resolvePipelineOwnerOnCreate", () => {
  it("vendedor sempre vira dono (ignora o solicitado)", () => {
    expect(resolvePipelineOwnerOnCreate(joao, null)).toBe("u-joao");
    expect(resolvePipelineOwnerOnCreate(joao, "u-maria")).toBe("u-joao");
  });
  it("admin usa o dono solicitado", () => {
    expect(resolvePipelineOwnerOnCreate(admin, "u-joao")).toBe("u-joao");
  });
  it("admin sem seleção cria funil administrativo (null)", () => {
    expect(resolvePipelineOwnerOnCreate(admin, null)).toBeNull();
    expect(resolvePipelineOwnerOnCreate(admin, undefined)).toBeNull();
  });
});
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `npm --prefix frontend run test -- src/lib/supabase/pipeline-access.test.ts`
Expected: FAIL — não resolve `@/lib/supabase/pipeline-access` (arquivo ainda não existe).

- [ ] **Step 3: Implementar os predicados puros (mínimo para passar)**

Criar `frontend/src/lib/supabase/pipeline-access.ts`:

```ts
export interface CurrentUser {
  userId: string;
  role: string | undefined;
}

export interface PipelineOwnership {
  owner_user_id: string | null;
  is_universal: boolean;
}

/** Mover/criar DEALS no funil: admin OU dono OU universal. */
export function canWriteDealsInPipeline(user: CurrentUser, p: PipelineOwnership): boolean {
  return user.role === "admin" || p.is_universal || p.owner_user_id === user.userId;
}

/** Gerenciar a ESTRUTURA do funil (renomear, stages, excluir, trocar dono): admin OU dono. */
export function canManagePipeline(user: CurrentUser, p: PipelineOwnership): boolean {
  return user.role === "admin" || p.owner_user_id === user.userId;
}

/** Dono ao criar: vendedor → sempre ele mesmo; admin → o solicitado (null = administrativo). */
export function resolvePipelineOwnerOnCreate(
  user: CurrentUser,
  requestedOwnerId: string | null | undefined,
): string | null {
  if (user.role === "admin") return requestedOwnerId ?? null;
  return user.userId;
}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `npm --prefix frontend run test -- src/lib/supabase/pipeline-access.test.ts`
Expected: PASS (todos os describes verdes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/supabase/pipeline-access.ts frontend/src/lib/supabase/pipeline-access.test.ts
git commit -m "feat(funis): predicados puros de acesso a funil (deals vs gestão) + testes"
```

---

## Task 4: pipeline-access — guardas de IO (getCurrentUser, asserts, getAllowedPipelineIds)

**Files:**
- Modify: `frontend/src/lib/supabase/pipeline-access.ts`

- [ ] **Step 1: Acrescentar as funções de IO ao final do arquivo**

Adicionar ao final de `frontend/src/lib/supabase/pipeline-access.ts` (mantendo os predicados puros já existentes no topo):

```ts
import { createClient as createServerClient } from "@/lib/supabase/server";
import type { getServiceSupabase } from "@/lib/supabase/api";

type ServiceSupabase = Awaited<ReturnType<typeof getServiceSupabase>>;
type Guard = { ok: true } | { ok: false; error: string; status: number };

/** Lançado quando não é possível resolver a identidade do usuário logado. */
export class PipelineAccessError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PipelineAccessError";
  }
}

/** Resolve o usuário logado a partir dos cookies (fail-closed). */
export async function getCurrentUser(): Promise<CurrentUser> {
  try {
    const userClient = await createServerClient();
    const { data, error } = await userClient.auth.getUser();
    if (error) throw error;
    const userId = data.user?.id;
    if (!userId) throw new Error("no authenticated user");
    return { userId, role: data.user?.app_metadata?.role as string | undefined };
  } catch (err) {
    throw new PipelineAccessError(
      `auth check failed: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
}

async function assertWith(
  supabase: ServiceSupabase,
  pipelineId: string,
  predicate: (u: CurrentUser, p: PipelineOwnership) => boolean,
): Promise<Guard> {
  let user: CurrentUser;
  try {
    user = await getCurrentUser();
  } catch {
    return { ok: false, error: "Não autenticado", status: 401 };
  }
  const { data, error } = await supabase
    .from("pipelines")
    .select("owner_user_id, is_universal")
    .eq("id", pipelineId)
    .maybeSingle();
  if (error) return { ok: false, error: error.message, status: 500 };
  if (!data) return { ok: false, error: "Funil não encontrado.", status: 404 };
  if (!predicate(user, data as PipelineOwnership)) {
    return { ok: false, error: "Permissão insuficiente para este funil.", status: 403 };
  }
  return { ok: true };
}

/** Guarda para gestão de estrutura (renomear, stages, excluir, trocar dono). */
export function assertCanManagePipeline(supabase: ServiceSupabase, pipelineId: string) {
  return assertWith(supabase, pipelineId, canManagePipeline);
}

/** Guarda para escrita de deals no funil. */
export function assertCanWriteDealsInPipeline(supabase: ServiceSupabase, pipelineId: string) {
  return assertWith(supabase, pipelineId, canWriteDealsInPipeline);
}

/**
 * IDs de funis que o usuário pode ver. null = admin (sem restrição).
 * Vendedor → próprios + universais. Lança PipelineAccessError se auth falhar.
 */
export async function getAllowedPipelineIds(
  supabase: ServiceSupabase,
): Promise<string[] | null> {
  const { userId, role } = await getCurrentUser();
  if (role === "admin") return null;
  const { data, error } = await supabase
    .from("pipelines")
    .select("id")
    .or(`owner_user_id.eq.${userId},is_universal.eq.true`);
  if (error) throw new PipelineAccessError(`failed to load pipelines: ${error.message}`);
  return (data || []).map((p: { id: string }) => p.id);
}
```

> Nota: o `import` no meio do arquivo é válido em ES modules (hoisted), mas mova-o para o topo do arquivo junto aos demais imports ao colar, para seguir o lint. Os predicados puros não importam nada — continuam testáveis isoladamente.

- [ ] **Step 2: Type-check e lint**

Run: `npm --prefix frontend run type-check`
Expected: PASS
Run: `npm --prefix frontend run lint`
Expected: PASS (imports no topo do arquivo)

- [ ] **Step 3: Rodar os testes puros (garantir que não quebraram)**

Run: `npm --prefix frontend run test -- src/lib/supabase/pipeline-access.test.ts`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/supabase/pipeline-access.ts
git commit -m "feat(funis): guardas de IO e getAllowedPipelineIds em pipeline-access"
```

---

## Task 5: /api/users — incluir role no retorno

**Files:**
- Modify: `frontend/src/app/api/users/route.ts:8-14`

- [ ] **Step 1: Adicionar `role` ao map**

Substituir o `return NextResponse.json(...)` por:

```ts
  return NextResponse.json(
    users.map((u) => ({
      id: u.id,
      email: u.email ?? "",
      name: (u.user_metadata?.full_name as string | undefined) ?? u.email ?? "",
      role: (u.app_metadata?.role as string | undefined) ?? "vendedor",
    }))
  );
```

- [ ] **Step 2: Type-check**

Run: `npm --prefix frontend run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/users/route.ts
git commit -m "feat(funis): /api/users devolve role (para o seletor de dono)"
```

---

## Task 6: /api/pipelines — POST resolve dono; GET escopa

**Files:**
- Modify: `frontend/src/app/api/pipelines/route.ts`

- [ ] **Step 1: Atualizar imports**

No topo, somar ao import existente:

```ts
import {
  getCurrentUser,
  resolvePipelineOwnerOnCreate,
  getAllowedPipelineIds,
} from "@/lib/supabase/pipeline-access";
```

- [ ] **Step 2: Escopar o GET**

Substituir a função `GET` inteira por:

```ts
export async function GET() {
  const supabase = await getServiceSupabase();
  let allowed: string[] | null;
  try {
    allowed = await getAllowedPipelineIds(supabase);
  } catch {
    return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
  }
  let query = supabase.from("pipelines").select("*").order("order_index", { ascending: true });
  if (allowed !== null) query = query.in("id", allowed.length ? allowed : ["00000000-0000-0000-0000-000000000000"]);
  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}
```

- [ ] **Step 3: Resolver o dono no POST**

Substituir a primeira metade da função `POST` (até a criação do pipeline) por:

```ts
export async function POST(request: NextRequest) {
  const { name, owner_user_id } = await request.json();
  if (!name?.trim()) return NextResponse.json({ error: "Nome é obrigatório" }, { status: 400 });

  let user;
  try {
    user = await getCurrentUser();
  } catch {
    return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
  }
  const ownerToSet = resolvePipelineOwnerOnCreate(user, owner_user_id ?? null);

  const supabase = await getServiceSupabase();

  const { data: pipeline, error: pipelineError } = await supabase
    .from("pipelines")
    .insert({ name: name.trim(), owner_user_id: ownerToSet })
    .select()
    .single();
  if (pipelineError) return NextResponse.json({ error: pipelineError.message }, { status: 500 });
```

(A parte de criação dos `DEFAULT_STAGES` e o `return` permanecem iguais.)

- [ ] **Step 4: Type-check e lint**

Run: `npm --prefix frontend run type-check`
Expected: PASS
Run: `npm --prefix frontend run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/pipelines/route.ts
git commit -m "feat(funis): POST /api/pipelines define dono; GET escopa por usuário"
```

---

## Task 7: /api/pipelines/[id] — guarda + troca de dono (admin)

**Files:**
- Modify: `frontend/src/app/api/pipelines/[id]/route.ts`

- [ ] **Step 1: Imports**

No topo, somar:

```ts
import { assertCanManagePipeline } from "@/lib/supabase/pipeline-access";
import { requireAdmin } from "@/lib/admin-auth";
```

- [ ] **Step 2: Reescrever o PATCH (guarda + permitir trocar dono/universal só admin)**

Substituir a função `PATCH` inteira por:

```ts
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const guard = await assertCanManagePipeline(supabase, id);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const updates: Record<string, unknown> = { updated_at: new Date().toISOString() };

  if (body.name !== undefined) {
    if (!body.name?.trim()) return NextResponse.json({ error: "Nome é obrigatório" }, { status: 400 });
    updates.name = body.name.trim();
  }

  // Trocar dono / marcar universal: só admin
  if (body.owner_user_id !== undefined || body.is_universal !== undefined) {
    const admin = await requireAdmin();
    if (!admin.ok) return NextResponse.json({ error: admin.error }, { status: admin.status });
    if (body.owner_user_id !== undefined) updates.owner_user_id = body.owner_user_id; // string | null
    if (body.is_universal !== undefined) updates.is_universal = !!body.is_universal;
  }

  const { data, error } = await supabase
    .from("pipelines")
    .update(updates)
    .eq("id", id)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}
```

- [ ] **Step 3: Adicionar a guarda no DELETE**

Logo após `const supabase = await getServiceSupabase();` na função `DELETE`, inserir:

```ts
  const guard = await assertCanManagePipeline(supabase, id);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
```

(O resto do DELETE — checagem de último funil e de deals — permanece igual.)

- [ ] **Step 4: Type-check e lint**

Run: `npm --prefix frontend run type-check`
Expected: PASS
Run: `npm --prefix frontend run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/pipelines/[id]/route.ts
git commit -m "feat(funis): guarda de gestão em PATCH/DELETE de funil + troca de dono (admin)"
```

---

## Task 8: /api/pipelines/[id]/stages — guarda de gestão

**Files:**
- Modify: `frontend/src/app/api/pipelines/[id]/stages/route.ts` (POST)
- Modify: `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts` (PATCH, DELETE)

- [ ] **Step 1: Guarda no POST de stage**

Em `stages/route.ts`, somar ao import:

```ts
import { assertCanManagePipeline } from "@/lib/supabase/pipeline-access";
```

Na função `POST`, logo após `const supabase = await getServiceSupabase();`, inserir:

```ts
  const guard = await assertCanManagePipeline(supabase, id);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
```

- [ ] **Step 2: Guarda no PATCH e DELETE de stage**

Em `stages/[stageId]/route.ts`, somar ao import:

```ts
import { assertCanManagePipeline } from "@/lib/supabase/pipeline-access";
```

Em `PATCH`, logo após `const supabase = await getServiceSupabase();` (o `id` do funil já vem em `params`; desestruture-o):

```ts
  const { id, stageId } = await params;
  // ...
  const guard = await assertCanManagePipeline(supabase, id);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
```

Fazer o mesmo no `DELETE` (desestruturar `id` junto de `stageId` e inserir a mesma guarda após obter o `supabase`).

- [ ] **Step 3: Type-check e lint**

Run: `npm --prefix frontend run type-check`
Expected: PASS
Run: `npm --prefix frontend run lint`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/api/pipelines/[id]/stages/route.ts" "frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts"
git commit -m "feat(funis): guarda de gestão nas rotas de stages"
```

---

## Task 9: /api/deals — guarda de escrita de deals; GET escopa

**Files:**
- Modify: `frontend/src/app/api/deals/route.ts` (POST, GET)
- Modify: `frontend/src/app/api/deals/[id]/route.ts` (PATCH, DELETE)

- [ ] **Step 1: deals/route.ts — imports**

Somar ao import:

```ts
import { assertCanWriteDealsInPipeline, getAllowedPipelineIds } from "@/lib/supabase/pipeline-access";
```

- [ ] **Step 2: Escopar o GET de deals**

Na função `GET`, logo após `const supabase = await getServiceSupabase();`, inserir o escopo e aplicá-lo à query:

```ts
  let allowed: string[] | null;
  try {
    allowed = await getAllowedPipelineIds(supabase);
  } catch {
    return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
  }
```

E, após a linha `if (pipelineId) query = query.eq("pipeline_id", pipelineId);`, inserir:

```ts
  if (allowed !== null) query = query.in("pipeline_id", allowed.length ? allowed : ["00000000-0000-0000-0000-000000000000"]);
```

- [ ] **Step 3: Guarda no POST de deal**

Na função `POST`, logo após a validação `if (!body.lead_id || !body.title?.trim()) ...`, inserir:

```ts
  const guard = await assertCanWriteDealsInPipeline(supabase, body.pipeline_id);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
```

- [ ] **Step 4: deals/[id]/route.ts — imports e guarda no PATCH**

Somar ao import:

```ts
import { assertCanWriteDealsInPipeline } from "@/lib/supabase/pipeline-access";
```

No `PATCH`, trocar o fetch de `currentDeal` para incluir `pipeline_id` e adicionar as guardas. Substituir o bloco:

```ts
  const { data: currentDeal } = await supabase
    .from("deals")
    .select("stage_id, lead_id")
    .eq("id", id)
    .single();
  const oldStageId = currentDeal?.stage_id ?? null;
```

por:

```ts
  const { data: currentDeal } = await supabase
    .from("deals")
    .select("stage_id, lead_id, pipeline_id")
    .eq("id", id)
    .single();
  if (!currentDeal) return NextResponse.json({ error: "Deal não encontrado." }, { status: 404 });
  const oldStageId = currentDeal.stage_id ?? null;

  // Guarda: precisa poder escrever no funil de origem
  if (currentDeal.pipeline_id) {
    const guardSrc = await assertCanWriteDealsInPipeline(supabase, currentDeal.pipeline_id);
    if (!guardSrc.ok) return NextResponse.json({ error: guardSrc.error }, { status: guardSrc.status });
  }
  // Movimentação entre funis: precisa poder escrever também no destino
  if (body.pipeline_id && body.pipeline_id !== currentDeal.pipeline_id) {
    const guardDst = await assertCanWriteDealsInPipeline(supabase, body.pipeline_id);
    if (!guardDst.ok) return NextResponse.json({ error: guardDst.error }, { status: guardDst.status });
  }
```

(As referências a `currentDeal?.stage_id` / `currentDeal?.lead_id` mais abaixo continuam válidas.)

- [ ] **Step 5: Guarda no DELETE de deal**

Substituir a função `DELETE` inteira por:

```ts
export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data: deal } = await supabase
    .from("deals")
    .select("pipeline_id")
    .eq("id", id)
    .single();
  if (deal?.pipeline_id) {
    const guard = await assertCanWriteDealsInPipeline(supabase, deal.pipeline_id);
    if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  }

  const { error } = await supabase.from("deals").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 6: Type-check e lint**

Run: `npm --prefix frontend run type-check`
Expected: PASS
Run: `npm --prefix frontend run lint`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add "frontend/src/app/api/deals/route.ts" "frontend/src/app/api/deals/[id]/route.ts"
git commit -m "feat(funis): guarda de escrita de deals (origem/destino) + GET escopado"
```

---

## Task 10: Hook useCurrentRole

**Files:**
- Create: `frontend/src/hooks/use-current-role.ts`

- [ ] **Step 1: Criar o hook**

```ts
"use client";

import { useState, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";

/** Lê role e userId do usuário logado a partir da sessão (app_metadata.role). */
export function useCurrentRole() {
  const [state, setState] = useState<{
    role: "admin" | "vendedor";
    userId: string | null;
    loading: boolean;
  }>({ role: "vendedor", userId: null, loading: true });

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      const r = session?.user?.app_metadata?.role as "admin" | "vendedor" | undefined;
      setState({
        role: r === "admin" ? "admin" : "vendedor",
        userId: session?.user?.id ?? null,
        loading: false,
      });
    });
  }, []);

  return state;
}
```

- [ ] **Step 2: Type-check**

Run: `npm --prefix frontend run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/use-current-role.ts
git commit -m "feat(funis): hook useCurrentRole (role/userId no client)"
```

---

## Task 11: PipelineCreateModal — seletor de dono (admin) + fiação no vendas

**Files:**
- Modify: `frontend/src/components/deals/pipeline-create-modal.tsx`
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx`

- [ ] **Step 1: Reescrever o modal com seletor de dono (admin)**

Substituir o conteúdo de `pipeline-create-modal.tsx` por:

```tsx
"use client";

import { useState, useEffect } from "react";
import { useCurrentRole } from "@/hooks/use-current-role";

interface UserOption { id: string; name: string; role: string; }

interface PipelineCreateModalProps {
  onClose: () => void;
  onCreate: (name: string, ownerUserId: string | null) => Promise<void>;
}

export function PipelineCreateModal({ onClose, onCreate }: PipelineCreateModalProps) {
  const { role } = useCurrentRole();
  const isAdmin = role === "admin";
  const [name, setName] = useState("");
  const [ownerUserId, setOwnerUserId] = useState<string>(""); // "" = Administrativo (null)
  const [vendedores, setVendedores] = useState<UserOption[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin) return;
    fetch("/api/users")
      .then((r) => (r.ok ? r.json() : []))
      .then((list: UserOption[]) => setVendedores(list.filter((u) => u.role !== "admin")))
      .catch(() => setVendedores([]));
  }, [isAdmin]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onCreate(name.trim(), isAdmin ? (ownerUserId || null) : null);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao criar funil.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-sm p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-normal text-[#111111] mb-4" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>
          Novo Funil
        </h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome do Funil *</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex: Funil Atacado"
              autoFocus
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
            />
            <p className="text-[11px] text-[#7b7b78] mt-1.5">O funil será criado com os stages padrão (Novo, Contato, Proposta, Negociação, Fechado Ganho, Perdido).</p>
          </div>
          {isAdmin && (
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Dono</label>
              <select
                value={ownerUserId}
                onChange={(e) => setOwnerUserId(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              >
                <option value="">Administrativo (todos os admins)</option>
                {vendedores.map((u) => (
                  <option key={u.id} value={u.id}>{u.name}</option>
                ))}
              </select>
            </div>
          )}
          {error && (
            <div className="bg-[#fee2e2] border border-[#fca5a5] rounded-[6px] px-3 py-2 text-[13px] text-[#991b1b]">
              {error}
            </div>
          )}
          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={saving || !name.trim()} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Funil"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Atualizar `handleCreatePipeline` no vendas/page.tsx**

Substituir a função `handleCreatePipeline` por:

```tsx
  async function handleCreatePipeline(name: string, ownerUserId: string | null) {
    const res = await fetch("/api/pipelines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, owner_user_id: ownerUserId }),
    });
    if (!res.ok) {
      const { error } = await res.json().catch(() => ({}));
      throw new Error(error || "Erro ao criar funil.");
    }
    const pipeline = await res.json();
    await refetchPipelines();
    if (pipeline?.id) setSelectedPipelineId(pipeline.id);
  }
```

- [ ] **Step 3: Type-check e lint**

Run: `npm --prefix frontend run type-check`
Expected: PASS (a prop `onCreate` agora aceita `(name, ownerUserId)`)
Run: `npm --prefix frontend run lint`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/deals/pipeline-create-modal.tsx "frontend/src/app/(authenticated)/vendas/page.tsx"
git commit -m "feat(funis): seletor de dono no modal de criar funil (admin)"
```

---

## Task 12: PipelineEditModal — seletor de dono (admin) + fiação

**Files:**
- Modify: `frontend/src/components/deals/pipeline-edit-modal.tsx`
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx`

- [ ] **Step 1: Adicionar props de dono ao modal**

Em `pipeline-edit-modal.tsx`, somar imports:

```tsx
import { useEffect } from "react";
import { useCurrentRole } from "@/hooks/use-current-role";
```

(O arquivo já importa `useState` de "react"; ajuste para `import { useState, useEffect } from "react";`.)

Trocar a interface de props e a assinatura do componente:

```tsx
interface UserOption { id: string; name: string; role: string; }

interface PipelineEditModalProps {
  pipelineId: string;
  pipelineName: string;
  ownerUserId: string | null;
  isUniversal: boolean;
  stages: PipelineStage[];
  onClose: () => void;
  onSaved: () => void;
}

export function PipelineEditModal({
  pipelineId, pipelineName, ownerUserId: initialOwner, isUniversal, stages: initialStages, onClose, onSaved,
}: PipelineEditModalProps) {
  const { role } = useCurrentRole();
  const isAdmin = role === "admin";
  const [owner, setOwner] = useState<string>(initialOwner ?? ""); // "" = Administrativo (null)
  const [vendedores, setVendedores] = useState<UserOption[]>([]);
```

(Manter as demais declarações de estado já existentes: `stages`, `name`, `saving`, `error`, `sensors`.)

Adicionar o efeito de carregar vendedores logo após as declarações de estado:

```tsx
  useEffect(() => {
    if (!isAdmin) return;
    fetch("/api/users")
      .then((r) => (r.ok ? r.json() : []))
      .then((list: UserOption[]) => setVendedores(list.filter((u) => u.role !== "admin")))
      .catch(() => setVendedores([]));
  }, [isAdmin]);
```

- [ ] **Step 2: Persistir a troca de dono no `handleSave`**

Dentro de `handleSave`, logo após o bloco que faz PATCH de nome (antes do bloco dos `dirty` stages), inserir:

```tsx
      // Troca de dono (admin, funil não-universal)
      if (isAdmin && !isUniversal && (owner || null) !== (initialOwner ?? null)) {
        ops.push(
          fetch(`/api/pipelines/${pipelineId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ owner_user_id: owner || null }),
          }).then(async (r) => {
            if (!r.ok) {
              const d = await r.json().catch(() => ({}));
              throw new Error(d.error ?? "Erro ao trocar o dono do funil.");
            }
          })
        );
      }
```

- [ ] **Step 3: Renderizar o seletor de dono**

No JSX, logo após o `<div className="mb-4">...</div>` do campo "Nome do Funil", inserir:

```tsx
        {isAdmin && !isUniversal && (
          <div className="mb-4">
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Dono</label>
            <select
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
            >
              <option value="">Administrativo (todos os admins)</option>
              {vendedores.map((u) => (
                <option key={u.id} value={u.id}>{u.name}</option>
              ))}
            </select>
          </div>
        )}
        {isUniversal && (
          <div className="mb-4 text-[12px] text-[#7b7b78]">Funil universal (Blacklist) — visível a todos.</div>
        )}
```

- [ ] **Step 4: Passar as novas props no vendas/page.tsx**

Substituir o bloco `{showPipelineEdit && activePipeline && (...)}` por:

```tsx
      {showPipelineEdit && activePipeline && (
        <PipelineEditModal
          pipelineId={activePipeline.id}
          pipelineName={activePipeline.name}
          ownerUserId={activePipeline.owner_user_id}
          isUniversal={activePipeline.is_universal}
          stages={stages}
          onClose={() => setShowPipelineEdit(false)}
          onSaved={refetchStages}
        />
      )}
```

- [ ] **Step 5: Type-check e lint**

Run: `npm --prefix frontend run type-check`
Expected: PASS
Run: `npm --prefix frontend run lint`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/deals/pipeline-edit-modal.tsx "frontend/src/app/(authenticated)/vendas/page.tsx"
git commit -m "feat(funis): reatribuir dono no modal de editar funil (admin)"
```

---

## Task 13: PipelineSwitcher — rótulo de tipo/dono (admin)

**Files:**
- Modify: `frontend/src/components/deals/pipeline-switcher.tsx`
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx`

- [ ] **Step 1: Adicionar `isAdmin` e carregar nomes; renderizar rótulo**

Em `pipeline-switcher.tsx`, somar imports:

```tsx
import { useState, useRef, useEffect } from "react";
```

(Já existe; garantir `useEffect` incluído.) Trocar a interface de props e a assinatura para receber `isAdmin`:

```tsx
interface PipelineSwitcherProps {
  pipelines: Pipeline[];
  activePipelineId: string | null;
  isAdmin: boolean;
  onSelect: (id: string) => void;
  onCreateNew: () => void;
  onEdit: () => void;
  onDelete: (pipeline: Pipeline) => void;
}

export function PipelineSwitcher({
  pipelines, activePipelineId, isAdmin, onSelect, onCreateNew, onEdit, onDelete,
}: PipelineSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const dropdownRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const activePipeline = pipelines.find((p) => p.id === activePipelineId);

  useEffect(() => {
    if (!isAdmin) return;
    fetch("/api/users")
      .then((r) => (r.ok ? r.json() : []))
      .then((list: { id: string; name: string }[]) =>
        setNames(Object.fromEntries(list.map((u) => [u.id, u.name]))))
      .catch(() => setNames({}));
  }, [isAdmin]);

  function ownerLabel(p: Pipeline): string | null {
    if (!isAdmin) return null;
    if (p.is_universal) return "Universal";
    if (!p.owner_user_id) return "Administrativo";
    return names[p.owner_user_id] ?? "—";
  }
```

(Manter o `useEffect` de click-outside já existente.)

- [ ] **Step 2: Mostrar o rótulo em cada item do dropdown**

No `pipelines.map((p) => (...))`, trocar o conteúdo do botão para incluir o rótulo. Substituir `{p.name}` (a primeira ocorrência, dentro do botão de seleção) por:

```tsx
                  <span className="flex flex-col">
                    <span>{p.name}</span>
                    {ownerLabel(p) && (
                      <span className="text-[11px] text-[#7b7b78]">{ownerLabel(p)}</span>
                    )}
                  </span>
```

- [ ] **Step 3: Passar `isAdmin` no vendas/page.tsx**

No topo de `VendasPage`, somar:

```tsx
  const { role } = useCurrentRole();
  const isAdmin = role === "admin";
```

(E o import: `import { useCurrentRole } from "@/hooks/use-current-role";`.)

No `<PipelineSwitcher ... />`, somar a prop `isAdmin={isAdmin}`.

- [ ] **Step 4: Type-check e lint**

Run: `npm --prefix frontend run type-check`
Expected: PASS
Run: `npm --prefix frontend run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/deals/pipeline-switcher.tsx "frontend/src/app/(authenticated)/vendas/page.tsx"
git commit -m "feat(funis): rótulo de tipo/dono do funil no switcher (admin)"
```

---

## Task 14: Verificação final (suite + auditoria + checklist manual)

**Files:** nenhum (validação).

- [ ] **Step 1: Suite completa do front**

Run: `npm --prefix frontend run test`
Expected: PASS (inclui `pipeline-access.test.ts` e `import-deals.test.ts`).
Run: `npm --prefix frontend run type-check`
Expected: PASS
Run: `npm --prefix frontend run lint`
Expected: PASS

- [ ] **Step 2: Auditar outras leituras no browser de deals/pipelines**

Run: `git grep -n "from(\"deals\")\|from(\"pipelines\")\|from(\"pipeline_stages\")" -- frontend/src`
Confirmar que cada leitura feita pelo **client** (arquivos que importam `@/lib/supabase/client`) é compatível com o escopo por RLS (vendedor vê só os seus; admin vê tudo). Leituras conhecidas que devem escopar bem: `use-pipelines.ts`, `use-realtime-deals.ts`. Anotar qualquer tela (ex.: dashboard) que dependa de um vendedor ver tudo — se houver, ela passa a usar uma rota de API service-role específica de admin (fora do escopo desta entrega; registrar como follow-up).

- [ ] **Step 3: Checklist manual de RLS (após o usuário aplicar a Parte B no Supabase)**

Sem Postgres no CI — validar manualmente no ambiente com a migração aplicada:
- Login como **vendedor (João)** → no /vendas vê só os funis do João **+ Blacklist**; não vê funis administrativos nem de outro vendedor; realtime não traz deals de outros.
- Login como **admin** → vê todos os funis (pessoais, administrativos, universal) e o rótulo de dono no switcher.
- **Blacklist:** vendedor consegue mover cards (universal gravável por todos); vendedor **não** consegue Editar/Excluir o funil Blacklist (botões de gestão retornam 403).
- **Funil administrativo:** vendedor não enxerga; admin edita normalmente.
- **"Parar mensagens"** (chat) → continua movendo os deals do lead para a Blacklist (backend service role).
- Tentativa de escrita direta via client (anon key) em `pipelines`/`deals` → negada.

- [ ] **Step 4: Sem commit** (passo de validação). Relatar resultados ao usuário.

---

## Self-Review (preenchido)

- **Cobertura do spec:** modelo de dados (Task 1, 2), RLS (Task 1B), guarda de escrita com 2 predicados (Task 3, 4, 7, 8, 9), POST resolve dono (Task 6), GET escopado (Task 6, 9), `/api/users` role (Task 5), `useCurrentRole` (Task 10), seletor de dono criar/editar (Task 11, 12), rótulo no switcher (Task 13), migração/backfill (Task 1A), testes (Task 3, 14), auditoria e checklist (Task 14). ✔
- **Placeholders:** nenhum — todo passo tem código/comando reais.
- **Consistência de tipos/nomes:** `canWriteDealsInPipeline`, `canManagePipeline`, `resolvePipelineOwnerOnCreate`, `assertCanWriteDealsInPipeline`, `assertCanManagePipeline`, `getAllowedPipelineIds`, `getCurrentUser`, `useCurrentRole` usados de forma idêntica entre as tasks. `Pipeline.owner_user_id`/`is_universal` definidos na Task 2 e consumidos nas Tasks 11-13.

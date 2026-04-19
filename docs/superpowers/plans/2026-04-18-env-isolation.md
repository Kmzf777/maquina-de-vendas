# Isolamento de Ambientes Dev/Prod — Worker de Campanhas WhatsApp

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar coluna `env_tag` nas tabelas `broadcasts`, `cadences` e `cadence_enrollments` para que os workers de dev e prod nunca processem registros do ambiente errado, e o CRM de cada ambiente só exiba seus próprios registros.

**Architecture:** Coluna `env_tag TEXT NOT NULL DEFAULT 'production'` nas três tabelas. O frontend injeta o `env_tag` correto em todos os inserts (baseado em `NODE_ENV`). Os workers filtram as queries por `env_tag` (baseado em `IS_DEV_ENV`). A service layer valida parent-child ao criar enrollments.

**Tech Stack:** Supabase (MCP), Next.js App Router Route Handlers (TypeScript), FastAPI/Python (Pydantic Settings)

---

## Mapa de Arquivos

| Arquivo | Acção |
|---|---|
| Supabase MCP | Aplicar 3 migrations |
| `frontend/src/lib/env.ts` | **Criar** — exporta `APP_ENV` |
| `frontend/src/app/api/broadcasts/route.ts` | **Modificar** — GET filter + POST env_tag |
| `frontend/src/app/api/cadences/route.ts` | **Modificar** — GET filter + POST env_tag |
| `frontend/src/app/api/cadences/[id]/enrollments/route.ts` | **Modificar** — POST env_tag + validação parent |
| `backend/app/broadcast/worker.py` | **Modificar** — `_ENV_TAG` + filter em `process_broadcasts()` |
| `backend/app/cadence/service.py` | **Modificar** — `_ENV_TAG` + env_tag em `create_enrollment()` + filter em 3 queries de leitura |

---

## Task 1: Migrations no Supabase

**Files:**
- Supabase MCP (`mcp__supabase__apply_migration`)

- [ ] **Step 1: Aplicar migration na tabela `broadcasts`**

Usar MCP `apply_migration` com SQL:
```sql
ALTER TABLE broadcasts ADD COLUMN env_tag TEXT NOT NULL DEFAULT 'production';
```

- [ ] **Step 2: Aplicar migration na tabela `cadences`**

```sql
ALTER TABLE cadences ADD COLUMN env_tag TEXT NOT NULL DEFAULT 'production';
```

- [ ] **Step 3: Aplicar migration na tabela `cadence_enrollments`**

```sql
ALTER TABLE cadence_enrollments ADD COLUMN env_tag TEXT NOT NULL DEFAULT 'production';
```

- [ ] **Step 4: Verificar que as colunas existem**

Usar MCP `execute_sql`:
```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name IN ('broadcasts', 'cadences', 'cadence_enrollments')
  AND column_name = 'env_tag';
```

Esperado: 3 linhas, cada uma com `data_type = text` e `column_default = 'production'`.

---

## Task 2: Constante `APP_ENV` no Frontend

**Files:**
- Criar: `frontend/src/lib/env.ts`

- [ ] **Step 1: Criar o ficheiro**

```ts
export const APP_ENV = process.env.NODE_ENV === 'development' ? 'dev' : 'production';
```

- [ ] **Step 2: Verificar que o valor é correcto em dev**

Com o servidor dev a correr (`npm run dev`), abrir qualquer route handler no browser e confirmar que `APP_ENV` resolve para `'dev'`. (Verificar via log temporário ou inspecção do Next.js.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/env.ts
git commit -m "feat(env): constante APP_ENV baseada em NODE_ENV"
```

---

## Task 3: Route Handler de Broadcasts — GET filter + POST env_tag

**Files:**
- Modificar: `frontend/src/app/api/broadcasts/route.ts`

Estado actual do ficheiro:

```ts
export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("broadcasts")
    .select("*, cadences(id, name)")
    .order("created_at", { ascending: false });
  ...
}

export async function POST(request: NextRequest) {
  ...
  const { data, error } = await supabase
    .from("broadcasts")
    .insert({
      name: body.name,
      channel_id: body.channel_id || null,
      ...
      status: body.scheduled_at ? "scheduled" : "draft",
    })
  ...
}
```

- [ ] **Step 1: Aplicar as alterações**

Substituir o ficheiro completo por:

```ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("broadcasts")
    .select("*, cadences(id, name)")
    .eq("env_tag", APP_ENV)
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("broadcasts")
    .insert({
      name: body.name,
      channel_id: body.channel_id || null,
      template_name: body.template_name,
      template_preset_id: body.template_preset_id || null,
      template_variables: body.template_variables || {},
      send_interval_min: body.send_interval_min || 3,
      send_interval_max: body.send_interval_max || 8,
      cadence_id: body.cadence_id || null,
      agent_profile_id: body.agent_profile_id || null,
      scheduled_at: body.scheduled_at || null,
      status: body.scheduled_at ? "scheduled" : "draft",
      env_tag: APP_ENV,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Verificar — criar um broadcast em dev e confirmar `env_tag='dev'` no Supabase**

Via MCP `execute_sql`:
```sql
SELECT id, name, env_tag FROM broadcasts ORDER BY created_at DESC LIMIT 3;
```

Esperado: broadcast criado em dev tem `env_tag = 'dev'`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/broadcasts/route.ts
git commit -m "feat(broadcasts): env_tag no insert e filtro GET por ambiente"
```

---

## Task 4: Route Handler de Cadências — GET filter + POST env_tag

**Files:**
- Modificar: `frontend/src/app/api/cadences/route.ts`

Estado actual:

```ts
export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("cadences")
    .select("*")
    .order("created_at", { ascending: false });
  ...
}

export async function POST(request: NextRequest) {
  ...
  const { data, error } = await supabase
    .from("cadences")
    .insert({
      name: body.name,
      description: body.description || null,
      target_type: body.target_type || "manual",
      ...
    })
  ...
}
```

- [ ] **Step 1: Aplicar as alterações**

```ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("cadences")
    .select("*")
    .eq("env_tag", APP_ENV)
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadences")
    .insert({
      name: body.name,
      description: body.description || null,
      target_type: body.target_type || "manual",
      target_stage: body.target_stage || null,
      stagnation_days: body.stagnation_days || null,
      send_start_hour: body.send_start_hour ?? 7,
      send_end_hour: body.send_end_hour ?? 18,
      cooldown_hours: body.cooldown_hours ?? 48,
      max_messages: body.max_messages ?? 5,
      env_tag: APP_ENV,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Verificar — listar cadências no CRM dev e confirmar que apenas as de dev aparecem**

Via MCP `execute_sql`:
```sql
SELECT id, name, env_tag FROM cadences ORDER BY created_at DESC LIMIT 5;
```

Cadências criadas em dev devem ter `env_tag = 'dev'`. Cadências existentes (antes da migration) têm `env_tag = 'production'` e NÃO devem aparecer no CRM dev.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/cadences/route.ts
git commit -m "feat(cadences): env_tag no insert e filtro GET por ambiente"
```

---

## Task 5: Route Handler de Enrollments — env_tag + validação parent

**Files:**
- Modificar: `frontend/src/app/api/cadences/[id]/enrollments/route.ts`

Estado actual do POST (linhas 25-48):

```ts
export async function POST(request, { params }) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadence_enrollments")
    .insert({
      cadence_id: id,
      lead_id: body.lead_id,
      deal_id: body.deal_id || null,
      status: "active",
      current_step: 0,
      total_messages_sent: 0,
    })
    ...
}
```

- [ ] **Step 1: Aplicar as alterações**

```ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const status = request.nextUrl.searchParams.get("status");
  const supabase = await getServiceSupabase();

  let query = supabase
    .from("cadence_enrollments")
    .select("*, leads!inner(id, name, phone, company, stage)")
    .eq("cadence_id", id)
    .order("enrolled_at", { ascending: false });

  if (status) query = query.eq("status", status);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data: cadence } = await supabase
    .from("cadences")
    .select("env_tag")
    .eq("id", id)
    .single();

  if (cadence?.env_tag !== APP_ENV) {
    return NextResponse.json(
      { error: "Cadência pertence a outro ambiente" },
      { status: 403 }
    );
  }

  const { data, error } = await supabase
    .from("cadence_enrollments")
    .insert({
      cadence_id: id,
      lead_id: body.lead_id,
      deal_id: body.deal_id || null,
      status: "active",
      current_step: 0,
      total_messages_sent: 0,
      env_tag: APP_ENV,
    })
    .select("*, leads!inner(id, name, phone, company, stage)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Verificar — tentar inscrever lead em cadência de prod a partir do CRM dev**

Esperado: resposta `403 Cadência pertence a outro ambiente`.

- [ ] **Step 3: Verificar — inscrever lead em cadência de dev**

Esperado: sucesso. Confirmar via MCP:
```sql
SELECT id, cadence_id, lead_id, env_tag FROM cadence_enrollments ORDER BY enrolled_at DESC LIMIT 3;
```

Enrollment criado em dev deve ter `env_tag = 'dev'`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/api/cadences/[id]/enrollments/route.ts
git commit -m "feat(enrollments): env_tag no insert e validação de ambiente do parent"
```

---

## Task 6: Backend — `_ENV_TAG` e filtro em `broadcast/worker.py`

**Files:**
- Modificar: `backend/app/broadcast/worker.py`

A função `process_broadcasts()` actualmente (linhas 76-88):

```python
async def process_broadcasts():
    sb = get_supabase()
    broadcasts = (
        sb.table("broadcasts")
        .select("*")
        .eq("status", "running")
        .execute()
        .data
    )
```

- [ ] **Step 1: Adicionar a constante `_ENV_TAG` no topo do módulo e filtrar a query**

Após os imports existentes, adicionar:

```python
import os
_ENV_TAG = "dev" if os.environ.get("IS_DEV_ENV") == "true" else "production"
```

Substituir a query em `process_broadcasts()`:

```python
async def process_broadcasts():
    sb = get_supabase()
    broadcasts = (
        sb.table("broadcasts")
        .select("*")
        .eq("status", "running")
        .eq("env_tag", _ENV_TAG)
        .execute()
        .data
    )
```

- [ ] **Step 2: Verificar — iniciar o backend dev com `IS_DEV_ENV=true` e confirmar nos logs**

Iniciar via VS Code task "Start Backend". Criar um broadcast em dev e colocá-lo a `running`. Nos logs do backend, confirmar que o worker o processa. Criar um broadcast com `env_tag='production'` directamente no Supabase e confirmar que o worker dev o **ignora**.

- [ ] **Step 3: Commit**

```bash
git add backend/app/broadcast/worker.py
git commit -m "feat(worker): filtrar broadcasts por env_tag para isolar dev/prod"
```

---

## Task 7: Backend — `_ENV_TAG` e filtros em `cadence/service.py`

**Files:**
- Modificar: `backend/app/cadence/service.py`

Mudanças em quatro funções: `create_enrollment`, `get_due_enrollments`, `get_reengagement_enrollments`, `get_stagnation_cadences`.

- [ ] **Step 1: Adicionar a constante `_ENV_TAG` no topo do módulo**

Após os imports existentes:

```python
import os
_ENV_TAG = "dev" if os.environ.get("IS_DEV_ENV") == "true" else "production"
```

- [ ] **Step 2: Adicionar validação parent-child e env_tag ao insert em `create_enrollment`**

Substituir a função completa:

```python
def create_enrollment(
    cadence_id: str,
    lead_id: str,
    deal_id: str | None = None,
    broadcast_id: str | None = None,
    next_send_at: datetime | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    cadence = sb.table("cadences").select("env_tag").eq("id", cadence_id).single().execute().data
    if cadence and cadence.get("env_tag") != _ENV_TAG:
        raise ValueError(
            f"env_tag mismatch: cadence='{cadence.get('env_tag')}', current env='{_ENV_TAG}'"
        )
    data = {
        "cadence_id": cadence_id,
        "lead_id": lead_id,
        "status": "active",
        "current_step": 0,
        "total_messages_sent": 0,
        "next_send_at": next_send_at.isoformat() if next_send_at else None,
        "env_tag": _ENV_TAG,
    }
    if deal_id:
        data["deal_id"] = deal_id
    if broadcast_id:
        data["broadcast_id"] = broadcast_id
    result = sb.table("cadence_enrollments").insert(data).execute()
    return result.data[0]
```

- [ ] **Step 3: Filtrar `get_due_enrollments` por `env_tag`**

Substituir a função (linhas 134-144):

```python
def get_due_enrollments(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("*, leads!inner(phone, stage, human_control, name, company), cadences!inner(id, name, send_start_hour, send_end_hour, max_messages, status)")
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .lte("next_send_at", now.isoformat())
        .limit(limit)
        .execute()
    )
    return result.data
```

- [ ] **Step 4: Filtrar `get_reengagement_enrollments` por `env_tag`**

Substituir a função (linhas 147-157):

```python
def get_reengagement_enrollments(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("*, leads!inner(phone, last_msg_at, human_control), cadences!inner(id, cooldown_hours, status)")
        .eq("status", "responded")
        .eq("env_tag", _ENV_TAG)
        .lte("responded_at", now.isoformat())
        .limit(limit)
        .execute()
    )
    return result.data
```

- [ ] **Step 5: Filtrar `get_stagnation_cadences` por `env_tag`**

Substituir a função (linhas 160-170):

```python
def get_stagnation_cadences() -> list[dict[str, Any]]:
    """Get active cadences that have stagnation triggers configured."""
    sb = get_supabase()
    result = (
        sb.table("cadences")
        .select("*")
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .not_.is_("stagnation_days", "null")
        .execute()
    )
    return result.data
```

- [ ] **Step 6: Reiniciar o backend dev e verificar nos logs**

Reiniciar via VS Code task. Nos logs, confirmar que:
- Cadências com `env_tag='dev'` são processadas pelo worker dev
- Nenhum erro de `env_tag mismatch` aparece para enrollments legítimos de dev

- [ ] **Step 7: Commit**

```bash
git add backend/app/cadence/service.py
git commit -m "feat(cadence-service): env_tag em create_enrollment e filtros de leitura por ambiente"
```

---

## Verificação Final de Isolamento

- [ ] **Confirmar que broadcasts de prod são ignorados pelo worker dev**

Via MCP, criar broadcast com `env_tag='production'` e status `running`:
```sql
UPDATE broadcasts SET status = 'running' WHERE env_tag = 'production' LIMIT 1;
```

Observar logs do backend dev: nenhuma tentativa de processar esse broadcast.

- [ ] **Confirmar que broadcasts de dev são ignorados pelo worker prod**

Verificar em prod (logs do Docker Swarm) que nenhum broadcast com `env_tag='dev'` é processado. (Ou verificar via Supabase que registros dev permanecem `status='running'` após o worker prod passar.)

- [ ] **Confirmar isolamento do CRM**

Abrir o CRM dev: apenas cadências/broadcasts com `env_tag='dev'` aparecem.  
Abrir o CRM prod: apenas cadências/broadcasts com `env_tag='production'` aparecem.

- [ ] **Commit de fechamento**

```bash
git log --oneline -6
```

Confirmar que os 6 commits da feature estão presentes antes de fazer merge para master.

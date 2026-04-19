# Design: Isolamento de Ambientes Dev/Prod — Worker de Campanhas WhatsApp

**Data:** 2026-04-18  
**Status:** Aprovado (v2 — revisado após code review)  
**Escopo:** Broadcasts, Cadências, Re-engajamentos, UI do CRM

---

## Problema

O banco de dados Supabase é compartilhado entre dev e prod (comportamento esperado e aceito). O worker do backend (broadcasts, cadências, re-engajamentos) faz polling no Supabase. Como ambos os backends (dev local + prod no Docker Swarm) fazem polling na mesma base, um registro criado em dev com `status="running"` é processado por **ambos** os workers, causando envios duplicados de mensagens WhatsApp reais a partir de testes locais.

---

## Fluxo de Inbound (Webhooks) — Sem Mudança

O dev router existente em `backend/app/webhook/meta_router.py` já previne duplo processamento de inbound via `continue`:

```python
dev_url = await get_dev_route(redis, msg.from_number)
if dev_url:
    background_tasks.add_task(forward_to_dev, ...)
    continue  # prod NÃO processa — mensagem vai apenas para dev
await push_to_buffer(redis, msg)
```

Adicionalmente, `get_dev_route()` só retorna URL para telefones explicitamente registados na whitelist (`dev:phone_routes` no Redis). Não há colisão de IA no inbound. **Este fluxo não é alterado.**

---

## Solução: Coluna `env_tag` com Isolamento em Todas as Camadas

A solução actua em quatro camadas:
1. **Schema** — coluna `env_tag` nas tabelas afectadas
2. **UI (Frontend)** — listas filtradas por `env_tag` + validação ao criar
3. **Backend Worker** — queries filtradas por `env_tag`
4. **Service Layer** — validação parent-child de `env_tag`

---

## Fluxo após a correção

```
[Frontend dev] npm run dev (NODE_ENV=development, APP_ENV='dev')
      │
      ├─► GET /api/cadences  → filtra env_tag='dev'  → só mostra cadências dev
      │
      └─► POST /api/broadcasts → insere env_tag='dev' → Supabase
                │
                ├─► [Worker DEV local]   filtra env_tag='dev'  → processa ✓
                │         └─► Meta Cloud API (graph.facebook.com) → WhatsApp ✓
                │
                └─► [Worker PROD Swarm]  filtra env_tag='production' → ignora ✓

[Frontend prod] NODE_ENV=production, APP_ENV='production'
      │
      └─► GET /api/cadences  → filtra env_tag='production' → não vê cadências dev ✓
```

---

## Regras de ambiente

| Ambiente | `NODE_ENV` (Next.js) | `IS_DEV_ENV` (Backend) | `env_tag` gravado |
|---|---|---|---|
| Dev local | `development` | `true` | `'dev'` |
| Prod (Docker Swarm) | `production` | não definido | `'production'` |

---

## Escopo de mudanças

### 1. Supabase — Migrations (via MCP)

Três migrations independentes. O `DEFAULT 'production'` garante que registros existentes continuem a ser processados pelo worker de prod sem quebra retroativa.

```sql
-- Migration 1
ALTER TABLE broadcasts ADD COLUMN env_tag TEXT NOT NULL DEFAULT 'production';

-- Migration 2
ALTER TABLE cadences ADD COLUMN env_tag TEXT NOT NULL DEFAULT 'production';

-- Migration 3
ALTER TABLE cadence_enrollments ADD COLUMN env_tag TEXT NOT NULL DEFAULT 'production';
```

**Risco operacional (inserts manuais):** Qualquer insert manual via SQL Editor do Supabase sem `env_tag` explícito receberá `'production'` e será processado pelo worker de prod. Regra de operação: inserts manuais em tabelas afectadas DEVEM especificar `env_tag` explicitamente. Todos os caminhos automatizados (route handlers + serviços) são cobertos pelas camadas 2 e 3.

---

### 2. Frontend — Next.js

**Arquivo novo:** `frontend/src/lib/env.ts`

```ts
export const APP_ENV = process.env.NODE_ENV === 'development' ? 'dev' : 'production';
```

#### 2a. Route handlers de escrita (INSERT) — injectam `env_tag`

| Arquivo | Tabela | Mudança |
|---|---|---|
| `src/app/api/broadcasts/route.ts` | `broadcasts` | adicionar `env_tag: APP_ENV` no insert |
| `src/app/api/cadences/route.ts` | `cadences` | adicionar `env_tag: APP_ENV` no insert |
| `src/app/api/cadences/[id]/enrollments/route.ts` | `cadence_enrollments` | adicionar `env_tag: APP_ENV` no insert + validação parent (ver 2b) |

#### 2b. Validação parent-child no enrollment (frontend)

Antes de inserir um `cadence_enrollment`, o route handler valida que a cadência pai tem o mesmo `env_tag`:

```ts
// src/app/api/cadences/[id]/enrollments/route.ts — POST handler
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
```

#### 2c. Route handlers de leitura (SELECT) — filtram por `env_tag`

Para prevenir que utilizadores do CRM de prod vejam e interajam com registros de dev (e vice-versa):

| Arquivo | Tabela | Mudança |
|---|---|---|
| `src/app/api/cadences/route.ts` | `cadences` | adicionar `.eq("env_tag", APP_ENV)` na query GET |
| `src/app/api/broadcasts/route.ts` | `broadcasts` | adicionar `.eq("env_tag", APP_ENV)` na query GET |

---

### 3. Backend Worker — FastAPI

**Constante partilhada** (adicionada nos dois módulos afectados):

```python
import os
_ENV_TAG = "dev" if os.environ.get("IS_DEV_ENV") == "true" else "production"
```

#### 3a. `backend/app/broadcast/worker.py`

Query em `process_broadcasts()`:

```python
sb.table("broadcasts")
  .select("*")
  .eq("status", "running")
  .eq("env_tag", _ENV_TAG)
```

#### 3b. `backend/app/cadence/scheduler.py`

Mesma constante `_ENV_TAG`. Filtrar `env_tag` nas queries das funções:

| Função | Tabela filtrada |
|---|---|
| `process_due_cadences()` | `cadence_enrollments` |
| `process_reengagements()` | `cadence_enrollments` |
| `process_stagnation_triggers()` | `cadences` |

---

### 4. Service Layer — Validação parent-child

**`backend/app/cadence/service.py` — `create_enrollment()`**

Antes de inserir, valida que a cadência pai tem o mesmo `env_tag` que o ambiente actual:

```python
def create_enrollment(cadence_id, lead_id, broadcast_id=None, next_send_at=None):
    sb = get_supabase()
    cadence = sb.table("cadences").select("env_tag").eq("id", cadence_id).single().execute().data
    if cadence and cadence.get("env_tag") != _ENV_TAG:
        raise ValueError(
            f"env_tag mismatch: cadence='{cadence.get('env_tag')}', current env='{_ENV_TAG}'"
        )
    sb.table("cadence_enrollments").insert({
        "cadence_id": cadence_id,
        "lead_id": lead_id,
        "broadcast_id": broadcast_id,
        "next_send_at": next_send_at,
        "env_tag": _ENV_TAG,
    }).execute()
```

---

## O que NÃO muda

- Dev router (`meta_router.py`, `dev_router/`) — inbound já isolado via `continue`
- `meta.py` e chamadas ao Graph API da Meta (`https://graph.facebook.com`)
- Variáveis de ambiente existentes (`IS_DEV_ENV` já existe em `backend/.env.local`)
- GitHub Actions / deploy pipeline
- Qualquer outra tabela do Supabase

---

## Invariantes do sistema

| Invariante | Mecanismo |
|---|---|
| Worker de prod não processa registros dev | Filtro `env_tag` nas queries do worker |
| Worker de dev não processa registros prod | Filtro `env_tag` nas queries do worker |
| Utilizadores de prod não veem cadências/broadcasts dev | Filtro `env_tag` nas queries GET do frontend |
| Enrollment não pode referenciar cadência de outro env | Validação no route handler + service layer |
| Registros existentes continuam em prod | `DEFAULT 'production'` retroactivo |
| Inbound não tem duplo processamento | `continue` existente no `meta_router.py` |
| Meta webhook sempre aponta para prod | Dev router existente — sem alteração |

# Design: Isolamento de Ambientes Dev/Prod — Worker de Campanhas WhatsApp

**Data:** 2026-04-18  
**Status:** Aprovado  
**Escopo:** Broadcasts, Cadências, Re-engajamentos

---

## Problema

O banco de dados Supabase é compartilhado entre dev e prod (comportamento esperado e aceito). O worker do backend (broadcasts, cadências, re-engajamentos) faz polling no Supabase. Como ambos os backends (dev local + prod no Docker Swarm) fazem polling na mesma base, um registro criado em dev com `status="running"` é processado por **ambos** os workers, causando envios duplicados de mensagens WhatsApp reais a partir de testes locais.

---

## Solução: Coluna `env_tag` nas tabelas afetadas

Adicionar a coluna `env_tag TEXT NOT NULL DEFAULT 'production'` nas tabelas que alimentam o worker. Cada backend filtra apenas os registros do seu próprio ambiente.

O `DEFAULT 'production'` garante retrocompatibilidade: registros existentes continuam sendo processados pelo worker de produção sem nenhum backfill.

---

## Fluxo após a correção

```
[Frontend dev] npm run dev (NODE_ENV=development)
      │
      ▼
[Next.js Route Handler] insere broadcast com env_tag='dev' → Supabase
      │
      ├─► [Worker DEV local]  filtra env_tag='dev'  → processa ✓
      │         │
      │         └─► Meta Cloud API (graph.facebook.com) → WhatsApp ✓
      │
      └─► [Worker PROD Swarm] filtra env_tag='production' → ignora ✓
```

---

## Regras de ambiente

| Ambiente | `NODE_ENV` (Next.js) | `IS_DEV_ENV` (Backend) | `env_tag` gravado |
|---|---|---|---|
| Dev local | `development` | `true` | `'dev'` |
| Prod (Docker Swarm) | `production` | não definido | `'production'` |

---

## Invariantes preservados

- Registros sem `env_tag` (criados antes da migration) → `DEFAULT 'production'`, processados pelo worker de prod sem quebra
- O CRM exibe todos os registros independentemente do `env_tag` (sem filtro de UI)
- Nenhuma variável de ambiente nova é necessária (`IS_DEV_ENV` já existe em `backend/.env.local`)
- O webhook da Meta sempre aponta para `https://api.canastrainteligencia.com/webhook/meta` (prod); o dev router e o `meta.py` permanecem inalterados

---

## Escopo de mudanças

### 1. Supabase — Migrations (via MCP)

Três migrations independentes:

```sql
-- broadcasts
ALTER TABLE broadcasts ADD COLUMN env_tag TEXT NOT NULL DEFAULT 'production';

-- cadences
ALTER TABLE cadences ADD COLUMN env_tag TEXT NOT NULL DEFAULT 'production';

-- cadence_enrollments
ALTER TABLE cadence_enrollments ADD COLUMN env_tag TEXT NOT NULL DEFAULT 'production';
```

### 2. Frontend — Next.js

**Arquivo novo:** `frontend/src/lib/env.ts`

```ts
export const APP_ENV = process.env.NODE_ENV === 'development' ? 'dev' : 'production';
```

**Route handlers alterados** (apenas inserts):

| Arquivo | Tabela | Mudança |
|---|---|---|
| `src/app/api/broadcasts/route.ts` | `broadcasts` | adicionar `env_tag: APP_ENV` no insert |
| `src/app/api/cadences/route.ts` | `cadences` | adicionar `env_tag: APP_ENV` no insert |

### 3. Backend — FastAPI

**`backend/app/broadcast/worker.py`**

Adicionar constante no topo do módulo:

```python
import os
_ENV_TAG = "dev" if os.environ.get("IS_DEV_ENV") == "true" else "production"
```

Alterar query em `process_broadcasts()`:

```python
sb.table("broadcasts")
  .select("*")
  .eq("status", "running")
  .eq("env_tag", _ENV_TAG)
```

**`backend/app/cadence/scheduler.py`**

Mesma constante `_ENV_TAG`. Filtrar `env_tag` nas queries das funções:
- `process_due_cadences()` — query em `cadence_enrollments`
- `process_reengagements()` — query em `cadence_enrollments`
- `process_stagnation_triggers()` — query em `cadences`

**`backend/app/cadence/service.py`**

Função `create_enrollment()`: adicionar `env_tag: _ENV_TAG` no insert de `cadence_enrollments`.

---

## O que NÃO muda

- Arquitetura do dev router (webhook forwarding)
- `meta.py` e chamadas ao Graph API da Meta
- Variáveis de ambiente existentes
- Queries de leitura no frontend (CRM exibe tudo)
- GitHub Actions / deploy pipeline
- Qualquer outra tabela do Supabase

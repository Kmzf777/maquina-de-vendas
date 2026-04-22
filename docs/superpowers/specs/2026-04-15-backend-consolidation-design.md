# Backend Consolidation Design

**Date:** 2026-04-15  
**Status:** Approved  
**Scope:** Merge `backend/`, `backend-evolution/`, and `backend-recuperar-lead/` into a single unified `backend/`

---

## Problem

The system has three independent Python/FastAPI backend folders that evolved organically:

- `backend/` — original production backend (only this is deployed via CI/CD)
- `backend-evolution/` — Evolution API integration focus; added broadcast, cadence, stats, deals, token tracking
- `backend-recuperar-lead/` — adds outbound lead recovery dispatch and multi-provider Strategy/Factory pattern

This fragmentation causes:
- Bug fixes and prompt updates must be propagated manually to three codebases
- Functional capabilities (cadence scheduling, outbound dispatch) are siloed and cannot interact
- Database migrations are pulverized across folders with duplicate and conflicting `002_*.sql` files
- CI/CD only deploys `backend/`; all evolution work bypasses the production pipeline
- Two parallel provider abstractions (`whatsapp/factory.py` and `providers/registry.py`) coexist without integration, and `outbound/dispatcher.py` bypasses both with direct HTTP calls

---

## Approach

**Abordagem 1 — Big Bang from most complete base.**

Use `backend-recuperar-lead` as the canonical base (it already contains everything from `backend-evolution` plus `outbound/`, `providers/`, and `conversations/`). Port the missing pieces from the original `backend/`, apply the `whatsapp/` unification refactor, linearize migrations, then overwrite `backend/` with the result on a feature branch.

This is a cold composition — `backend/` is the only service serving live traffic, so there is no rollback risk during development.

---

## Architecture

### Module Inventory

| Module | Source | Notes |
|---|---|---|
| `agent/` | `backend-recuperar-lead` | Includes `token_tracker.py` |
| `agent_profiles/` | `backend/` original | **Port** router + service |
| `broadcast/` | `backend-recuperar-lead` | — |
| `buffer/` | `backend-recuperar-lead` + `backend/` original | **Port** `flusher.py`; keep toggle endpoints |
| `cadence/` | `backend-recuperar-lead` | scheduler refactored (see below) |
| `campaign/` | `backend-recuperar-lead` | — |
| `channels/` | `backend-recuperar-lead` + `backend/` original | **Port** `router.py` from original |
| `conversations/` | `backend-recuperar-lead` | — |
| `db/` | `backend-recuperar-lead` | — |
| `humanizer/` | `backend-recuperar-lead` | — |
| `leads/` | `backend-recuperar-lead` | — |
| `outbound/` | `backend-recuperar-lead` | dispatcher refactored (see below) |
| `stats/` | `backend-recuperar-lead` | — |
| `webhook/` | `backend-recuperar-lead` | Both evolution parser + meta parser |
| `whatsapp/` | **REFACTORED** | Unified; replaces both `factory.py` and `providers/` |
| `providers/` | — | **DELETED** — absorbed into `whatsapp/` |

### Final `backend/app/` Structure

```
app/
├── agent/
│   ├── orchestrator.py
│   ├── token_tracker.py
│   ├── tools.py
│   └── prompts/
├── agent_profiles/
│   ├── router.py
│   └── service.py
├── broadcast/
│   ├── router.py
│   ├── service.py
│   └── worker.py
├── buffer/
│   ├── flusher.py
│   ├── manager.py
│   └── processor.py
├── cadence/
│   ├── router.py
│   ├── scheduler.py
│   └── service.py
├── campaign/
│   ├── importer.py
│   ├── router.py
│   └── worker.py
├── channels/
│   ├── router.py
│   └── service.py
├── conversations/
│   └── service.py
├── db/
│   └── supabase.py
├── humanizer/
│   ├── splitter.py
│   └── typing.py
├── leads/
│   ├── router.py
│   └── service.py
├── outbound/
│   ├── dispatcher.py
│   └── router.py
├── stats/
│   ├── pricing_router.py
│   └── router.py
├── webhook/
│   ├── meta_parser.py
│   ├── meta_router.py
│   ├── parser.py
│   └── router.py
├── whatsapp/
│   ├── base.py
│   ├── evolution.py
│   ├── media.py
│   ├── meta.py
│   └── registry.py
├── config.py
└── main.py
```

---

## Key Design Decisions

### 1. WhatsApp Provider Unification (`whatsapp/`)

Two parallel abstractions (`WhatsAppClient` in `whatsapp/base.py` and `WhatsAppProvider` in `providers/base.py`) are merged into a single interface.

**`whatsapp/base.py` — `WhatsAppProvider` ABC:**

```python
class WhatsAppProvider(ABC):
    @abstractmethod
    async def send_text(self, to: str, body: str) -> dict: ...
    @abstractmethod
    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict: ...
    @abstractmethod
    async def send_audio(self, to: str, audio_url: str) -> dict: ...
    @abstractmethod
    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict: ...
```

**`whatsapp/registry.py` — single resolution point:**

```python
def get_provider(channel: dict) -> WhatsAppProvider:
    """Resolve the correct WhatsAppProvider instance from a channel record."""
```

Replaces both `whatsapp/factory.py` and `providers/registry.py`. The `providers/` directory is deleted entirely.

**Callers refactored to use `get_provider(channel)`:**

| Caller | Before | After |
|---|---|---|
| `outbound/dispatcher.py` | Direct `httpx` call to Meta API | `get_provider(channel).send_text(...)` |
| `cadence/scheduler.py` | `send_text(phone, msg)` direct import | `get_provider(channel).send_text(...)` |
| `broadcast/worker.py` | `client.send_text(...)` via factory | `get_provider(channel).send_text(...)` |

**Channel resolution in `cadence/scheduler.py`:** The scheduler fetches due enrollments. The query must be enriched to join the `channel` associated with each lead so the scheduler can call `get_provider(channel)` at runtime. The channel record contains `provider` and `provider_config` fields used by the registry.

### 2. Buffer + Flusher with Dynamic Toggle

`buffer/flusher.py` runs as a persistent background task launched in the FastAPI `lifespan`. Every cycle it checks the Redis flag `config:buffer_enabled` before processing.

**Runtime flow:**

```
lifespan start
  └── asyncio.create_task(run_flusher(app))   # always running

run_flusher (continuous loop)
  └── reads "config:buffer_enabled" from Redis
      ├── "0" → sleep, skip this cycle
      └── "1" → flush accumulated messages → call agent orchestrator
```

The `webhook/` inbound handler applies the same check: if flag is `"0"`, the message is processed immediately (no buffering); if `"1"`, it is enqueued in Redis for the flusher to batch.

**Initial state:** Flag set to `"0"` (buffer off) at startup — same as `backend-recuperar-lead`. The CRM Next.js frontend can toggle via `POST /api/buffer` without restarting the application.

**Control endpoints (retained from evolved backends):**

```
GET  /api/buffer  →  {"enabled": true|false}
POST /api/buffer  →  body: {"enabled": true|false}
```

**Web dashboard `/web`:** Retained from original `backend/` — visual toggle panel that reflects real Redis flag state.

### 3. `main.py` Router Registration

All routers registered in the consolidated `main.py`:

```python
app.include_router(webhook_router)       # Evolution webhook
app.include_router(meta_webhook_router)  # Meta Cloud webhook
app.include_router(leads_router)
app.include_router(broadcast_router)
app.include_router(cadence_router)
app.include_router(stats_router)
app.include_router(pricing_router)
app.include_router(outbound_router)
app.include_router(channels_router)
app.include_router(agent_profiles_router)
```

---

## Database Migrations

### Strategy

Linearize all migrations from all three backends into a clean, numbered sequence. All files must be fully idempotent so they can be run on every deploy without risk.

### Idempotency Rules (mandatory for every migration file)

- Table creation: `CREATE TABLE IF NOT EXISTS`
- Index creation: `CREATE INDEX IF NOT EXISTS`
- Column addition:
  ```sql
  DO $$ BEGIN
    ALTER TABLE t ADD COLUMN col type;
  EXCEPTION WHEN duplicate_column THEN NULL;
  END $$;
  ```
- Seed data: `INSERT ... ON CONFLICT DO NOTHING`
- Enum types: `DO $$ BEGIN CREATE TYPE ...; EXCEPTION WHEN duplicate_object THEN NULL; END $$`

### Migration Sequence

| File | Content |
|---|---|
| `001_initial.sql` | Core tables: `leads`, `messages`, `channels`, `agent_profiles`, `campaigns` |
| `002_crm_enrichment.sql` | Resolves the 3 conflicting `002_*` files: CRM columns, lead enrichment, tags |
| `003_cadence.sql` | Tables: `cadences`, `cadence_steps`, `cadence_enrollments` |
| `004_campaign_type.sql` | `type` column on `campaigns` |
| `005_token_usage.sql` | `token_usage` table for per-lead/stage cost tracking |
| `006_lead_notes_events.sql` | Tables: `lead_notes`, `lead_events` |
| `007_multi_channel.sql` | Multi-channel support: `channel_id` foreign keys and related columns |
| `008_agent_profile_seed.sql` | Default ValerIA agent profile seed |
| `009_deals.sql` | `deals` table (sales funnel) |
| `010_campaigns_redesign.sql` | Campaigns table redesign with targeting and scheduling fields |

No external migration runner (Alembic, Flyway). Files are applied via shell script on the VPS, compatible with the current SSH-based deploy workflow.

---

## Supporting Files

| File | Source | Action |
|---|---|---|
| `Dockerfile` | `backend/` original | **Base canônica** — contém configuração de build compatível com a VPS |
| `docker-compose.yml` | `backend/` original | **Base canônica** — contém labels Traefik, redes externas do Docker Swarm (`canastrainteligencia`) e variáveis de ambiente reais da VPS; não substituir pelo do `backend-recuperar-lead` |
| `config.py` | `backend/` original | **Base canônica** — contém as variáveis de ambiente da VPS; recebe acréscimo das novas vars presentes no `config.py` do `backend-recuperar-lead` (ex: `meta_access_token`, `meta_phone_number_id`, `openai_api_key`) |
| `requirements.txt` | Todos os três | **Merge** — union de todas as dependências, deduplicadas; base do original acrescida das libs novas dos backends evoluídos |
| `pytest.ini` | `backend-recuperar-lead` | Use as-is |

---

## CI/CD

**`deploy.yml` — no structural changes required.** The existing job monitors `backend/` and deploys via SSH. One addition: a migration step executed before `docker stack deploy`.

```yaml
# In deploy-backend job, after git pull, before docker stack deploy:
- name: Apply migrations
  # For each file in backend/migrations/:
  # psql $DATABASE_URL -f backend/migrations/001_initial.sql
  # ...
  # psql $DATABASE_URL -f backend/migrations/010_campaigns_redesign.sql
```

Migrations are idempotent — running all files on every deploy is safe. First run applies the full schema; subsequent runs are no-ops for existing objects.

---

## Cleanup (Final Step)

After the consolidated `backend/` is validated on the feature branch and merged to `master`:

```bash
git rm -r backend-evolution/
git rm -r backend-recuperar-lead/
git commit -m "chore: remove superseded backend forks after consolidation"
```

---

## Decision Summary

| Decision | Choice |
|---|---|
| Canonical base | `backend-recuperar-lead` |
| Target folder | `backend/` (in-place, on feature branch) |
| Composition strategy | Big Bang — port missing pieces, then refactor |
| Provider abstraction | `whatsapp/` unified with `registry.py`; `providers/` deleted |
| Buffer behavior | Automatic flusher + Redis toggle API |
| Migrations | Linearized 001–010, all idempotent |
| CI/CD | Unchanged structure + migration step added |
| Legacy forks | Deleted after validation and merge |

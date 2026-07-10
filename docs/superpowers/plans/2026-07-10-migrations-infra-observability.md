# Migrações + Higiene de Infra + Observabilidade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (Opt5) pasta única `supabase/migrations/` + ledger `schema_migrations` + runner `apply_migrations.py`; (Opt8) healthchecks conservadores, usuário não-root, `data/` fora do versionamento; (P4) logging JSON stdlib + Sentry fail-open no backend.

**Architecture:** Specs `2026-07-10-migrations-runner-design.md` e `2026-07-10-infra-observabilidade-design.md`.

**Tech Stack:** httpx (Management API), stdlib logging, sentry-sdk[fastapi], Docker/Swarm.

## Global Constraints

- Sem Alembic/psycopg; runner usa Management API com `User-Agent` explícito (Cloudflare 1010).
- NUNCA reexecutar SQL em banco existente: adoção via `--baseline` (grava ledger sem executar); `--apply` só toca o que não está no ledger.
- Healthchecks: intervalos ≥30s, `start_period` generoso; worker sem healthcheck.
- `SENTRY_DSN` vazio = no-op absoluto; watchdog intocado.
- Suítes pytest+vitest verdes; push só com autorização.

---

### Task 1 (Opt5): consolidar SQLs + runner com ledger (TDD no runner)

**Files:**
- Move: `migrations/*.sql` e `backend/migrations/*.sql` → `supabase/migrations/` (git mv; `009_multi_agent_schema.sql` → `009b_...`; dedupe por hash)
- Create: `backend/scripts/apply_migrations.py`
- Test: `backend/tests/test_apply_migrations.py`

- [ ] Inventário: detectar nomes duplicados entre os 3 diretórios (hash compare) antes do move
- [ ] `git mv` de tudo para `supabase/migrations/`; remover diretórios vazios
- [ ] Testes do runner (transport mockado): ordenação lexicográfica; `--apply` pula ledger; para no 1º erro; `--baseline` recusa com ledger populado; drift de sha256 gera warning; `--dry-run` não executa
- [ ] Implementar runner: `_sql(query)` via `POST https://api.supabase.com/v1/projects/{ref}/database/query` (headers Authorization Bearer PAT + User-Agent); ensure-ledger; comandos `--status/--baseline/--apply/--dry-run`
- [ ] `pytest -k apply_migrations` verde
- [ ] Commit: `feat(migrations): pasta unica supabase/migrations + ledger schema_migrations + runner`

### Task 2 (Opt8): Dockerfiles não-root + healthchecks + limpeza

**Files:**
- Modify: `backend/Dockerfile` (curl + appuser), `frontend/Dockerfile` (USER node + chown)
- Modify: `backend/docker-compose.yml` (healthchecks api/redis), `frontend/docker-compose.yml` (healthcheck crm)
- Modify: `.gitignore` (+`data/`, `TREE.md`); `git rm --cached data/`

- [ ] Dockerfile backend: `apt-get install -y curl` (com cleanup), `useradd`, `USER appuser`
- [ ] Compose: healthchecks com interval 30s/timeout 5s/retries 3/start_period 40s (api), redis-cli ping (redis), wget spider /login (crm)
- [ ] `git rm --cached` dos 4 arquivos de `data/` + gitignore
- [ ] Validar compose: `docker compose -f backend/docker-compose.yml config -q` (se Docker disponível)
- [ ] Commit: `chore(infra): healthchecks conservadores, usuario nao-root e data/ fora do git`

### Task 3 (P4): logging JSON + Sentry fail-open (TDD)

**Files:**
- Create: `backend/app/logging_setup.py`, `backend/app/observability.py`
- Modify: `backend/app/main.py`, `backend/app/campaign/worker.py`, `backend/requirements.txt` (+sentry-sdk[fastapi]), `backend/.env.example` (LOG_FORMAT, SENTRY_DSN)
- Test: `backend/tests/test_logging_setup.py`, `backend/tests/test_observability.py`

- [ ] Testes: JsonFormatter produz JSON válido com ts/level/logger/msg; exceção vira campo; LOG_FORMAT=text preserva formato atual; init_sentry sem DSN é no-op; com DSN chama sentry_sdk.init com environment
- [ ] Implementar `logging_setup.setup_logging()` e `observability.init_sentry()`
- [ ] Ligar nos entrypoints (lifespan da API e shim do worker)
- [ ] Commit: `feat(obs): logs JSON estruturados + Sentry fail-open (SENTRY_DSN opcional)`

### Task 4: suítes completas + fechamento

- [ ] `pytest -q -m "not integration"` verde; `npm run test` + `type-check` + `build` verdes
- [ ] Commit specs+plano; diff consolidado; push só com autorização
- [ ] Pós-deploy (operacional, com autorização): `apply_migrations --baseline` em homolog e prod (PATs distintos do .mcp.json); criar projeto Sentry e setar SENTRY_DSN quando o usuário quiser ativar

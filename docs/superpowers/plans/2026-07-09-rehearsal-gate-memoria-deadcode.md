# Rehearsal CI Gate + Memória P3 + Limpeza de Código Morto — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (P2) rodar os 10 arquétipos de rehearsal como gate agendado/manual no GitHub Actions; (P3) destravar a persistência do dossiê para conversas curtas/leads NULL e tornar o "histórico completo" real; (Opt4) deletar o código morto confirmado pelo levantamento de 09/07.

**Architecture:** Specs `2026-07-09-rehearsal-ci-gate-design.md` e `2026-07-09-memoria-persistencia-curta-design.md`. Opt4 segue o veredicto item a item do relatório de código morto (sem spec — é deleção guiada por evidência).

**Tech Stack:** GitHub Actions (workflow novo, cron+dispatch), pytest, vitest, harness de rehearsal existente.

## Global Constraints

- Rehearsal NUNCA no push (custo LLM) — só `schedule` + `workflow_dispatch`.
- Supabase homolog + chaves Gemini isoladas (guards do harness abortam com chave/URL de prod).
- Backfill usa flash-lite (já é default `memory_model`); execução em prod só após deploy dos fixes.
- Suítes completas (pytest + vitest) verdes antes de qualquer push; push só com autorização.
- NÃO deletar: backend `evolution.py`/`webhook/parser.py` (vivos via registry/endpoint), merge `fetchEvolutionConversations`/`fetchEvolutionMessages` (alcançável com canal evolution ativo), `_execute_send_node`, `handle_campaign_reply`.

---

### Task 1 (Opt4-backend): remover loop morto de campaigns/worker.py

**Files:**
- Modify: `backend/app/campaigns/worker.py`

Deletar: `process_campaign_enrollments`, `check_campaign_triggers`, `_is_within_window`, `_next_window_start`, `_execute_condition_node`, `_execute_action_node`, `_execute_end_node` + imports órfãos (`asyncio`, `random`, `get_supabase` top-level, `get_settings`/`_ENV_TAG`/`BRT_OFFSET`, e do bloco campaigns.service: `get_campaigns_with_trigger_type`, `is_already_enrolled`, `create_enrollment`, `get_due_enrollments`, `update_enrollment`, `complete_enrollment`).

**Manter:** `_execute_send_node` (engine importa), `handle_campaign_reply` (+ `cancel_enrollment`/`pause_enrollment`), `decide_failure_update` + `_is_permanent_error` + seu teste (`test_campaigns_worker_retry.py`) — código puro com suíte própria; classificador de erro Meta reutilizável.

- [ ] Deletar funções + imports órfãos; conferir com `python -m compileall app`
- [ ] `python -m pytest tests/ -q -k "campaign or automation" -m "not integration"` verde
- [ ] Commit: `chore(campaigns): remove loop morto substituido pelo automation engine (~200 linhas)`

### Task 2 (Opt4-frontend): remover rotas e componente mortos

**Files:**
- Delete: `frontend/src/components/chat-active.tsx`, `frontend/src/app/api/chat/send/route.ts`, `frontend/src/app/api/conversations/[id]/messages/route.ts`, `frontend/src/app/api/evolution/` (3 rotas)
- Modify: `frontend/src/lib/types.ts` (remover `EvolutionChat`/`EvolutionMessage` órfãos), `frontend/src/proxy.ts` (remover matcher `/api/evolution/:path*` se o diretório sumir), `frontend/src/lib/auth/roles.ts` (remover `/api/evolution` de ADMIN_API_PREFIXES)

- [ ] Verificar se `app/api/chat/` contém apenas `send` (se houver outras rotas vivas, remover só `send`)
- [ ] Deletar arquivos; limpar config órfã (matcher/roles/types)
- [ ] `npm run test` (guard de cobertura do matcher continua verde — dirs removidos saem da enumeração) + `npm run type-check` + `npm run build`
- [ ] Commit: `chore(frontend): remove chat-active, /api/chat/send, rota messages sem consumidor e /api/evolution/*`

### Task 3 (P3): fixes de persistência da memória (TDD)

**Files:**
- Modify: `backend/app/agent/memory_manager.py` (select + skip em `process_stale_lead_memories`; `limit=` no `get_history` do caminho sem dossiê)
- Test: `backend/tests/test_memoria_persistencia_curta_2026_07_09.py`

- [ ] Teste 1 (falha): lead com `rolling_summary=None` e watermark ≥ last_msg NÃO é pulado pelo worker
- [ ] Teste 2 (falha): caminho sem dossiê chama `get_history` com `limit=MEMORY_BACKFILL_MAX_MSGS` e fica com as mensagens mais recentes
- [ ] Fix 1: adicionar `rolling_summary` ao select (`:338`) e condicionar o skip a `and lead.get("rolling_summary")`
- [ ] Fix 2: passar `limit=MEMORY_BACKFILL_MAX_MSGS` (verificar semântica asc/desc de `get_history` em `leads/service.py:1509` — garantir que o corte preserva as mais recentes)
- [ ] `python -m pytest tests/ -q -k "memory or memoria or dossie" -m "not integration"` verde
- [ ] Commit: `fix(memoria): worker não pula lead sem dossiê + histórico completo real (cap 200 efetivo)`

### Task 4 (P2): exit code no runner outbound + workflow rehearsal.yml

**Files:**
- Modify: `backend/scripts/outbound_rehearsal_runner.py` (sys.exit igual ao inbound)
- Create: `.github/workflows/rehearsal.yml`

- [ ] Adicionar ao final de `main()` do outbound: `any_fail = any(v.get("status") != "passed" for v in verifications)` + `sys.exit(1 if any_fail else 0)` (espelhar `rehearsal_runner.py:410-411`)
- [ ] Criar workflow: `schedule: cron '0 9 * * *'` + `workflow_dispatch` (input `only`); job único ubuntu-latest, `timeout-minutes: 45`; services redis:7-alpine (porta 6379); setup-python 3.12 + pip install -r requirements.txt -r requirements-dev.txt; sobe `uvicorn app.main:app --port 8001` em background com env: `REHEARSAL_MODE=true`, `SUPABASE_URL/SUPABASE_SERVICE_KEY` = secrets `REHEARSAL_SUPABASE_*`, `GEMINI_API_KEY` = secret `REHEARSAL_GEMINI_API_KEY`, `REDIS_URL=redis://localhost:6379`; espera `/health`; roda `python -m scripts.rehearsal_runner` e depois `python -m scripts.outbound_rehearsal_runner` com `DEV_BACKEND_URL=http://127.0.0.1:8001`, `GEMINI_API_KEY_DEV` secret, `REHEARSAL_ONLY` do input; step final (always) publica resumo no `$GITHUB_STEP_SUMMARY` a partir dos run.json e faz upload-artifact das pastas de run (retention 14d)
- [ ] Validar YAML (`yaml.safe_load`)
- [ ] Commit: `ci(rehearsal): gate diario/dispatch dos 10 arquetipos (homolog + chaves isoladas)`

### Task 5: suítes completas + fechamento

- [ ] `python -m pytest -q -m "not integration"` (esperado: ~1864 - o que sair com o código morto + novos de P3)
- [ ] `npm run test` + `npm run type-check` + `npm run build`
- [ ] Commit specs + plano; diff consolidado ao usuário; push só com autorização
- [ ] Pós-deploy (com autorização): `python -m scripts.backfill_dossies --dry-run` e depois lotes; primeira execução manual do rehearsal.yml via dispatch (exige os 4 secrets criados — alertar o usuário ANTES)

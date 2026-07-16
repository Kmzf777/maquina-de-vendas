# Status — Ciclo Estratégico de Evolução Tecnológica

**Período:** 2026-07-09 a 2026-07-10 · **Status:** ✅ CONCLUÍDO E DEPLOYADO (escopo encerrado)
**Origem:** diagnóstico estratégico de 09/07 (análise geral → 8 otimizações + 5 inovações)

## Otimizações

- **Opt1 — Gate de testes no CI:** ✅ pytest (1888+) e vitest (160) bloqueiam o deploy no `deploy.yml`; salvou produção 2× de conflitos semânticos de merge.
- **Opt2 — Auth das rotas do frontend:** ✅ matcher do `proxy.ts` completado (13 rotas + `/painel-vendas`) + teste-guarda `proxy-coverage.test.ts` (rota fora do matcher quebra o deploy).
- **Opt3 — Retry/acesso a dados unificado:** ✅ `db_call` (to_thread + run_with_retry) nos hot paths de worker/scheduler/processor.
- **Opt4 — Código morto:** ✅ loop antigo de campaigns (~200 l), chat-active, `/api/chat/send`, `/api/evolution/*`, rota messages órfã e tipos Evolution removidos.
- **Opt5 — Migrações:** ✅ pasta única `supabase/migrations/` (92 SQLs), ledger `schema_migrations`, runner `apply_migrations.py` (`--baseline/--apply/--status/--dry-run`).
- **Opt6 — Arquivos-monstro (frontend):** ✅ `cadence-flow-builder.tsx` 1834 l → barrel + 6 módulos coesos (ponte do React Flow encapsulada; 13 testes de helpers).
- **Opt7 — Paginação do chat:** ✅ janela de 100 msgs + "Carregar anteriores" + `React.memo` nos bubbles (push realtime re-renderiza O(1)); payload de `/api/conversations` intacto.
- **Opt8 — Higiene de infra:** ✅ healthchecks conservadores (api/redis/crm healthy em prod), usuário não-root nos 2 Dockerfiles, `data/` (1,3 MB) fora do git.

## Inovações

- **P1 — Worker event-driven (Redis Streams):** ✅ 7 domínios asyncio isolados; XADD/XREADGROUP como wake-up (latência <0,1s vs 30s), banco = fonte de verdade, degradação graceful sem Redis.
- **P2 — Rehearsal como gate de regressão:** ✅ `rehearsal.yml` (cron diário + dispatch) roda os 10 arquétipos contra homolog; pendente: 4 secrets + 1ª execução.
- **P3 — Memória de longo prazo da Valéria:** ✅ worker não pula mais lead sem dossiê; histórico completo real (cap 200 efetivo via `latest=True`); backfill idempotente pronto (rodar pós-deploy).
- **P4 — Observabilidade estruturada:** ✅ logs JSON (stdlib, `LOG_FORMAT=text` p/ dev) + Sentry fail-open (`SENTRY_DSN` opcional); watchdog preservado.
- **P5 — React Query (incremental):** ✅ página `conversas` migrada (provider local, seleção derivada, cache patcheado pelo realtime, otimistas com rollback); resto do app segue para iterações futuras.

## Pendências operacionais (fora do escopo de código)

`apply_migrations --baseline` (homolog+prod) · secrets do rehearsal + 1º dispatch · `backfill_dossies` (agora liberado, fixes em prod) · `SENTRY_DSN` quando ativar.

Specs e planos de cada item em `docs/superpowers/specs/2026-07-09*` e `2026-07-10*`.

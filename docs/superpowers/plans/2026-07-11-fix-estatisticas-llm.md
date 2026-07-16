# Plan — Fix agregação de /estatisticas (RPC no servidor)

**Spec:** `docs/superpowers/specs/2026-07-11-fix-estatisticas-llm.md`
**Branch:** `fix/dashboard-llm-metrics`
**Status:** AGUARDANDO autorização do usuário para a fase de Execution.

## Task 1 — Migração SQL (RPCs de agregação)
1. Ler as 6 rotas de `frontend/src/app/api/stats/**` e inventariar o contrato exato (campos JSON, filtros, agrupamentos) de cada uma — o contrato é imutável neste fix.
2. Criar a migração pelo runner unificado do repo (padrão das migrações existentes em `supabase/migrations/`): 6 funções `STABLE SECURITY INVOKER` (`stats_costs_summary`, `stats_costs_daily`, `stats_costs_breakdown`, `stats_costs_top_leads`, `stats_whatsapp_summary`, `stats_whatsapp_daily`), filtros NULL-áveis, `REVOKE EXECUTE FROM anon, authenticated` + `GRANT EXECUTE TO service_role`.
3. Aplicar no HOMOLOG primeiro (padrão do repo); lembrar `NOTIFY pgrst, 'reload schema'` (armadilha PGRST205 conhecida). Validar cada RPC com janelas reais contra a verdade paginada.
4. Aplicação em PROD somente na janela do deploy, com autorização.

## Task 2 — Rotas Next.js
1. Trocar fetch+reduce por `sb.rpc(...)` nas 6 rotas, preservando o JSON de resposta byte a byte (mesmos nomes/arredondamentos — ex.: `Math.round(x*1e6)/1e6`).
2. Testes vitest para a lógica pura que restar (mapeamento RPC→JSON), no padrão do repo (não inventar harness de rota se não existir — extrair mappers puros como em `media-message-content.ts`).

## Task 3 — Validação de integridade
1. Script de verificação (temporário) comparando RPC vs verdade paginada nas janelas Hoje/7d/30d em homolog (e prod read-only): igualdade exata + invariante de monotonicidade Hoje ≤ 7d ≤ 30d.
2. `npx vitest run` + `pytest` (backend intocado, roda como regressão) verdes; advisors Supabase sem novos ERRORs.

## Follow-up registrado (fora deste fix)
- Fuso: interpretar `start_date/end_date` do dashboard em BRT (hoje o corte de "dia" é UTC = 21:00 BRT da véspera). Tratar em mudança separada para não contaminar a validação da correção de agregação.

## Riscos
- RPC divergir do contrato atual em algum campo raro (ex.: breakdown com dimensão calculada no JS) — mitigado pela Task 1.1 (inventário antes de escrever SQL) e pela comparação byte a byte na validação.
- Funções novas em `public` viram superfície de API — mitigado pelo REVOKE/GRANT restrito + advisors no gate (checklist de segurança Supabase).

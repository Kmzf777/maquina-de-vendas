# Plano — Custo de IA em R$ no /estatisticas

Spec: `docs/superpowers/specs/2026-07-12-add-brl-cost-dashboard.md` · Branch: `feat/dashboard-brl-pricing` → master (autorizado após vitest verde).

## Trilha A — dados
1. `stats-mappers.ts`: `DEFAULT_USD_TO_BRL_WITH_TAX`, `resolveBrlMultiplier`, `formatBRL`; `mapCostsSummary(row, brlMultiplier?)` retorna também `total_cost_brl` (round4) e `brl_multiplier`.
2. `app/api/stats/costs/route.ts`: lê `process.env.CUSTO_IA_MULTIPLICADOR_BRL` → `resolveBrlMultiplier` → passa ao mapper.
3. `frontend/.env.example` (se existir): documentar `CUSTO_IA_MULTIPLICADOR_BRL=5.73`.

## Trilha B — UI (`estatisticas/page.tsx`)
4. Interface do estado de IA: `total_cost_brl?: number`.
5. Card LLM/IA: linha secundária `≈ {formatBRL(...)}` + rótulo "est. câmbio+impostos" (12px, cinza da paleta `#7b7b78`, sem alterar o USD).
6. Tabela de detalhamento, linha LLM/IA: `≈ R$` em 11px sob o USD.
7. Aviso âmbar: acrescentar frase sobre a estimativa em R$ do custo de IA.

## Validação e deploy
8. Testes novos em `stats-mappers.test.ts`; rodar `vitest run` completo do frontend.
9. Commit → `git pull origin master` → `git push origin feat/dashboard-brl-pricing:master`; acompanhar deploy.

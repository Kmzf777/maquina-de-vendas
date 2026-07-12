# Plano — Fix do Dashboard Principal

Spec: `docs/superpowers/specs/2026-07-12-fix-main-dashboard.md` · Branch: `fix/main-dashboard-data`.
**Gate:** aguardando aprovação do diagnóstico pelo usuário antes de qualquer código.

## Etapa 1 — Migração SQL (`supabase/migrations/20260712_dashboard_rpcs.sql`)
1. `dashboard_kpis(p_tz)`: leads_today (dia local), ativos/ganhos/perdidos count+value via `deals.stage_id → pipeline_stages.key`, `unanswered_chats` (conversations: último turno do cliente >1h sem resposta), `avg_first_response_minutes` (30d, window sobre messages).
2. `dashboard_funnel()`: count+sum(value) por stage real (label + order_index + pipeline_id).
3. `dashboard_lead_sources()`: bucket normalizado de `metadata->>'origem'` (mapear valores crus da LP; default 'whatsapp').
4. Padrão das stats RPCs: `LANGUAGE sql STABLE SECURITY DEFINER SET search_path`. Aplicar em prod+homolog via runner/Management API (com autorização) e registrar no ledger.
5. Antes de fechar o SQL: validar as 3 queries read-only contra prod (números devem bater com a auditoria: 17 leads hoje, 1515 deals, stages reais).

## Etapa 2 — Rotas + mappers
6. `src/lib/dashboard-mappers.ts` (puro) + testes vitest (contrato, tipos string→number do PostgREST, buckets).
7. Rotas `frontend/src/app/api/dashboard/{kpis,funnel,sources}/route.ts` (finas, sb.rpc).
8. **Adicionar matcher das rotas novas no `proxy.ts`** (lição 841bc31 — sem isso a rota 404 em prod).

## Etapa 3 — Página `/dashboard`
9. Trocar `useRealtimeLeads`/`useRealtimeDeals` por fetch das 3 rotas (`useEffect` + polling 60s + refresh on focus). Hooks NÃO são apagados (Kanban usa).
10. KpiCards: ligar aos campos da RPC (mesmos 6 cards, layout intocado); "Tempo de resposta" e "Chats sem resposta" passam a ter dado real.
11. FunnelChart/FunnelMovement por stages reais (label/order_index; perdidos no período via closed_at+key).
12. LeadSourcesChart consome `/api/dashboard/sources`.
13. Avatar colors por hash (remove nomes hardcoded).
14. Verificar consumidores restantes de `DEAL_STAGES`; remover import da página.

## Etapa 4 — Validação
15. vitest completo (novos + regressão). Conferência manual: KPIs vs queries SQL diretas (aceite da spec). Lighthouse rápido opcional: payload da página deve despencar (hoje: 1000 leads + 1000 deals com joins no mount).
16. Commit → pull → push master (mediante autorização) → acompanhar deploy → validar números em produção contra o banco.

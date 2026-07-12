# Plano — Novo Dashboard Principal (13 KPIs de operação IA+SDR)

Spec (v2): `docs/superpowers/specs/2026-07-12-fix-main-dashboard.md` · Branch: `fix/main-dashboard-data`.
**Gate:** aguardando ordem de implementação do usuário.

## Etapa 1 — SQL (`supabase/migrations/20260712_dashboard_rpcs.sql`)
1. `dashboard_business_seconds(t_start,t_end)` (IMMUTABLE, seg–sex 10h–16h BRT) + testes SQL dos 4 cenários (mesma janela / overnight / fim de semana / resposta fora da janela).
2. `dashboard_kpis(p_start,p_end,p_tz)` — itens 1-8 da spec (leads hoje+tendência, ativos c/ Valéria [snapshot 24h], conversas atendidas, handoffs via `'[encaminhar_humano] Lead encaminhado%'`, taxa qualificação, SLA humano mediana/p95 útil, custo/handoff, custo/atendimento).
3. `dashboard_funnel_conversion` (coorte lead→handoff→ganho via `stage_id`/`key='fechado_ganho'`).
4. `dashboard_outbound_frio` (broadcasts×broadcast_leads, `template_name LIKE 'utilidade_%'`: sent/delivered/replied + taxas).
5. `dashboard_followups(p_tz)` (agendados vs executados hoje por job_type + pendings vencidos + retornos agendados com próximo fire_at).
6. Validar CADA RPC contra produção com queries diretas ANTES de seguir (aceites da spec §5). Aplicar prod+homolog (runner/Management API, com autorização) + ledger.

## Etapa 2 — Rotas + mappers
7. `src/lib/dashboard-mappers.ts` (puros; tipos string→number do PostgREST) + testes vitest de contrato (incl. divisões por zero → 0, períodos vazios).
8. Rotas `/api/dashboard/{kpis,conversion,outbound,followups}` finas (sb.rpc).
9. **Matcher das 4 rotas no `proxy.ts`** (lição registrada — sem isso, 404 em produção).

## Etapa 3 — Página `/dashboard`
10. Remover: 6 KpiCards atuais, `FunnelChart`, `LeadSourcesChart`, `FunnelMovement`, e os hooks `useRealtimeLeads`/`useRealtimeDeals` DA PÁGINA (ficam no Kanban). Verificar consumidores restantes de `DEAL_STAGES`.
11. Novo layout: seletor de período (Hoje/7d/30d, padrão /estatisticas) → Linha 1 "Motor" (4 cards) → Linha 2 "Qualidade e custo" (4 cards) → blocos "Conversão fim-a-fim" (3 estágios), "Outbound Frio" (funil sent→delivered→replied), "Esteira de Follow-up" (agendados×executados + retornos). Tooltips: SLA explica horário comercial e ausência de feriados.
12. Manter abaixo (intocados): `SlaTable`, `OverdueLeadsSection`, `OnlineUsersSection`, `ConversionsSection`.
13. Polling 60s + refresh on focus; estados de loading/erro por bloco (um bloco com erro não derruba a página).

## Etapa 4 — Validação e deploy
14. vitest completo; conferência manual RPC×UI×SQL direto (3 números por bloco).
15. Commit → pull → push master (mediante autorização) → acompanhar deploy → conferir números em produção.

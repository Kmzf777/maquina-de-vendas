# Spec — Dashboard /estatisticas: agregação truncada pelo max-rows do PostgREST

**Sintoma:** "Hoje" > "7 dias" em tokens e custo de IA (matematicamente impossível); chamadas de 7 dias cravadas em exatamente 1000.

## Causa raiz (provada em produção, read-only)

As rotas de `/api/stats/*` fazem a agregação **no cliente**: buscam as linhas cruas de `token_usage` (ou `messages`) com `.limit(10000)` e somam com `reduce` no Node (`frontend/src/app/api/stats/costs/route.ts:14-33`). O Supabase/PostgREST tem um teto de servidor (**max-rows = 1000**) que se sobrepõe a qualquer `limit` maior pedido pelo cliente — o `.limit(10000)` devolve **no máximo 1000 linhas**, silenciosamente. E a query **não tem `.order()`**, então o subconjunto de 1000 linhas é arbitrário (ordem física da heap ≈ inserção — as linhas mais ANTIGAS da janela).

Reprodução exata contra produção (11/07):

| Janela | Réplica da rota (limit 10000, sem order) | Verdade (count exato + paginação) | Truncado? |
|---|---|---|---|
| Hoje | 194 linhas / 4.472.737 tok / $1,34 | 194 / 4.472.737 / $1,34 | Não |
| 7 dias | **1000 linhas / 3.108.729 tok / $0,8743** | **2.156 / 12.591.462 / $4,1303** | **SIM (1000/2156)** |

Os números da réplica truncada batem **byte a byte** com o bug reportado no dashboard (3.108.729 / $0.87 / 1000). A inversão acontece porque: "Hoje" (194 ≤ 1000) escapa do teto e soma completo; "7 dias" soma só as 1000 linhas mais antigas da janela (04–08/07, período de chamadas mais baratas/curtas — transcrição/loop em flash-lite), que somam MENOS que o dia atual completo. As "chamadas = 1000" não estavam "corretas": são a assinatura do teto.

**Frontend inocente** (`(authenticated)/estatisticas/page.tsx` só passa `start_date`/`end_date` e plota o que a API devolve). **Timezone não é a causa da inversão** — há um skew secundário real (datas `YYYY-MM-DD` comparadas contra `created_at` UTC fazem o "Hoje" começar às 21:00 BRT da véspera), registrado abaixo como melhoria opcional, fora do fix principal.

## Superfície afetada (todas com o mesmo padrão `.limit(10000)` + soma/agrupamento no cliente)

1. `api/stats/costs/route.ts` — cards de custo/tokens/chamadas (o bug reportado)
2. `api/stats/costs/daily/route.ts` — gráfico diário de IA
3. `api/stats/costs/breakdown/route.ts` — quebra por stage/modelo
4. `api/stats/costs/top-leads/route.ts` — ranking de leads por custo
5. `api/stats/whatsapp/route.ts` — cards de WhatsApp (tabela `messages`; janelas de 30 dias certamente >1000 linhas)
6. `api/stats/whatsapp/daily/route.ts` — gráfico diário de WhatsApp

## Abordagens consideradas

- **A) Agregar no SERVIDOR via RPC SQL (ESCOLHIDA).** Funções Postgres (`SECURITY INVOKER`, schema public com `GRANT` só ao service_role — as rotas usam `getServiceSupabase`) que devolvem os agregados prontos (`SUM`, `COUNT`, `COUNT(DISTINCT lead_id)`, `GROUP BY date/stage/model/lead`). Exatidão garantida pelo Postgres, 1 request por card, imune a crescimento de volume. Migração via runner unificado do repo.
- **B) Paginação `.range()` em loop nas rotas.** Sem migração, mas O(n) requests por render do dashboard, cresce sem teto com o volume (2.156 linhas hoje → dezenas de páginas em meses) e repete a lição do egress de 03/07 (não reintroduzir N+1). Rejeitada como solução definitiva; aceitável apenas como fallback.
- **C) Aggregate functions nativas do PostgREST (`select=total_cost.sum()`)**. Depende de flag de projeto (agregados vêm desabilitados por padrão no Supabase por precaução de performance) e não cobre `COUNT(DISTINCT)` composto do top-leads. Rejeitada.

## Solução (A)

1. **Migração SQL** (runner do repo, mesma migração p/ prod+homolog): 4 funções RPC —
   - `stats_costs_summary(p_start timestamptz, p_end timestamptz, p_stage text, p_model text, p_lead_id uuid)` → linha única: `total_cost, total_calls, total_prompt_tokens, total_completion_tokens, unique_leads`.
   - `stats_costs_daily(p_start, p_end, p_stage, p_model, p_lead_id)` → `GROUP BY date(created_at)`.
   - `stats_costs_breakdown(...)` → conforme dimensões atuais da rota (ler a rota antes; replicar contrato).
   - `stats_costs_top_leads(..., p_limit int)` → `GROUP BY lead_id ORDER BY SUM(total_cost) DESC`.
   - Equivalentes p/ WhatsApp (`stats_whatsapp_summary`, `stats_whatsapp_daily`) sobre `messages`, replicando os filtros atuais das rotas.
   - Filtros NULL-áveis (`p_stage IS NULL OR stage = p_stage`), `STABLE`, `SECURITY INVOKER`.
2. **Rotas** trocam o fetch-de-linhas por `sb.rpc("stats_..._...", {...})`, preservando **exatamente** o contrato JSON atual de cada rota (o frontend não muda).
3. **Contrato de datas preservado** neste fix: as rotas continuam recebendo `YYYY-MM-DD` e passando adiante (comparação UTC como hoje). A correção de fuso (interpretar o dia em BRT) fica registrada como follow-up separado — mudar as duas coisas juntas mascararia a validação do fix principal.

## Validação

- Réplica do script de diagnóstico (mesmas janelas) contra as RPCs no homolog/prod: `stats_costs_summary(7 dias)` ≡ verdade paginada (2.156 / 12.591.462 / $4,1303 na data da prova).
- Invariante de sanidade: para toda métrica, `Hoje ⊆ 7 dias ⊆ 30 dias` (monotonicidade) — teste de integração ou verificação manual pós-deploy no dashboard.
- `vitest` (frontend) e `pytest` (backend, não tocado) verdes; advisors do Supabase sem novos achados após a migração (funções em `public` com `GRANT EXECUTE` restrito — revogar de `anon`/`authenticated`, conceder a `service_role`).

## Critérios de aceite

1. Dashboard "7 dias" ≥ "Hoje" em todas as métricas, com valores batendo a verdade paginada.
2. Nenhuma rota de `/api/stats/*` faz agregação em JS sobre linhas cruas.
3. Zero mudança de contrato JSON (frontend intocado, exceto se algum campo já estiver morto — não remover neste fix).
4. Migração aplicada em homolog E prod (prod mediante autorização, junto com o deploy).

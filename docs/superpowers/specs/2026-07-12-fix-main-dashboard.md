# Novo Dashboard Principal (/dashboard) — KPIs de operação IA+SDR

**Data:** 2026-07-12 (v2 — escopo de produto redefinido pelo usuário após o cardápio de KPIs) · **Branch:** `fix/main-dashboard-data` · **Status:** spec aprovada em escopo, AGUARDANDO ordem de implementação.

## 1. Por que o dashboard atual mente (diagnóstico resumido, provado em prod)

1. KPIs de deals leem `deals.stage` (texto legado, congelado em `'novo'` — 0 ocorrências de `fechado_ganho` em 1.515 deals); a verdade é `stage_id → pipeline_stages`.
2. Hooks sem paginação → teto max-rows 1.000 (1.293 leads reais) + ordenação por coluna NULL = janela arbitrária → "Leads hoje" mostrava 0 com 17 reais.
3. `leads.first_response_at` (0/1.293) e `leads.last_msg_at` (10/1.293) são campos mortos — KPIs "Tempo de resposta" e "Chats sem resposta" nunca funcionaram.
4. Realtime table-wide com refetch completo (classe egress).

**Decisão de produto:** em vez de consertar KPIs de vaidade, o dashboard é RECRIADO com 13 métricas escolhidas pelo usuário. Componentes antigos quebrados (`FunnelChart`, `LeadSourcesChart`, `FunnelMovement`, os 6 KpiCards atuais) saem; `SlaTable`, `OverdueLeadsSection`, `OnlineUsersSection` e `ConversionsSection` (corretos) permanecem como drill-down abaixo dos novos blocos.

## 2. Os 13 KPIs escolhidos e sua verdade no banco (validada em produção 12/07)

### Cards de topo — Linha 1 "O motor hoje"
| # | KPI | Lógica (fonte validada) |
|---|---|---|
| 1 | **Leads novos hoje** (+tendência vs ontem) | `count(leads)` por dia LOCAL (`created_at AT TIME ZONE p_tz`); delta % vs dia anterior |
| 2 | **Leads ativos com a Valéria** (snapshot AGORA) | `leads.ai_enabled=true AND opt_out=false AND stage<>'perdido'` **E** `EXISTS` mensagem `role='user'` nas últimas 24h na(s) conversa(s) do lead. Drill-down no card: quantos "aguardando lead" (última msg é da IA) |
| 3 | **Conversas atendidas pela IA hoje** | `count(distinct conversation_id)` com ≥1 msg `role='user'` E ≥1 `role='assistant' AND sent_by='ai'` no dia local |
| 4 | **Handoffs (período)** | `count(messages)` com `role='system' AND content LIKE '[encaminhar_humano] Lead encaminhado%'` — marcador REAL validado (o `'Lead encaminhado%'` cru retorna 0; o prefixo da tool vem antes) |

### Cards de topo — Linha 2 "Qualidade e custo"
| # | KPI | Lógica |
|---|---|---|
| 5 | **Taxa de qualificação da IA** (período) | conversas com marcador `'[qualificar_lead]%'` ÷ conversas atendidas (item 3) no período |
| 6 | **SLA de resposta humana pós-handoff** (mediana em HORÁRIO COMERCIAL) | Por handoff (item 4): primeira msg `sent_by='human'` posterior na MESMA conversa; tempo = `business_seconds(handoff_ts, resposta_ts)` — função SQL que soma APENAS a interseção com janelas seg–sex 10h–16h BRT (ver §4). `percentile_cont(0.5)` + p95 como tooltip. Handoffs sem resposta ficam FORA da mediana (métrica de fila não foi escolhida) |
| 7 | **Custo de IA por handoff** (período) | `sum(token_usage.total_cost)` do período ÷ handoffs do período |
| 8 | **Custo por atendimento hoje** | `sum(total_cost where call_type LIKE 'response%')` ÷ `count(distinct lead_id)` dessas chamadas, no dia — mesma definição da auditoria de unit economics |

### Bloco "Conversão fim-a-fim" (gráfico de 3 estágios)
| 9 | **Lead → Handoff → Ganho** | Coorte por `leads.created_at` no período: total criados; % com handoff (item 4 por lead); % com deal `pipeline_stages.key='fechado_ganho'` (via `stage_id`, NUNCA `deals.stage`). Barras com contagem + % |

### Bloco "Outbound Frio" (funil de disparo)
| 10 | **Entregabilidade do disparo** | De `broadcasts` (filtro `template_name LIKE 'utilidade_%'` — restrição do usuário; template real validado: `utilidade_22_04_2026_16_40`) × `broadcast_leads`: `sent_at`/`delivered_at` → taxas sent→delivered |
| 11 | **Taxa de resposta do disparo frio** | `broadcast_leads.first_replied_at IS NOT NULL` ÷ `sent_at IS NOT NULL`, mesmo filtro `utilidade_%` (campo purpose-built validado em prod) |

### Bloco "Esteira de Follow-up"
| 12 | **Follow-ups agendados vs executados hoje** | `follow_up_jobs`: `count(fire_at::date local = hoje)` vs `count(sent_at::date local = hoje)` + abertos `status='pending'` vencidos — é o histograma-detector do postmortem da cadência morta, agora visível |
| 13 | **Retornos agendados pendentes** | `follow_up_jobs` `job_type IN ('ai_scheduled_return')` + jobs de `agendar_retorno` com `status='pending'`: contagem + próximo `fire_at` |

**Descartados pelo usuário:** origem de leads (mapeamento fraco), tempo de resposta da IA, funil por stage (explicado — pode entrar depois), categoria H inteira, aging, motivos de perda, composição da base.

## 3. Arquitetura — 4 RPCs + 1 helper (padrão /estatisticas)

Migração `20260712_dashboard_rpcs.sql` (aplicar prod+homolog via runner/Management API com autorização; `LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public`):

1. **`dashboard_business_seconds(t_start timestamptz, t_end timestamptz)`** — helper IMMUTABLE (ver §4).
2. **`dashboard_kpis(p_start date, p_end date, p_tz text)`** → 1 linha com itens 1,2,3,4,5,6,7,8 (item 2 é snapshot e ignora o período; itens com "hoje" fixo usam o dia local corrente; os demais respeitam p_start/p_end do seletor Hoje/7d/30d).
3. **`dashboard_funnel_conversion(p_start,p_end,p_tz)`** → item 9 (coorte).
4. **`dashboard_outbound_frio(p_start,p_end)`** → itens 10-11 (join broadcasts×broadcast_leads, filtro `template_name LIKE 'utilidade_%'`).
5. **`dashboard_followups(p_tz)`** → itens 12-13.

Rotas Next finas `/api/dashboard/{kpis,conversion,outbound,followups}` + mapper puro `src/lib/dashboard-mappers.ts` (testes vitest de contrato) + **matcher no `proxy.ts`** (obrigatório p/ rota /api/* nova). Página: fetch das 4 rotas com seletor de período (Hoje/7d/30d, mesmo padrão do /estatisticas), polling 60s, ZERO fetch de tabela inteira. `useRealtimeLeads`/`useRealtimeDeals` saem da página (permanecem p/ o Kanban).

## 4. SLA em horário comercial — a técnica SQL

Função pura de "segundos úteis" entre dois timestamps, janela seg–sex 10h–16h BRT:

```sql
-- Para cada dia entre início e fim (em BRT), soma a interseção do intervalo
-- [t_start, t_end] com a janela [dia 10:00, dia 16:00], pulando sáb/dom:
SELECT coalesce(sum(
  GREATEST(0, EXTRACT(EPOCH FROM (
    LEAST(t_end AT TIME ZONE 'America/Sao_Paulo', d + time '16:00')
    - GREATEST(t_start AT TIME ZONE 'America/Sao_Paulo', d + time '10:00')
  )))
), 0)
FROM generate_series(
  date_trunc('day', t_start AT TIME ZONE 'America/Sao_Paulo'),
  date_trunc('day', t_end   AT TIME ZONE 'America/Sao_Paulo'),
  interval '1 day') AS d
WHERE EXTRACT(ISODOW FROM d) BETWEEN 1 AND 5;
```

Semântica resultante (a pinar em teste SQL): handoff sexta 20h respondido segunda 10h05 → SLA = 5 min (o relógio só anda dentro da janela); handoff e resposta dentro da mesma janela → diferença direta; resposta fora da janela → conta só o trecho útil decorrido. Feriados NÃO são tratados (sem tabela de feriados — limitação aceita e documentada no tooltip do card).

## 5. Critérios de aceite
- Cada RPC validada contra queries diretas de produção ANTES do frontend (leads hoje = contagem real; handoffs batem com o daily_qa; broadcast batem com contadores da tabela `broadcasts`).
- `business_seconds` com teste SQL de 4 cenários (mesma janela, overnight, fim de semana, resposta fora da janela).
- Nenhuma resposta de rota > algumas dezenas de linhas; página sem `select("*")` de tabela.
- vitest verde (mappers novos + regressão); layout segue o design system atual (cards 2×4 + 3 blocos).

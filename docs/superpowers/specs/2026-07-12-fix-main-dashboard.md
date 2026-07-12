# Fix do Dashboard Principal (/dashboard) — diagnóstico e arquitetura da correção

**Data:** 2026-07-12 · **Branch:** `fix/main-dashboard-data` · **Status:** DIAGNÓSTICO APROVADO PENDENTE — nenhuma alteração de código feita.
**Método:** leitura do código (página, 2 hooks, 7 subcomponentes, constants, migrações) + queries read-only no Supabase de PRODUÇÃO comparando a UI com a verdade do banco.

---

## 1. POR QUE o dashboard está errado — os furos, com prova de produção

### F1 (CRÍTICO) — Todos os KPIs de deals leem a coluna ERRADA
`page.tsx:83-117` e `funnel-movement.tsx:28-47` filtram por **`deals.stage`** (texto legado, default `'novo'`) usando as keys hardcoded de `DEAL_STAGES` (`constants.ts:9-16`). A fonte de verdade desde a migração `012_multi_pipeline` é **`deals.stage_id → pipeline_stages`** — é o que o Kanban usa, e NADA no sistema atualiza `deals.stage` (insert grava `'novo'` fixo; o PATCH do Kanban só manda `stage_id`).
**Prova (prod):** distribuição real de `deals.stage`: `novo=1300, respondeu=105, ja_chamado=52, qualificado=37, perdido=20, fechado_perdido=1` — **`fechado_ganho` = 0 ocorrências**; enquanto `pipeline_stages` tem 52 stages reais em 10 pipelines (com "Fechado Ganho"/"Perdido" e `stage_id` populado em 1515/1515 deals).
**Efeito na tela:** "Deals ganhos" = 0 para sempre; "Deals perdidos" ≈ 0; "Deals ativos" conta e soma TUDO (inflado); FunnelChart joga ~86% dos deals na coluna "Novo"; FunnelMovement "Perdidos no período" = 0 para sempre.

### F2 (CRÍTICO) — Teto silencioso de 1.000 linhas + janela arbitrária
`use-realtime-leads.ts` e `use-realtime-deals.ts` fazem `select("*")` **sem `.limit()`/`.range()`** → o max-rows do PostgREST corta em 1.000 (mesma assinatura do incidente do /estatisticas).
**Prova (prod):** existem **1.293 leads** e **1.515 deals**. Pior: o hook de leads ordena por `last_msg_at` — que é NULL em 99% das linhas (ver F4) — então a janela de 1.000 é **arbitrária**: medido, ela cobre 27/02→11/07 e **os 17 leads criados HOJE ficam FORA**.
**Efeito na tela:** **"Leads hoje" renderiza 0 com 17 leads reais** — a queixa "não está atualizado" é literalmente isso. Todos os KPIs/gráficos de leads operam sobre ~77% dos dados, virados para o passado.

### F3 (CRÍTICO) — KPI "Tempo de resposta" lê um campo MORTO
`page.tsx:97-104` usa `leads.first_response_at`. **Prova (prod): 0 de 1.293 leads têm o campo preenchido** — grep no backend confirma que NENHUM código escreve nele.
**Efeito:** KPI mostra "—" desde sempre.

### F4 (CRÍTICO) — KPI "Chats sem resposta" lê coluna que o backend não popula
`page.tsx:92-95` usa `leads.last_msg_at`; o backend escreve em **`conversations.last_msg_at`** (o campo de leads tem 10/1.293 preenchidos, resíduo legado). Além disso a lógica está conceitualmente errada: `last_msg_at < 1h atrás && !human_control` marcaria como "sem resposta" qualquer conversa antiga — não distingue quem falou por último.
**Efeito:** KPI = 0 sempre (falso negativo permanente).

### F5 (ESTRUTURAL) — Realtime caro e inútil
`use-realtime-deals` assina `postgres_changes` **table-wide** e refaz o fetch COMPLETO (com joins de leads+stages) a cada mudança de qualquer deal — padrão da classe do incidente de egress. Já `leads` nem está na publicação realtime e o hook não assina nada → os KPIs de leads só atualizam no mount.

### F6 (MENOR) — Gráfico de origens com buckets fantasmas
`LeadSourcesChart` agrupa por `leads.metadata->>origem`, mas: (a) só leads de LP têm o campo; (b) as keys de `LP_ORIGINS` (`graocafeteria/atacado/terceirizacao`) divergem dos valores crus que a LP grava (`landing-page-atacado`, `terceirizacaocafe`, `cafeatacado`) → quase tudo cai em "Não identificado".

### F7 (MENOR/cosmético) — Nomes reais hardcoded
`online-users-section.tsx:27-38`: cores de avatar chumbadas para "Arthur/Rafael/Kelwin/João".

### O que JÁ está correto (não mexer)
`SlaTable` e `OverdueLeadsSection` (paginam com `.range()` em loop — únicos imunes ao teto — e escopam por papel), `ConversionsSection` (proxy → FastAPI, dados reais), `FunnelChart`/`KpiCard` (apresentacionais puros). Não há mocks de dados nos componentes — o dashboard mente por ler colunas mortas e janelas truncadas, não por dados fake.

---

## 2. Arquitetura da correção (mesmo playbook que salvou o /estatisticas)

**Princípio: agrega no Postgres, exibe no cliente.** Nenhuma tabela inteira viaja ao browser para virar `filter/reduce`.

### 2.1 Migração `20260712_dashboard_rpcs.sql` — 3 RPCs SQL (STABLE, mesmo padrão de `20260711_stats_aggregation_rpcs`)
1. **`dashboard_kpis(p_tz text default 'America/Sao_Paulo')`** → 1 linha: `leads_today` (contagem por dia LOCAL, não UTC), `active_deals_count/value`, `won_deals_count/value`, `lost_deals_count/value` — **via `stage_id → pipeline_stages.key`** (`fechado_ganho`/`fechado_perdido`; ativos = resto), `unanswered_chats` (de **`conversations`**: última mensagem é do cliente E sem resposta há >1h E `ai_enabled=false` OU sem humano atribuído — definição correta de "esperando resposta"), `avg_first_response_minutes` (janela 30d, window function sobre `messages`: primeira `assistant/human` após a primeira `user` de cada conversa — cálculo real, sem depender do campo morto).
2. **`dashboard_funnel()`** → contagem + soma de `value` por `pipeline_stages` (agregado por `label` normalizado, com `order_index` e por pipeline p/ filtro futuro), lendo `stage_id`.
3. **`dashboard_lead_sources()`** → contagem por `coalesce(metadata->>'origem','whatsapp')` com normalização dos valores REAIS gravados pela LP (mapear `landing-page-atacado`→Atacado etc.) feita no SQL.

### 2.2 Rotas Next `/api/dashboard/kpis|funnel|sources`
Finas: `sb.rpc(...)` + mapper puro em `src/lib/dashboard-mappers.ts` (testável em vitest, mesmo padrão de `stats-mappers`). **Atenção obrigatória:** rota `/api/*` nova exige matcher no `proxy.ts` (lição registrada do painel Follow-up).

### 2.3 Página
- KPIs/FunnelChart/LeadSourcesChart/FunnelMovement passam a ler as rotas agregadas (fetch único + `useEffect`), removendo `useRealtimeLeads`/`useRealtimeDeals` da página (os hooks PERMANECEM para o Kanban, que os usa por pipeline).
- Atualização: polling leve de 60s + refresh no focus (agregados custam ~1 query cada) — substitui o realtime table-wide. Zero mudança visual de layout.
- `FunnelMovement` "perdidos no período" via `closed_at` + `key='fechado_perdido'` (dados já existem).
- LeadSourcesChart consome a RPC (buckets normalizados no SQL).
- F7: derivar cor de avatar por hash da inicial (remove nomes chumbados).

### 2.4 Decisões explícitas
- **NÃO ressuscitar** `leads.first_response_at`/`leads.last_msg_at` (colunas mortas; a verdade vive em `conversations`/`messages` — criar writer novo duplicaria estado). Documentá-las como deprecated.
- **NÃO segmentar por vendedor nesta fase**: leads é deliberadamente não-segmentado (decisão RLS registrada) e os KPIs são visão de operação; SLA/Overdue continuam com o escopo por papel que já têm.
- RPCs com `security definer` + `set search_path` espelhando as stats RPCs (RLS-safe), aplicadas em prod+homolog com ledger do runner.
- `DEAL_STAGES` legado: manter apenas se outro consumidor usar (verificar no plano); o dashboard deixa de importá-lo.

### 2.5 Critérios de aceite
- "Leads hoje" do dashboard == `select count(*) from leads where created_at::date (BRT) = hoje` (17 no dia da auditoria).
- Ganhos/perdidos/ativos batem com o Kanban (contagem por `stage_id`).
- Nenhuma query da página retorna >100 linhas ao browser.
- vitest verde (mappers novos + existentes); página sem regressão visual de layout.

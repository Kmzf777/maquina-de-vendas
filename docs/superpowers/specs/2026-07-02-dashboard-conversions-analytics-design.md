# Design — Seção "Conversões (Ads)" no Dashboard (analytics, admin-only)

**Data:** 2026-07-02
**Branch:** feat/ad-conversion-attribution
**Status:** aprovado no brainstorming

## 1. Problema
A seção de conversões no Dashboard está básica (só cards de contagem). Precisa de
**métricas reais e gráficos**, com foco em **orgânico × tráfego pago**, e ser visível
**somente para administradores**.

## 2. Decisões (brainstorming)
- **Gráficos escolhidos:** (1) Orgânico × Pago (leads por `traffic_type`), (2) Conversões no
  tempo (30 dias, empilhado por etapa), (3) Valor por origem / ROI (vendas pago × orgânico).
  **Fora:** funil por etapa, filtros de período configuráveis, drill-down por campanha (YAGNI).
- **Admin-only:** UI via `useCurrentRole()` + guard de sessão nos proxies Next.js.
- **Gráficos:** recharts (já usado em `estatisticas/page.tsx`).

## 3. Visibilidade / segurança
- **UI:** `ConversionsSection` usa `useCurrentRole()`; `role !== "admin"` (ou `loading`) →
  retorna `null` (some do Dashboard p/ vendedores).
- **Servidor (defesa real — o CSV MUTA dados via `exported_at`):** os proxies Next.js
  `/api/conversions/*` chamam `getCurrentUser()` (de `lib/supabase/pipeline-access.ts`,
  resolve role dos cookies, fail-closed) e retornam **403** se `role !== "admin"`. Aplica-se a
  `google-export`, `stats` e o novo `dashboard`.

## 4. Backend — `GET /api/conversions/dashboard`
Um endpoint compõe tudo (fail-soft: erro/tabela ausente → zeros):
```json
{
  "kpis": { "google_pending": 3, "google_exported": 5, "meta_sent": 8, "purchase_value": 11500 },
  "traffic_split": { "paid": 124, "organic": 62, "unknown": 14 },
  "timeseries": [ { "date": "2026-06-03", "qualified": 2, "opportunity": 1, "purchase": 0 }, "... 30 dias" ],
  "value_by_traffic": { "paid": 8400, "organic": 3100, "unknown": 0 }
}
```
Fontes e funções puras (testáveis) em `app/campaigns/conversion_analytics.py`:
- `traffic_split`: 3 `count` queries em `leads` por `traffic_type` (paid / organic / IS NULL→unknown).
- `timeseries` + `value_by_traffic`: fetch de `conversion_events` (últimos 30 dias p/ série;
  `event='purchase'` com join `leads(traffic_type)` p/ valor por origem).
  - `build_timeseries(events, days=30, today)` → lista de 30 dias, cada um
    `{date, qualified, opportunity, purchase}`, **preenchendo dias sem evento com zero**.
  - `aggregate_value_by_traffic(purchase_rows)` → `{paid, organic, unknown}` somando `value`
    pelo `traffic_type` do lead (linha sem lead/tipo → `unknown`).
- `kpis`: reusa `conversion_stats()` existente (`google_export.py`).
- Registrado no router `conversions_router.py` (prefixo `/api/conversions`). O `/stats` atual
  permanece (inofensivo).

## 5. Frontend — `ConversionsSection` (recharts + shadcn, admin-gated)
Arquivo: `frontend/src/components/dashboard/conversions-section.tsx` (reescrito).
- Gating: `const { role, loading } = useCurrentRole(); if (loading || role !== "admin") return null;`
- Fetch `/api/conversions/dashboard` (proxy novo). Loading = skeleton; erro/sem dados = estado discreto.
- Layout:
  - KPIs (cards): Pendentes p/ Google (destaque), Exportadas, Enviadas ao Meta, Valor em vendas (BRL).
  - 3 gráficos (recharts, `ResponsiveContainer`):
    - **Orgânico × Pago** — `PieChart` (donut) do `traffic_split` (paid/organic/unknown).
    - **Conversões / dia (30d)** — `BarChart` empilhado por etapa (qualified/opportunity/purchase).
    - **Valor por origem** — `BarChart` (paid vs organic, R$).
  - Rodapé: badges por evento + botão "Baixar conversões Google (CSV)" (+ nº pendentes).
- Paleta warm-neutral do dashboard (`#111111`, `#dedbd6`, `#7b7b78`, cards brancos). Cores dos
  gráficos: pago = tom escuro/accent, orgânico = tom médio, unknown = cinza.

Proxies Next.js (todos com guard admin via `getCurrentUser()`):
- Novo `app/api/conversions/dashboard/route.ts` (GET JSON).
- Atualizar `app/api/conversions/google-export/route.ts` e `stats/route.ts` c/ o mesmo guard 403.

## 6. Testes
- **Backend:** `test_conversion_analytics.py` — `build_timeseries` (preenche dias zerados, agrupa
  por etapa, respeita janela), `aggregate_value_by_traffic` (soma por traffic_type, unknown p/
  sem tipo), e a composição do dashboard (mockando as queries). Mesma linha de `test_google_export.py`.
- **Frontend:** `npm run type-check` (`tsc --noEmit`) e build limpos nos arquivos tocados.
  (Lição registrada: rodar `type-check` — mais rígido que o build Turbopack — antes de subir.)

## 7. Fora de escopo
Funil por etapa; seletor de período; drill-down por campanha/UTM; paginação/limite de janela
além dos 30 dias (o fetch de `conversion_events` p/ série é limitado a 30 dias; KPIs seguem full).

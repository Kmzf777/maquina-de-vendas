# CRM Kommo Migration - Design Spec

**Date:** 2026-03-27
**Goal:** Evolve the ValerIA CRM from its current minimal state to match the most important features of Kommo CRM, following an incremental page-by-page approach while keeping the existing light/olive design system.

---

## 1. Lead Model Evolution

### New B2B Fields (all nullable strings)
- `cnpj`
- `razao_social`
- `nome_fantasia`
- `endereco`
- `telefone_comercial`
- `email`
- `instagram`
- `inscricao_estadual`

### Sale Value
- `sale_value` — numeric, default 0. Manually entered by the seller.

### Metric Fields
- `entered_stage_at` — timestamp, auto-updated when `stage` or `seller_stage` changes. Used to calculate "days in stage".
- `first_response_at` — timestamp, nullable. Set when the first seller/agent reply is sent.
- `on_hold` — boolean, default false. Used by the "Colocar em espera" action.

### TypeScript Interface Update
The `Lead` interface in `src/lib/types.ts` mirrors all new columns.

### SQL Migration
Single migration file: `ALTER TABLE leads ADD COLUMN ...` for each new field. No data backfill needed — all new fields are nullable or have defaults.

---

## 2. Enriched Kanban (Qualificacao + Vendas)

### Card Enrichment
Each kanban card displays:
- Lead name (existing)
- Company/nome fantasia (new)
- Sale value badge: `R$ 1.600` in green (new)
- Days in stage: `37d` with red indicator if > 30 days (new, from `entered_stage_at`)
- Last message preview, truncated (new)
- Lead tags as colored badges (new)
- Unread message indicator (new)

Both Qualificacao and Vendas pages share the same enriched card component (`LeadCard`), differing only in which stages they display.

### Top Metrics Bar
A horizontal bar above the kanban columns showing:
- Total leads in funnel + total R$ value
- "Novo hoje / ontem" — count of leads created today vs yesterday
- "Vendas em potencial" — sum of `sale_value` for active leads

### Quick Add
- "+ Adicao rapida" button at the top of each column
- Inline form: name, phone, company (minimum viable)
- Creates lead in the corresponding stage

### Filters
- Toggle "Leads ativos" — hides leads with seller_stage = "perdido" or "fechado"
- Search by name/company/phone

---

## 3. Dashboard Overhaul

### KPI Cards (first row, 6 cards)
| KPI | Source |
|---|---|
| Leads hoje | `created_at >= today` |
| Leads ativos + R$ | `status = active`, sum of `sale_value` |
| Leads ganhos + R$ | `seller_stage = fechado`, sum of `sale_value` |
| Leads perdidos + R$ | `seller_stage = perdido`, sum of `sale_value` |
| Chats sem resposta | Leads where last message is from user (role = "user") and was sent > 1 hour ago with no seller/agent reply since |
| Tempo de resposta medio | Average of `first_response_at - created_at` |

### Lead Sources Chart (new — donut)
- Groups leads by `channel` field (evolution, campaign, manual, etc.)
- Donut/pie chart with legend
- Keeps the olive/earth color palette

### Funnel Movement Bar (new — bottom section, Kommo style)
- For each funnel stage: how many entered (+) and exited (-) within the selected period
- R$ value per stage
- "Perda" row at the bottom
- Period filter: today, 7 days, 30 days

### Existing Widgets
- Funnel chart stays, enhanced with R$ values per stage
- Campaign metrics table stays as-is

---

## 4. Enriched Conversas

### ContactDetail Panel (right sidebar) — enriched
All B2B fields displayed and **editable inline** (click to edit, save on blur/enter):
- CNPJ, Razao Social, Nome Fantasia, Endereco, Telefone Comercial, Email, Instagram, Inscricao Estadual
- Sale value with R$ mask, editable
- Tags toggle (already works)
- Seller stage selector (already works)

### Contact Stats (new section in right panel)
- Days active (since `created_at`)
- Total messages exchanged (count)
- Lead source (`channel`)

### Action Buttons (new — top of chat view)
- "Fechar conversa" — sets `seller_stage = perdido`
- "Colocar em espera" — sets `on_hold = true`, visual indicator in chat list

### Audio Player (new)
- When a message is of type `audioMessage`, render an inline player inside the message bubble
- Controls: play/pause, progress bar, duration display
- Compact style matching the existing chat bubble design

### Out of Scope
- Media tab (gallery of shared photos/docs) — deferred to a future iteration

---

## 5. Estatisticas Page (new)

### Route
`/estatisticas` — new entry in the sidebar navigation.

### Layout
Left sidebar navigation within the page (like Kommo):
- Analise de vendas
- Relatorio de tempo
- Relatorio por vendedor

Content area on the right.

### Analise de Vendas (main view)
- Table: columns = funnel stages, rows = "Dentro da etapa" / "Entrou na etapa" / "Perda"
- Each cell: lead count + R$ value
- Colored bar at top of each column matching stage color
- Period filter

### Relatorio de Tempo
- Average time in each stage (days)
- Average first response time
- Leads stuck > X days (red highlight)
- Bottleneck ranking (stages where leads stay longest)

### Relatorio por Vendedor
- Table: vendedor | leads ativos | leads ganhos | leads perdidos | valor total | taxa de conversao
- Period filter (7d, 30d, 90d, custom)
- Sortable by any column

### Global Filters
- Period selector: presets (hoje, 7d, 30d, 90d) + custom date range
- Funnel filter (Qualificacao vs Vendas)

---

## 6. Technical Approach

### Incremental Order
1. SQL migration + TypeScript types (base)
2. Kanban enrichment (LeadCard, metrics bar, quick add, filters)
3. Dashboard overhaul (new KPIs, donut chart, funnel movement)
4. Conversas enrichment (B2B fields, actions, audio player)
5. Estatisticas page (new route + 3 reports)

### Data Layer
- All data comes from Supabase (existing setup)
- Realtime hooks already exist for leads, messages, campaigns — reuse them
- New queries for aggregated stats can use Supabase `.rpc()` or client-side computation for now
- `entered_stage_at` updated via Supabase trigger or client-side on stage change

### Charts
- Donut chart and bar charts: lightweight implementation with SVG or a small library (recharts if already in deps, otherwise pure SVG)

### Design System
- Keep existing light theme with olive/earth tones
- Cards get richer but maintain same border-radius, shadows, font sizes
- New badges use the existing color palette from `constants.ts`

### No Breaking Changes
- All new lead fields are nullable/defaulted — existing leads continue to work
- Existing components get enhanced, not replaced
- Sidebar gains one new item (Estatisticas)

# Leads Page Design

## Overview

Standalone `/leads` page for the ValerIA CRM. Provides full lead management: listing with temperature-based KPIs, filtering, individual lead details with editing, manual lead creation, and bulk CSV import.

## Data Source

- **Hook**: `useRealtimeLeads()` (already exists) — fetches all leads ordered by `last_msg_at`, subscribes to realtime changes
- **Temperature**: Calculated client-side from `last_msg_at`:
  - Quente: < 48h
  - Morno: 48h - 7d
  - Frio: > 7d or null
- **Tags**: Fetched via `lead_tags` join table
- **Sidebar**: Add "Leads" nav item to `sidebar.tsx` (between Qualificacao and Vendas)

## Page Structure

### Header
- Title "Leads" + subtitle "Gestao completa dos seus contatos"
- 3 action buttons:
  - "Novo Lead" (primary, dark) — opens create modal
  - "Importar" — opens CSV import modal
  - "Exportar" — downloads current filtered view as CSV

### KPI Bar (5 cards, 1 row)
| Card | Value | Color |
|------|-------|-------|
| Total de Leads | count(all) | neutral |
| Quentes | count(temp = quente) | #f87171 red dot |
| Mornos | count(temp = morno) | #e8d44d yellow dot |
| Frios | count(temp = frio) | #60a5fa blue dot |
| Valor Total Pipeline | sum(sale_value) | #4ade80 green |

### Filter Bar
- Search input: busca por nome, telefone, empresa
- Dropdowns: Temperatura, Stage, Seller Stage, Tags, Canal
- Active filter chips (removable)
- Counter: "Mostrando X de Y leads"
- "Limpar" button to reset all filters

### Lead Cards Grid (3 columns)
Each card shows:
- Left border colored by temperature (red/yellow/blue)
- Avatar (initials) + name + phone
- Temperature badge (top-right)
- Tags as chips (stage + custom tags)
- Company name + sale_value
- Footer: seller_stage + time since last message

### Pagination
- Page navigation at bottom
- 30 leads per page

## Lead Detail Modal

Opens when clicking a card. Full-width modal (max-width 720px).

### Header
- Avatar + name + phone/company + temperature badge + close button

### Tab 1: Dados Gerais (editable)
Two-column layout:

**Coluna Contato:**
- name (text input)
- phone (text input, readonly — unique identifier)
- email (text input)
- instagram (text input)
- channel (select)

**Coluna Empresa B2B:**
- razao_social (text input)
- nome_fantasia (text input)
- cnpj (text input)
- telefone_comercial (text input)
- endereco (text input)

**Status CRM (4 cards, editable):**
- Stage (select: secretaria, atacado, private_label, exportacao, consumo)
- Seller Stage (select: novo, em_contato, negociacao, fechado, perdido)
- Assigned To (select from users or text)
- Sale Value (numeric input, formatted as R$)

**Save**: "Salvar alteracoes" button appears when fields are dirty. PATCH via `/api/leads/[id]` route.

### Tab 2: Campanhas
- List of campaigns the lead is part of (via `cadence_state` join)
- Each campaign card shows:
  - Campaign name + creation date
  - Status badge (ativa, respondeu, exaurida, cooled)
  - 3 mini-cards: cadence progress, messages sent, next send / response date

### Tab 3: Tags & Notas
**Tags section:**
- Current tags as removable chips
- "Adicionar tag" button — select from existing tags or create new
- Uses existing `/api/leads/[id]/tags` route

**Timeline section (merged manual notes + automatic events):**
- Sorted chronologically (newest first)
- Manual notes: author + timestamp + text content, with "Add note" input at top
- Automatic events (styled differently, e.g., lighter background):
  - Stage change: "Stage alterado de X para Y"
  - Seller stage change: "Etapa vendas alterada de X para Y"
  - Campaign entry/exit: "Adicionado a campanha X" / "Removido de campanha X"
  - First response: "Primeira resposta recebida"
- Notes stored in a new `lead_notes` table
- Automatic events derived from existing data (stage changes from `entered_stage_at` trigger, campaign events from `cadence_state`)

### Tab 4: Metricas
- 3 KPI cards: Temperatura (with emoji + time), Valor Venda, Tempo 1a Resposta
- Stage timeline: horizontal bars showing time spent in each stage
- Engagement: 4 cards — messages exchanged (from messages table), campaigns count, days in CRM, response rate

## Novo Lead Modal

Simple form with fields:
- **Required**: Nome, Telefone
- **Optional**: Email, Instagram, Empresa (company), CNPJ
- **Selects**: Stage (default: none), Seller Stage (default: "novo"), Canal (default: "evolution")
- **Submit**: "Criar Lead" button
- Insert via Supabase, realtime hook auto-updates the list
- Validation: phone must be unique (show error if duplicate)

## Importar CSV Modal

3-step wizard:

### Step 1: Upload
- Drag & drop zone or file picker (accepts .csv)
- Parse and show preview table of first 5 rows
- Show total row count

### Step 2: Mapeamento de Colunas
- For each CSV column, a dropdown to map to a lead field (nome, phone, email, instagram, company, cnpj, razao_social, nome_fantasia, endereco, telefone_comercial, stage, seller_stage)
- Auto-detect mapping by column header name (e.g., "telefone" -> phone, "nome" -> name)
- Option to skip columns

### Step 3: Confirmacao
- Summary: "X leads serao importados"
- Duplicate handling: "Y leads ja existem (por telefone)" with option to skip or update
- "Importar" button
- Progress bar during import
- API route: POST `/api/leads/import` — upserts by phone field

## New Database Objects

### `lead_notes` table
```sql
CREATE TABLE lead_notes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    author text NOT NULL,
    content text NOT NULL,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX idx_lead_notes_lead_id ON lead_notes(lead_id);
```

### `lead_events` table (automatic activity log)
```sql
CREATE TABLE lead_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    event_type text NOT NULL, -- 'stage_change', 'seller_stage_change', 'campaign_added', 'campaign_removed', 'first_response'
    old_value text,
    new_value text,
    metadata jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX idx_lead_events_lead_id ON lead_events(lead_id);
```

## Tech Notes

- Page route: `crm/src/app/(authenticated)/leads/page.tsx`
- Follow existing patterns: "use client", hooks for data, loading skeletons
- Reuse design system: bg `#f6f7ed`, cards with `border: 1px solid #e5e5dc`, rounded-xl, DM Sans font
- Temperature calculation: shared utility function (used in KPIs, cards, and modal)
- CSV parsing: use `papaparse` library (lightweight, handles edge cases)
- All editing via API routes (not direct Supabase client mutations) for consistency

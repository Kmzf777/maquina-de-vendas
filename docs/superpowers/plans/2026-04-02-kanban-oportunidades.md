# Kanban de Oportunidades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/vendas` lead kanban with a deals/opportunities pipeline, introducing a `deals` table, rewriting the kanban page, updating the dashboard, and cleaning up all `seller_stage`/`sale_value` references across the CRM.

**Architecture:** New `deals` table in Supabase with FK to `leads`. Frontend uses a new `useRealtimeDeals()` hook. The `/vendas` page becomes a deal kanban with drag-and-drop. Dashboard KPIs and funnel read from deals. All components that referenced `seller_stage`/`sale_value` on leads are updated or cleaned up. Backend `encaminhar_humano` tool creates a deal instead of setting `seller_stage`.

**Tech Stack:** Supabase (PostgreSQL), Next.js (App Router), React, @dnd-kit/core, TypeScript

---

### Task 1: Database migration — create `deals` table and migrate data

**Files:**
- Create: `backend-evolution/migrations/009_deals.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 009_deals.sql
-- Create deals table and migrate existing seller pipeline data

-- 1. Create deals table
CREATE TABLE IF NOT EXISTS deals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    title text NOT NULL,
    value numeric(12,2) DEFAULT 0,
    stage text NOT NULL DEFAULT 'novo',
    category text,
    expected_close_date date,
    assigned_to text,
    closed_at timestamptz,
    lost_reason text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deals_lead_id ON deals(lead_id);
CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
CREATE INDEX IF NOT EXISTS idx_deals_category ON deals(category);

-- 2. Migrate existing lead data to deals
INSERT INTO deals (lead_id, title, value, stage, created_at)
SELECT
  id,
  COALESCE(name, phone) || ' - Oportunidade',
  COALESCE(sale_value, 0),
  CASE seller_stage
    WHEN 'novo' THEN 'novo'
    WHEN 'em_contato' THEN 'contato'
    WHEN 'negociacao' THEN 'negociacao'
    WHEN 'fechado' THEN 'fechado_ganho'
    WHEN 'perdido' THEN 'fechado_perdido'
    ELSE 'novo'
  END,
  created_at
FROM leads
WHERE human_control = true
  AND seller_stage IS NOT NULL
  AND seller_stage != '';

-- 3. Drop deprecated columns from leads
ALTER TABLE leads DROP COLUMN IF EXISTS seller_stage;
ALTER TABLE leads DROP COLUMN IF EXISTS sale_value;

-- 4. Enable realtime for deals
ALTER PUBLICATION supabase_realtime ADD TABLE deals;
```

- [ ] **Step 2: Run the migration in Supabase SQL Editor**

Copy the SQL above and execute it in the Supabase SQL Editor. Verify:
- `deals` table exists with correct columns
- Data was migrated (run `SELECT COUNT(*) FROM deals`)
- `leads` table no longer has `seller_stage` or `sale_value` columns
- Realtime is enabled for `deals`

- [ ] **Step 3: Commit**

```bash
git add backend-evolution/migrations/009_deals.sql
git commit -m "feat: add deals table migration with data migration from leads"
```

---

### Task 2: Update types and constants

**Files:**
- Modify: `crm/src/lib/types.ts`
- Modify: `crm/src/lib/constants.ts`

- [ ] **Step 1: Add Deal type and remove deprecated Lead fields**

In `crm/src/lib/types.ts`, add the `Deal` interface and remove `seller_stage` and `sale_value` from `Lead`:

Remove these lines from the `Lead` interface:
```typescript
  seller_stage: string;
  sale_value: number;
```

Add this new interface after the `Lead` interface:
```typescript
export interface Deal {
  id: string;
  lead_id: string;
  title: string;
  value: number;
  stage: string;
  category: string | null;
  expected_close_date: string | null;
  assigned_to: string | null;
  closed_at: string | null;
  lost_reason: string | null;
  created_at: string;
  updated_at: string;
  // Joined fields
  leads?: {
    id: string;
    name: string | null;
    company: string | null;
    phone: string;
    nome_fantasia: string | null;
  };
}
```

- [ ] **Step 2: Replace SELLER_STAGES with DEAL_STAGES in constants**

In `crm/src/lib/constants.ts`, replace the `SELLER_STAGES` export:

Remove:
```typescript
export const SELLER_STAGES = [
  { key: "novo", label: "Novo", color: "bg-[#f0d8d8]", dotColor: "#e07a7a", tintColor: "#f6eeee", avatarColor: "#e07a7a" },
  { key: "em_contato", label: "Em Contato", color: "bg-[#f0e4d0]", dotColor: "#d4a04a", tintColor: "#f4f0ea", avatarColor: "#d4a04a" },
  { key: "negociacao", label: "Negociacao", color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5b8aad" },
  { key: "fechado", label: "Fechado", color: "bg-[#d8f0dc]", dotColor: "#5aad65", tintColor: "#edf4ef", avatarColor: "#5aad65" },
  { key: "perdido", label: "Perdido", color: "bg-[#f4f4f0]", dotColor: "#9ca3af", tintColor: "#f2f2f0", avatarColor: "#9ca3af" },
] as const;
```

Add:
```typescript
export const DEAL_STAGES = [
  { key: "novo", label: "Novo", color: "bg-[#f0d8d8]", dotColor: "#e07a7a", tintColor: "#f6eeee", avatarColor: "#e07a7a" },
  { key: "contato", label: "Contato", color: "bg-[#f0e4d0]", dotColor: "#d4a04a", tintColor: "#f4f0ea", avatarColor: "#d4a04a" },
  { key: "proposta", label: "Proposta", color: "bg-[#e8dff0]", dotColor: "#9b7abf", tintColor: "#f0edf4", avatarColor: "#9b7abf" },
  { key: "negociacao", label: "Negociacao", color: "bg-[#dce8f0]", dotColor: "#5b8aad", tintColor: "#eef2f6", avatarColor: "#5b8aad" },
  { key: "fechado_ganho", label: "Fechado Ganho", color: "bg-[#d8f0dc]", dotColor: "#5aad65", tintColor: "#edf4ef", avatarColor: "#5aad65" },
  { key: "fechado_perdido", label: "Perdido", color: "bg-[#f4f4f0]", dotColor: "#9ca3af", tintColor: "#f2f2f0", avatarColor: "#9ca3af" },
] as const;

export const DEAL_CATEGORIES = [
  { key: "atacado", label: "Atacado", color: "#5b8aad" },
  { key: "private_label", label: "Private Label", color: "#9b7abf" },
  { key: "exportacao", label: "Exportacao", color: "#5aad65" },
  { key: "consumo", label: "Consumo", color: "#d4b84a" },
] as const;
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/lib/types.ts crm/src/lib/constants.ts
git commit -m "feat: add Deal type and DEAL_STAGES constants, remove seller_stage from Lead"
```

---

### Task 3: Create `useRealtimeDeals` hook

**Files:**
- Create: `crm/src/hooks/use-realtime-deals.ts`

- [ ] **Step 1: Write the hook**

Create `crm/src/hooks/use-realtime-deals.ts`:

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Deal } from "@/lib/types";

export function useRealtimeDeals() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchDeals = useCallback(async () => {
    const { data } = await supabase
      .from("deals")
      .select("*, leads(id, name, company, phone, nome_fantasia)")
      .order("updated_at", { ascending: false });
    if (data) setDeals(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchDeals();

    const channel = supabase
      .channel("deals-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "deals" },
        () => {
          fetchDeals();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchDeals]);

  return { deals, loading };
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd crm && npx tsc --noEmit --pretty 2>&1 | head -20`

This will likely show errors in other files that still reference `seller_stage`/`sale_value` — that's expected at this point and will be fixed in subsequent tasks.

- [ ] **Step 3: Commit**

```bash
git add crm/src/hooks/use-realtime-deals.ts
git commit -m "feat: add useRealtimeDeals realtime hook"
```

---

### Task 4: Create deals API route

**Files:**
- Create: `crm/src/app/api/deals/route.ts`

- [ ] **Step 1: Write the API route**

Check the Next.js docs first: read `crm/node_modules/next/dist/docs/` for any breaking changes in route handlers.

Create `crm/src/app/api/deals/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET() {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("deals")
    .select("*, leads(id, name, company, phone, nome_fantasia)")
    .order("updated_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await createClient();

  const { data, error } = await supabase
    .from("deals")
    .insert({
      lead_id: body.lead_id,
      title: body.title,
      value: body.value || 0,
      stage: "novo",
      category: body.category || null,
      expected_close_date: body.expected_close_date || null,
      assigned_to: body.assigned_to || null,
    })
    .select("*, leads(id, name, company, phone, nome_fantasia)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Create deals/[id] route for PATCH and DELETE**

Create `crm/src/app/api/deals/[id]/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function PATCH(request: NextRequest, { params }: { params: { id: string } }) {
  const body = await request.json();
  const supabase = await createClient();

  const updates: Record<string, unknown> = { ...body, updated_at: new Date().toISOString() };

  // Set closed_at when moving to a closed stage
  if (body.stage === "fechado_ganho" || body.stage === "fechado_perdido") {
    updates.closed_at = new Date().toISOString();
  }

  const { data, error } = await supabase
    .from("deals")
    .update(updates)
    .eq("id", params.id)
    .select("*, leads(id, name, company, phone, nome_fantasia)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(_request: NextRequest, { params }: { params: { id: string } }) {
  const supabase = await createClient();
  const { error } = await supabase.from("deals").delete().eq("id", params.id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/api/deals/route.ts crm/src/app/api/deals/\[id\]/route.ts
git commit -m "feat: add deals CRUD API routes"
```

---

### Task 5: Rewrite `/vendas` page — deal kanban

**Files:**
- Rewrite: `crm/src/app/(authenticated)/vendas/page.tsx`
- Create: `crm/src/components/deals/deal-card.tsx`
- Create: `crm/src/components/deals/deal-create-modal.tsx`
- Create: `crm/src/components/deals/deal-detail-sidebar.tsx`
- Create: `crm/src/components/deals/deal-kanban-metrics.tsx`
- Create: `crm/src/components/deals/deal-kanban-filters.tsx`
- Create: `crm/src/components/deals/lost-reason-modal.tsx`

- [ ] **Step 1: Create `deal-card.tsx`**

Create `crm/src/components/deals/deal-card.tsx`:

```typescript
import type { Deal } from "@/lib/types";
import { DEAL_CATEGORIES } from "@/lib/constants";

function formatCurrency(value: number): string {
  if (value === 0) return "";
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

function daysInStage(updatedAt: string): number {
  return Math.floor((Date.now() - new Date(updatedAt).getTime()) / (1000 * 60 * 60 * 24));
}

interface DealCardProps {
  deal: Deal;
  onClick: (deal: Deal) => void;
}

export function DealCard({ deal, onClick }: DealCardProps) {
  const lead = deal.leads;
  const displayName = lead?.name || lead?.company || lead?.nome_fantasia || lead?.phone || "—";
  const initial = displayName[0]?.toUpperCase() || "?";
  const categoryInfo = DEAL_CATEGORIES.find((c) => c.key === deal.category);
  const days = daysInStage(deal.updated_at);
  const assignedInitial = deal.assigned_to?.[0]?.toUpperCase();

  return (
    <button
      onClick={() => onClick(deal)}
      className="w-full text-left bg-white rounded-[10px] border border-[#e5e5dc] p-3 transition-all duration-150 hover:-translate-y-[1px] hover:shadow-[0_4px_12px_rgba(0,0,0,0.08)]"
      style={{ boxShadow: "0 2px 8px rgba(0,0,0,0.05)" }}
    >
      {/* Title + Value */}
      <div className="flex items-start justify-between mb-2">
        <p className="text-[13px] font-semibold text-[#1f1f1f] truncate flex-1">{deal.title}</p>
        {deal.value > 0 && (
          <span className="text-[12px] font-bold text-[#2d6a3f] ml-2 flex-shrink-0">
            {formatCurrency(deal.value)}
          </span>
        )}
      </div>

      {/* Lead name */}
      <div className="flex items-center gap-2 mb-2">
        <div className="w-6 h-6 rounded-full bg-[#1f1f1f] flex items-center justify-center text-[10px] font-bold text-[#c8cc8e] flex-shrink-0">
          {initial}
        </div>
        <span className="text-[12px] text-[#5f6368] truncate">{displayName}</span>
      </div>

      {/* Bottom row: category + days + assigned */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {categoryInfo && (
          <span
            className="text-[9px] font-medium px-2 py-0.5 rounded-md"
            style={{ backgroundColor: categoryInfo.color + "22", color: categoryInfo.color }}
          >
            {categoryInfo.label}
          </span>
        )}
        {days > 0 && (
          <span className={`text-[9px] px-2 py-0.5 rounded-md ${days > 7 ? "bg-[#fee2e2] text-[#991b1b]" : "bg-[#f4f4f0] text-[#5f6368]"}`}>
            {days}d
          </span>
        )}
        {assignedInitial && (
          <span className="ml-auto w-5 h-5 rounded-full bg-[#c8cc8e] flex items-center justify-center text-[9px] font-bold text-[#1f1f1f]">
            {assignedInitial}
          </span>
        )}
      </div>
    </button>
  );
}
```

- [ ] **Step 2: Create `deal-kanban-metrics.tsx`**

Create `crm/src/components/deals/deal-kanban-metrics.tsx`:

```typescript
import type { Deal } from "@/lib/types";

interface DealKanbanMetricsProps {
  deals: Deal[];
}

export function DealKanbanMetrics({ deals }: DealKanbanMetricsProps) {
  const activeDeals = deals.filter(
    (d) => d.stage !== "fechado_ganho" && d.stage !== "fechado_perdido"
  );
  const pipelineValue = activeDeals.reduce((sum, d) => sum + (d.value || 0), 0);

  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const wonThisMonth = deals.filter(
    (d) => d.stage === "fechado_ganho" && d.closed_at && new Date(d.closed_at) >= monthStart
  );
  const wonValue = wonThisMonth.reduce((sum, d) => sum + (d.value || 0), 0);

  const totalClosed = deals.filter(
    (d) => d.stage === "fechado_ganho" || d.stage === "fechado_perdido"
  ).length;
  const totalWon = deals.filter((d) => d.stage === "fechado_ganho").length;
  const conversionRate = totalClosed > 0 ? Math.round((totalWon / totalClosed) * 100) : 0;

  const fmt = (v: number) =>
    `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  return (
    <div className="flex gap-3.5 mb-5">
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Pipeline ativo
        </p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {activeDeals.length}
          </span>
          <span className="text-[12px] text-[#9ca3af]">deals</span>
        </div>
        <p className="text-[11px] text-[#c8cc8e] mt-1.5">{fmt(pipelineValue)}</p>
      </div>

      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Ganho no mes
        </p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-[#5aad65] leading-none">
            {fmt(wonValue)}
          </span>
        </div>
        <p className="text-[11px] text-[#9ca3af] mt-1.5">{wonThisMonth.length} deals</p>
      </div>

      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Taxa de conversao
        </p>
        <div className="mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {conversionRate}%
          </span>
        </div>
        <p className="text-[11px] text-[#9ca3af] mt-1.5">{totalWon} de {totalClosed} fechados</p>
      </div>

      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Total de deals
        </p>
        <div className="mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {deals.length}
          </span>
        </div>
        <p className="text-[11px] text-[#c8cc8e] mt-1.5">
          {fmt(deals.reduce((sum, d) => sum + (d.value || 0), 0))} total
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `deal-kanban-filters.tsx`**

Create `crm/src/components/deals/deal-kanban-filters.tsx`:

```typescript
"use client";

import { DEAL_CATEGORIES } from "@/lib/constants";

interface DealKanbanFiltersProps {
  search: string;
  onSearchChange: (val: string) => void;
  category: string;
  onCategoryChange: (val: string) => void;
  showActive: boolean;
  onToggleActive: () => void;
}

export function DealKanbanFilters({
  search,
  onSearchChange,
  category,
  onCategoryChange,
  showActive,
  onToggleActive,
}: DealKanbanFiltersProps) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <div className="relative w-72">
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9ca3af]"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
          />
        </svg>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Buscar por titulo, lead ou empresa..."
          className="w-full text-[13px] rounded-[10px] pl-9 pr-4 py-2.5 bg-white border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] transition-colors text-[#1f1f1f] placeholder:text-[#9ca3af]"
        />
      </div>
      <select
        value={category}
        onChange={(e) => onCategoryChange(e.target.value)}
        className="py-2.5 px-3 rounded-[10px] border border-[#e5e5dc] text-[12px] text-[#5f6368] bg-white cursor-pointer"
      >
        <option value="">Todas categorias</option>
        {DEAL_CATEGORIES.map((c) => (
          <option key={c.key} value={c.key}>
            {c.label}
          </option>
        ))}
      </select>
      <button
        onClick={onToggleActive}
        className={`px-4 py-2.5 rounded-[10px] text-[12px] font-medium transition-colors ${
          showActive
            ? "bg-[#1f1f1f] text-white"
            : "bg-white text-[#5f6368] border border-[#e5e5dc] hover:bg-[#f6f7ed]"
        }`}
      >
        Deals ativos
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Create `lost-reason-modal.tsx`**

Create `crm/src/components/deals/lost-reason-modal.tsx`:

```typescript
"use client";

import { useState } from "react";

interface LostReasonModalProps {
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

export function LostReasonModal({ onConfirm, onCancel }: LostReasonModalProps) {
  const [reason, setReason] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onCancel}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative bg-white rounded-2xl p-6 w-full max-w-[400px] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[16px] font-semibold text-[#1f1f1f] mb-1">Motivo da perda</h3>
        <p className="text-[13px] text-[#5f6368] mb-4">Por que essa oportunidade foi perdida?</p>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Ex: Preco alto, concorrente, sem resposta..."
          className="w-full text-[13px] rounded-xl px-4 py-3 border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] resize-none h-24"
        />
        <div className="flex gap-2 mt-4 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-lg border border-[#e5e5dc] bg-white text-[13px] text-[#5f6368] hover:bg-[#f6f7ed]"
          >
            Cancelar
          </button>
          <button
            onClick={() => onConfirm(reason)}
            className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333]"
          >
            Confirmar
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create `deal-detail-sidebar.tsx`**

Create `crm/src/components/deals/deal-detail-sidebar.tsx`:

```typescript
"use client";

import { useState } from "react";
import type { Deal } from "@/lib/types";
import { DEAL_STAGES, DEAL_CATEGORIES } from "@/lib/constants";

function formatCurrency(value: number): string {
  if (value === 0) return "R$ 0";
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

interface DealDetailSidebarProps {
  deal: Deal;
  onClose: () => void;
  onUpdate: (dealId: string, data: Record<string, unknown>) => Promise<void>;
}

export function DealDetailSidebar({ deal, onClose, onUpdate }: DealDetailSidebarProps) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    title: deal.title,
    value: deal.value,
    category: deal.category || "",
    assigned_to: deal.assigned_to || "",
    expected_close_date: deal.expected_close_date || "",
  });

  const lead = deal.leads;
  const displayName = lead?.name || lead?.company || lead?.nome_fantasia || lead?.phone || "—";
  const stageInfo = DEAL_STAGES.find((s) => s.key === deal.stage);
  const categoryInfo = DEAL_CATEGORIES.find((c) => c.key === deal.category);
  const daysActive = Math.floor(
    (Date.now() - new Date(deal.created_at).getTime()) / (1000 * 60 * 60 * 24)
  );

  async function handleSave() {
    await onUpdate(deal.id, {
      title: form.title,
      value: Number(form.value) || 0,
      category: form.category || null,
      assigned_to: form.assigned_to || null,
      expected_close_date: form.expected_close_date || null,
    });
    setEditing(false);
  }

  return (
    <div className="fixed inset-y-0 right-0 w-[380px] bg-white shadow-xl border-l border-[#e5e5dc] z-50 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[#e5e5dc]">
        <div className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: stageInfo?.dotColor || "#9ca3af" }}
          />
          <span className="text-[13px] font-semibold text-[#1f1f1f]">
            {stageInfo?.label || deal.stage}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setEditing(!editing)}
            className="text-[12px] text-[#5f6368] hover:text-[#1f1f1f] px-2 py-1 rounded-lg hover:bg-[#f6f7ed]"
          >
            {editing ? "Cancelar" : "Editar"}
          </button>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full bg-[#f4f4f0] text-[#5f6368] hover:bg-[#e5e5dc] hover:text-[#1f1f1f]"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Title + Value */}
        {editing ? (
          <div className="space-y-3">
            <div>
              <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Titulo</label>
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
              />
            </div>
            <div>
              <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Valor (R$)</label>
              <input
                type="number"
                value={form.value}
                onChange={(e) => setForm({ ...form, value: Number(e.target.value) })}
                className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
              />
            </div>
            <div>
              <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Categoria</label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] bg-white"
              >
                <option value="">Nenhuma</option>
                {DEAL_CATEGORIES.map((c) => (
                  <option key={c.key} value={c.key}>{c.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Responsavel</label>
              <input
                value={form.assigned_to}
                onChange={(e) => setForm({ ...form, assigned_to: e.target.value })}
                placeholder="Nome do vendedor"
                className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
              />
            </div>
            <div>
              <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Previsao de fechamento</label>
              <input
                type="date"
                value={form.expected_close_date}
                onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })}
                className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
              />
            </div>
            <button
              onClick={handleSave}
              className="w-full py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333]"
            >
              Salvar
            </button>
          </div>
        ) : (
          <>
            <div>
              <h3 className="text-[18px] font-semibold text-[#1f1f1f]">{deal.title}</h3>
              <p className="text-[24px] font-bold text-[#2d6a3f] mt-1">
                {formatCurrency(deal.value)}
              </p>
            </div>

            {categoryInfo && (
              <span
                className="inline-block text-[11px] font-medium px-2.5 py-0.5 rounded-md"
                style={{ backgroundColor: categoryInfo.color + "22", color: categoryInfo.color }}
              >
                {categoryInfo.label}
              </span>
            )}
          </>
        )}

        {/* Lead info */}
        <div className="border-t border-[#e5e5dc] pt-4">
          <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-2">Lead vinculado</span>
          <div className="flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-full bg-[#1f1f1f] flex items-center justify-center text-[13px] font-bold text-[#c8cc8e]">
              {displayName[0]?.toUpperCase() || "?"}
            </div>
            <div>
              <p className="text-[14px] font-semibold text-[#1f1f1f]">{displayName}</p>
              <p className="text-[12px] text-[#9ca3af]">{lead?.phone || "—"}</p>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="border-t border-[#e5e5dc] pt-4 space-y-2">
          <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-2">Detalhes</span>
          <div className="flex justify-between">
            <span className="text-[12px] text-[#5f6368]">Responsavel</span>
            <span className="text-[13px] font-medium text-[#1f1f1f]">{deal.assigned_to || "—"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[12px] text-[#5f6368]">Previsao</span>
            <span className="text-[13px] font-medium text-[#1f1f1f]">
              {deal.expected_close_date
                ? new Date(deal.expected_close_date).toLocaleDateString("pt-BR")
                : "—"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-[12px] text-[#5f6368]">Dias ativo</span>
            <span className="text-[13px] font-medium text-[#1f1f1f]">{daysActive}d</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[12px] text-[#5f6368]">Criado em</span>
            <span className="text-[13px] font-medium text-[#1f1f1f]">
              {new Date(deal.created_at).toLocaleDateString("pt-BR")}
            </span>
          </div>
          {deal.lost_reason && (
            <div className="mt-2 p-3 bg-[#fee2e2] rounded-lg">
              <span className="text-[11px] uppercase text-[#991b1b] block mb-1">Motivo da perda</span>
              <p className="text-[13px] text-[#991b1b]">{deal.lost_reason}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Create `deal-create-modal.tsx`**

Create `crm/src/components/deals/deal-create-modal.tsx`:

```typescript
"use client";

import { useState } from "react";
import { DEAL_CATEGORIES } from "@/lib/constants";
import type { Lead } from "@/lib/types";

interface DealCreateModalProps {
  leads: Lead[];
  preselectedLead?: Lead;
  onClose: () => void;
  onCreate: (data: {
    lead_id: string;
    title: string;
    value: number;
    category: string;
    expected_close_date: string;
  }) => Promise<void>;
}

export function DealCreateModal({ leads, preselectedLead, onClose, onCreate }: DealCreateModalProps) {
  const [title, setTitle] = useState("");
  const [leadSearch, setLeadSearch] = useState(
    preselectedLead ? (preselectedLead.name || preselectedLead.phone) : ""
  );
  const [selectedLeadId, setSelectedLeadId] = useState(preselectedLead?.id || "");
  const [value, setValue] = useState("");
  const [category, setCategory] = useState("");
  const [expectedClose, setExpectedClose] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [saving, setSaving] = useState(false);

  const filteredLeads = leads.filter((l) => {
    if (!leadSearch) return true;
    const q = leadSearch.toLowerCase();
    return (
      (l.name || "").toLowerCase().includes(q) ||
      l.phone.includes(q) ||
      (l.company || "").toLowerCase().includes(q)
    );
  }).slice(0, 8);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedLeadId || !title.trim()) return;
    setSaving(true);
    await onCreate({
      lead_id: selectedLeadId,
      title: title.trim(),
      value: Number(value) || 0,
      category,
      expected_close_date: expectedClose,
    });
    setSaving(false);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative bg-white rounded-2xl p-6 w-full max-w-[480px] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[18px] font-semibold text-[#1f1f1f] mb-4">Nova Oportunidade</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Lead autocomplete */}
          <div className="relative">
            <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Lead *</label>
            <input
              value={leadSearch}
              onChange={(e) => {
                setLeadSearch(e.target.value);
                setSelectedLeadId("");
                setShowDropdown(true);
              }}
              onFocus={() => setShowDropdown(true)}
              placeholder="Buscar lead por nome ou telefone..."
              className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
              readOnly={!!preselectedLead}
            />
            {showDropdown && !selectedLeadId && !preselectedLead && filteredLeads.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-[#e5e5dc] rounded-xl shadow-lg z-10 max-h-48 overflow-y-auto">
                {filteredLeads.map((l) => (
                  <button
                    key={l.id}
                    type="button"
                    onClick={() => {
                      setSelectedLeadId(l.id);
                      setLeadSearch(l.name || l.phone);
                      setShowDropdown(false);
                      if (!title) setTitle(`${l.name || l.phone} - Oportunidade`);
                    }}
                    className="w-full text-left px-3 py-2 text-[13px] hover:bg-[#f6f7ed] flex justify-between"
                  >
                    <span className="text-[#1f1f1f]">{l.name || l.phone}</span>
                    <span className="text-[#9ca3af]">{l.phone}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Title */}
          <div>
            <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Titulo *</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ex: Atacado 50kg - Cafe Especial"
              className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            {/* Value */}
            <div>
              <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Valor (R$)</label>
              <input
                type="number"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="0"
                className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
              />
            </div>
            {/* Category */}
            <div>
              <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Categoria</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] bg-white"
              >
                <option value="">Selecionar...</option>
                {DEAL_CATEGORIES.map((c) => (
                  <option key={c.key} value={c.key}>{c.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Expected close */}
          <div>
            <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Previsao de fechamento</label>
            <input
              type="date"
              value={expectedClose}
              onChange={(e) => setExpectedClose(e.target.value)}
              className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
            />
          </div>

          <div className="flex gap-2 justify-end pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-xl border border-[#e5e5dc] bg-white text-[13px] text-[#5f6368] hover:bg-[#f6f7ed]"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving || !selectedLeadId || !title.trim()}
              className="px-5 py-2.5 rounded-xl bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] disabled:opacity-50"
            >
              {saving ? "Criando..." : "Criar Oportunidade"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Rewrite the vendas page**

Rewrite `crm/src/app/(authenticated)/vendas/page.tsx` completely:

```typescript
"use client";

import { useState } from "react";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import { useDroppable, useDraggable } from "@dnd-kit/core";
import { useRealtimeDeals } from "@/hooks/use-realtime-deals";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { DEAL_STAGES } from "@/lib/constants";
import { DealCard } from "@/components/deals/deal-card";
import { DealKanbanMetrics } from "@/components/deals/deal-kanban-metrics";
import { DealKanbanFilters } from "@/components/deals/deal-kanban-filters";
import { DealCreateModal } from "@/components/deals/deal-create-modal";
import { DealDetailSidebar } from "@/components/deals/deal-detail-sidebar";
import { LostReasonModal } from "@/components/deals/lost-reason-modal";
import type { Deal } from "@/lib/types";

function DroppableColumn({
  id,
  title,
  dotColor,
  tintColor,
  deals,
  onDealClick,
}: {
  id: string;
  title: string;
  dotColor: string;
  tintColor: string;
  deals: Deal[];
  onDealClick: (deal: Deal) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });

  const columnValue = deals.reduce((sum, d) => sum + (d.value || 0), 0);
  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  return (
    <div className="flex-shrink-0 w-[270px]">
      <div className="bg-[#1f1f1f] rounded-t-xl px-3.5 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: dotColor }} />
          <h3 className="text-[12px] font-semibold text-white">{title}</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[#9ca3af]">{fmt(columnValue)}</span>
          <span className="text-[10px] font-semibold text-white bg-white/15 rounded-full px-2 py-0.5">
            {deals.length}
          </span>
        </div>
      </div>
      <div
        ref={setNodeRef}
        className={`rounded-b-xl p-2.5 min-h-[calc(100vh-280px)] space-y-2.5 overflow-y-auto transition-all duration-200 ${
          isOver ? "ring-2 ring-[#c8cc8e] ring-inset" : ""
        }`}
        style={{ backgroundColor: tintColor }}
      >
        {deals.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-[12px] text-[#b0adb5]">Nenhum deal</p>
          </div>
        )}
        {deals.map((deal) => (
          <DraggableDealCard key={deal.id} deal={deal} onClick={onDealClick} />
        ))}
      </div>
    </div>
  );
}

function DraggableDealCard({ deal, onClick }: { deal: Deal; onClick: (deal: Deal) => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: deal.id,
    data: deal,
  });

  return (
    <div ref={setNodeRef} {...listeners} {...attributes} className={isDragging ? "opacity-30" : ""}>
      <DealCard deal={deal} onClick={onClick} />
    </div>
  );
}

export default function VendasPage() {
  const { deals, loading } = useRealtimeDeals();
  const { leads } = useRealtimeLeads();
  const [selectedDeal, setSelectedDeal] = useState<Deal | null>(null);
  const [activeDrag, setActiveDrag] = useState<Deal | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [showActive, setShowActive] = useState(true);
  const [lostDeal, setLostDeal] = useState<Deal | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  function handleDragStart(event: DragStartEvent) {
    setActiveDrag(event.active.data.current as Deal);
  }

  async function handleDragEnd(event: DragEndEvent) {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;

    const deal = active.data.current as Deal;
    const newStage = over.id as string;
    if (deal.stage === newStage) return;

    // If dropping to fechado_perdido, ask for reason
    if (newStage === "fechado_perdido") {
      setLostDeal({ ...deal, stage: newStage });
      return;
    }

    await fetch(`/api/deals/${deal.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage: newStage }),
    });
  }

  async function handleLostConfirm(reason: string) {
    if (!lostDeal) return;
    await fetch(`/api/deals/${lostDeal.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage: "fechado_perdido", lost_reason: reason }),
    });
    setLostDeal(null);
  }

  async function handleCreateDeal(data: {
    lead_id: string;
    title: string;
    value: number;
    category: string;
    expected_close_date: string;
  }) {
    await fetch("/api/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  }

  async function handleUpdateDeal(dealId: string, data: Record<string, unknown>) {
    await fetch(`/api/deals/${dealId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    setSelectedDeal(null);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
          <span className="text-[14px] text-[#5f6368]">Carregando...</span>
        </div>
      </div>
    );
  }

  const filteredDeals = deals.filter((d) => {
    if (showActive && (d.stage === "fechado_ganho" || d.stage === "fechado_perdido")) return false;
    if (category && d.category !== category) return false;
    if (search) {
      const q = search.toLowerCase();
      const lead = d.leads;
      const match =
        d.title.toLowerCase().includes(q) ||
        (lead?.name || "").toLowerCase().includes(q) ||
        (lead?.company || "").toLowerCase().includes(q) ||
        (lead?.phone || "").includes(q);
      if (!match) return false;
    }
    return true;
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-[28px] font-bold text-[#1f1f1f]">Oportunidades</h1>
          <p className="text-[14px] text-[#5f6368] mt-1">Pipeline de vendas</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="btn-primary flex items-center gap-2 px-5 py-2.5 rounded-xl text-[13px] font-medium"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="8" y1="3" x2="8" y2="13" />
            <line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          Nova Oportunidade
        </button>
      </div>

      <DealKanbanMetrics deals={deals} />
      <DealKanbanFilters
        search={search}
        onSearchChange={setSearch}
        category={category}
        onCategoryChange={setCategory}
        showActive={showActive}
        onToggleActive={() => setShowActive(!showActive)}
      />

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex gap-3 overflow-x-auto pb-4">
          {DEAL_STAGES.map((stage) => {
            const stageDeals = filteredDeals.filter((d) => d.stage === stage.key);
            return (
              <DroppableColumn
                key={stage.key}
                id={stage.key}
                title={stage.label}
                dotColor={stage.dotColor}
                tintColor={stage.tintColor}
                deals={stageDeals}
                onDealClick={setSelectedDeal}
              />
            );
          })}
        </div>
        <DragOverlay>
          {activeDrag ? (
            <div className="w-[270px] opacity-90 rotate-[2deg] shadow-xl">
              <DealCard deal={activeDrag} onClick={() => {}} />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

      {selectedDeal && (
        <DealDetailSidebar
          deal={selectedDeal}
          onClose={() => setSelectedDeal(null)}
          onUpdate={handleUpdateDeal}
        />
      )}

      {showCreate && (
        <DealCreateModal
          leads={leads}
          onClose={() => setShowCreate(false)}
          onCreate={handleCreateDeal}
        />
      )}

      {lostDeal && (
        <LostReasonModal
          onConfirm={handleLostConfirm}
          onCancel={() => setLostDeal(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 8: Commit**

```bash
git add crm/src/components/deals/ crm/src/app/\(authenticated\)/vendas/page.tsx
git commit -m "feat: rewrite /vendas as deals kanban with drag-and-drop pipeline"
```

---

### Task 6: Update dashboard to read from deals

**Files:**
- Modify: `crm/src/app/(authenticated)/dashboard/page.tsx`
- Modify: `crm/src/components/dashboard/funnel-movement.tsx`
- Modify: `crm/src/components/kanban-metrics-bar.tsx` (used by qualificacao — remove seller_stage refs)

- [ ] **Step 1: Update dashboard page**

In `crm/src/app/(authenticated)/dashboard/page.tsx`:

Add import at top:
```typescript
import { useRealtimeDeals } from "@/hooks/use-realtime-deals";
import { DEAL_STAGES } from "@/lib/constants";
```

Inside the component, add after the existing hooks:
```typescript
const { deals, loading: dealsLoading } = useRealtimeDeals();
```

Update the loading check:
```typescript
if (leadsLoading || campaignsLoading || dealsLoading) {
```

Replace the KPI calculations that use `seller_stage`/`sale_value` (lines ~73-80 and ~96-111) with deal-based calculations:

Remove:
```typescript
const activeLeads = leads.filter((l) => l.seller_stage !== "perdido" && l.seller_stage !== "fechado");
const activeValue = activeLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);

const wonLeads = leads.filter((l) => l.seller_stage === "fechado");
const wonValue = wonLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);

const lostLeads = leads.filter((l) => l.seller_stage === "perdido");
const lostValue = lostLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);
```

Add:
```typescript
const activeDeals = deals.filter((d) => d.stage !== "fechado_ganho" && d.stage !== "fechado_perdido");
const activeValue = activeDeals.reduce((sum, d) => sum + (d.value || 0), 0);

const wonDeals = deals.filter((d) => d.stage === "fechado_ganho");
const wonValue = wonDeals.reduce((sum, d) => sum + (d.value || 0), 0);

const lostDeals = deals.filter((d) => d.stage === "fechado_perdido");
const lostValue = lostDeals.reduce((sum, d) => sum + (d.value || 0), 0);
```

Update the KPI cards to use deals:
```typescript
<KpiCard label="Deals ativos" value={activeDeals.length} subtitle={fmt(activeValue)} icon={UsersIcon} />
<KpiCard label="Deals ganhos" value={wonDeals.length} subtitle={fmt(wonValue)} icon={CheckIcon} />
<KpiCard label="Deals perdidos" value={lostDeals.length} subtitle={fmt(lostValue)} icon={XIcon} />
```

Replace the funnel data calculation:
```typescript
const funnelData = DEAL_STAGES
  .filter((s) => s.key !== "fechado_perdido")
  .map((stage) => {
    const stageDeals = deals.filter((d) => d.stage === stage.key);
    return {
      name: stage.label,
      count: stageDeals.length,
      value: stageDeals.reduce((sum, d) => sum + (d.value || 0), 0),
    };
  });
```

Update FunnelMovement to receive deals:
```typescript
<FunnelMovement deals={deals} />
```

- [ ] **Step 2: Rewrite `funnel-movement.tsx` to use deals**

Replace the entire content of `crm/src/components/dashboard/funnel-movement.tsx`:

```typescript
"use client";

import { useState } from "react";
import { DEAL_STAGES } from "@/lib/constants";
import type { Deal } from "@/lib/types";

interface FunnelMovementProps {
  deals: Deal[];
}

type Period = "today" | "7d" | "30d";

function getPeriodStart(period: Period): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  if (period === "7d") d.setDate(d.getDate() - 7);
  if (period === "30d") d.setDate(d.getDate() - 30);
  return d;
}

export function FunnelMovement({ deals }: FunnelMovementProps) {
  const [period, setPeriod] = useState<Period>("30d");
  const periodStart = getPeriodStart(period);

  const stages = DEAL_STAGES.filter((s) => s.key !== "fechado_perdido");

  const data = stages.map((stage) => {
    const inStage = deals.filter((d) => d.stage === stage.key);
    const entered = inStage.filter(
      (d) => d.updated_at && new Date(d.updated_at) >= periodStart
    );
    const value = inStage.reduce((sum, d) => sum + (d.value || 0), 0);

    return {
      ...stage,
      count: inStage.length,
      entered: entered.length,
      value,
    };
  });

  const lost = deals.filter(
    (d) =>
      d.stage === "fechado_perdido" &&
      d.closed_at &&
      new Date(d.closed_at) >= periodStart
  );
  const lostValue = lost.reduce((sum, d) => sum + (d.value || 0), 0);

  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
  const periods: { key: Period; label: string }[] = [
    { key: "today", label: "Hoje" },
    { key: "7d", label: "7 dias" },
    { key: "30d", label: "30 dias" },
  ];

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <h3
          className="text-[13px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-secondary)" }}
        >
          Movimentacao do Pipeline
        </h3>
        <div className="flex gap-1">
          {periods.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${
                period === p.key
                  ? "bg-[#1f1f1f] text-white"
                  : "text-[#5f6368] hover:bg-[#f6f7ed]"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr>
              <th className="text-left py-2 px-3 text-[#9ca3af] font-medium uppercase tracking-wider text-[11px]" />
              {data.map((d) => (
                <th key={d.key} className="text-center py-2 px-3 min-w-[120px]">
                  <div className={`h-1 rounded-full mb-2 ${d.color}`} />
                  <span className="text-[12px] font-semibold text-[#1f1f1f]">{d.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-[#e5e5dc]">
              <td className="py-2 px-3 text-[#9ca3af] text-[11px] uppercase">Na etapa</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-2 px-3">
                  <span className="text-[14px] font-bold text-[#1f1f1f]">{d.count}</span>
                  <br />
                  <span className="text-[11px] text-[#5f6368]">{fmt(d.value)}</span>
                </td>
              ))}
            </tr>
            <tr className="border-t border-[#e5e5dc]">
              <td className="py-2 px-3 text-[#9ca3af] text-[11px] uppercase">Entrou na etapa</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-2 px-3">
                  <span className={`text-[14px] font-bold ${d.entered > 0 ? "text-[#2d6a3f]" : "text-[#9ca3af]"}`}>
                    {d.entered > 0 ? `+${d.entered}` : "0"}
                  </span>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#e5e5dc] flex items-center gap-4">
        <span className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Perdidos no periodo:</span>
        <span className="text-[14px] font-bold text-[#a33]">{lost.length} deals</span>
        <span className="text-[12px] text-[#5f6368]">{fmt(lostValue)}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Clean up kanban-metrics-bar (used by qualificacao)**

The `kanban-metrics-bar.tsx` component is used by the qualificacao page. It references `seller_stage` and `sale_value`. Since qualificacao doesn't use deals, simplify it to only show lead counts:

In `crm/src/components/kanban-metrics-bar.tsx`, replace references to `seller_stage` and `sale_value`:

Replace `leads.filter((l) => l.seller_stage !== "perdido" && l.seller_stage !== "fechado")` with `leads` (show all leads).

Remove `sale_value` aggregations and replace with lead-count-only metrics. The `totalValue` and `potentialValue` sections should be removed since those values now live on deals, not leads.

Updated component:
```typescript
import type { Lead } from "@/lib/types";

interface KanbanMetricsBarProps {
  leads: Lead[];
}

export function KanbanMetricsBar({ leads }: KanbanMetricsBarProps) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const leadsToday = leads.filter((l) => new Date(l.created_at) >= today).length;
  const leadsYesterday = leads.filter((l) => {
    const d = new Date(l.created_at);
    return d >= yesterday && d < today;
  }).length;

  const withResponse = leads.filter((l) => l.first_response_at);
  const avgResponseMs =
    withResponse.length > 0
      ? withResponse.reduce(
          (sum, l) =>
            sum + (new Date(l.first_response_at!).getTime() - new Date(l.created_at).getTime()),
          0
        ) / withResponse.length
      : 0;
  const avgResponseMin = Math.round(avgResponseMs / 60000);
  const responseStr = avgResponseMin > 0 ? `${avgResponseMin}m` : "\u2014";

  return (
    <div className="flex gap-3.5 mb-5">
      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Total no funil
        </p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {leads.length}
          </span>
          <span className="text-[12px] text-[#9ca3af]">leads</span>
        </div>
      </div>

      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Novos hoje / ontem
        </p>
        <div className="flex items-baseline gap-2 mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {leadsToday}
          </span>
          <span className="text-[12px] text-[#9ca3af]">/ {leadsYesterday}</span>
        </div>
        {leadsToday > leadsYesterday && (
          <p className="text-[11px] text-[#5aad65] mt-1.5">&uarr; crescendo</p>
        )}
        {leadsToday <= leadsYesterday && leadsToday > 0 && (
          <p className="text-[11px] text-[#9ca3af] mt-1.5">&rarr; estavel</p>
        )}
        {leadsToday === 0 && (
          <p className="text-[11px] text-[#9ca3af] mt-1.5">nenhum hoje</p>
        )}
      </div>

      <div className="flex-1 min-w-0 bg-[#1f1f1f] rounded-xl px-4 py-3.5">
        <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">
          Tempo medio resp.
        </p>
        <div className="mt-1">
          <span className="text-[24px] font-bold text-white leading-none">
            {responseStr}
          </span>
        </div>
        <p className="text-[11px] text-[#c8cc8e] mt-1.5">agente IA</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add crm/src/app/\(authenticated\)/dashboard/page.tsx crm/src/components/dashboard/funnel-movement.tsx crm/src/components/kanban-metrics-bar.tsx
git commit -m "feat: update dashboard and funnel to read from deals instead of lead seller_stage"
```

---

### Task 7: Clean up seller_stage/sale_value from all remaining components

**Files:**
- Modify: `crm/src/lib/types.ts` (already done in Task 2, verify)
- Modify: `crm/src/components/leads/lead-detail-modal.tsx`
- Modify: `crm/src/components/leads/lead-grid-card.tsx`
- Modify: `crm/src/components/leads/leads-filter-bar.tsx`
- Modify: `crm/src/components/conversas/contact-detail.tsx`
- Modify: `crm/src/components/lead-card.tsx`
- Modify: `crm/src/components/quick-add-lead.tsx`
- Modify: `crm/src/components/lead-detail-sidebar.tsx`
- Modify: `crm/src/app/(authenticated)/leads/page.tsx`
- Modify: `crm/src/app/api/leads/route.ts`
- Modify: `crm/src/app/api/leads/[id]/route.ts`
- Modify: `crm/src/app/api/leads/export/route.ts`
- Modify: `crm/src/app/api/leads/import/route.ts`
- Modify: `crm/src/app/api/conversations/route.ts`
- Modify: `crm/src/app/api/evolution/send/route.ts`
- Modify: `crm/src/components/lead-selector.tsx`

This is a cleanup task. For each file, remove all references to `seller_stage` and `sale_value`. The exact changes per file:

- [ ] **Step 1: Clean `lead-detail-modal.tsx`**

Remove the `SELLER_STAGES` import. Remove the "Etapa Vendas" select dropdown (lines ~312-323). Remove the "Valor de Venda" input (lines ~333-342). Remove `sale_value` from the metricas tab (lines ~531-535). Remove `seller_stage_change` from `formatEventText`.

- [ ] **Step 2: Clean `lead-grid-card.tsx`**

Remove `SELLER_STAGES` import. Remove `sellerInfo` variable. Remove `sale_value` display. In the footer, replace `sellerInfo?.label || "Novo"` with just the agent stage.

- [ ] **Step 3: Clean `leads-filter-bar.tsx`**

Remove `SELLER_STAGES` import. Remove `sellerStage` from `LeadFilters` interface. Remove the "Etapa Vendas" select dropdown. Remove `sellerStage` from `clearAll` and `activeFilters`.

- [ ] **Step 4: Clean `leads/page.tsx`**

Remove `sellerStage` from the filter state. Remove `filters.sellerStage` check in the filter function. Remove `sale_value` from KPI calculations (the "Valor Total Pipeline" KPI should be removed or replaced with deal-based data later).

- [ ] **Step 5: Clean `contact-detail.tsx`**

Remove `SELLER_STAGES` import. Remove the "Stage (Vendedor)" select section. Remove the "Valor da Venda" EditableField. Remove `sale_value` from `numericFields`.

- [ ] **Step 6: Clean `lead-card.tsx`**

Remove the `formatCurrency` call using `lead.sale_value` and the currency display.

- [ ] **Step 7: Clean `quick-add-lead.tsx`**

Remove the `sellerStage` prop. Remove `seller_stage` and `sale_value` from the insert call.

- [ ] **Step 8: Clean `lead-detail-sidebar.tsx`**

Remove `seller_stage` display from the fields array.

- [ ] **Step 9: Clean API routes**

In `crm/src/app/api/leads/route.ts`: Remove `seller_stage` from the POST insert.
In `crm/src/app/api/leads/[id]/route.ts`: Remove `seller_stage` from the select and the seller_stage_change event tracking.
In `crm/src/app/api/leads/export/route.ts`: Remove `seller_stage` and `sale_value`/`valor_venda` from CSV columns.
In `crm/src/app/api/leads/import/route.ts`: Remove `seller_stage` from the interface and insert.
In `crm/src/app/api/conversations/route.ts`: Remove `seller_stage` from the lead insert and from the select query.
In `crm/src/app/api/evolution/send/route.ts`: Remove `seller_stage` from the lead insert.

- [ ] **Step 10: Clean `lead-selector.tsx`**

Check if it references `seller_stage` or `sale_value` and remove.

- [ ] **Step 11: Verify compilation**

Run: `cd crm && npx tsc --noEmit --pretty 2>&1 | head -40`

Fix any remaining TypeScript errors.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "refactor: remove all seller_stage and sale_value references from leads"
```

---

### Task 8: Update backend `encaminhar_humano` tool to create a deal

**Files:**
- Modify: `backend-evolution/app/agent/tools.py`
- Modify: `backend-evolution/app/leads/service.py`

- [ ] **Step 1: Add `create_deal` function to leads service**

In `backend-evolution/app/leads/service.py`, add:

```python
def create_deal(lead_id: str, title: str, category: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    deal = {
        "lead_id": lead_id,
        "title": title,
        "stage": "novo",
        "category": category,
    }
    result = sb.table("deals").insert(deal).execute()
    return result.data[0]
```

- [ ] **Step 2: Update `encaminhar_humano` in tools.py**

In `backend-evolution/app/agent/tools.py`, change:

```python
update_lead(lead_id, status="converted", human_control=True, seller_stage="novo")
```

To:

```python
from app.leads.service import update_lead, save_message, create_deal

# ... in the encaminhar_humano handler:
lead = update_lead(lead_id, status="converted", human_control=True)
create_deal(lead_id, title=f"{args.get('vendedor', 'Vendedor')} - {args['motivo']}")
```

Also update the import at the top of tools.py to include `create_deal`.

- [ ] **Step 3: Commit**

```bash
git add backend-evolution/app/agent/tools.py backend-evolution/app/leads/service.py
git commit -m "feat: encaminhar_humano now creates a deal instead of setting seller_stage"
```

---

### Task 9: Add deals section to lead detail and contact detail

**Files:**
- Modify: `crm/src/components/leads/lead-detail-modal.tsx`
- Modify: `crm/src/components/conversas/contact-detail.tsx`
- Modify: `crm/src/components/lead-detail-sidebar.tsx`

The spec requires that lead detail views show the linked deals, and that contact-detail shows the active deal badge. Task 7 removes the old `seller_stage`/`sale_value` fields — this task adds the new deals integration.

- [ ] **Step 1: Add deals list to `lead-detail-modal.tsx`**

In the "Status no CRM" section (after removing `seller_stage` and `sale_value` in Task 7), add a new section that fetches and displays deals for this lead.

Add state and fetch inside the component:
```typescript
const [leadDeals, setLeadDeals] = useState<Array<{ id: string; title: string; value: number; stage: string; category: string | null }>>([]);

useEffect(() => {
  import("@/lib/supabase/client").then(({ createClient }) => {
    const supabase = createClient();
    supabase
      .from("deals")
      .select("id, title, value, stage, category")
      .eq("lead_id", lead.id)
      .order("created_at", { ascending: false })
      .then(({ data }) => {
        if (data) setLeadDeals(data);
      });
  });
}, [lead.id]);
```

Add a "Oportunidades" section in the "dados" tab after the CRM Status row:
```typescript
<div className="mt-5 pt-4 border-t border-[#f3f3f0]">
  <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">
    Oportunidades ({leadDeals.length})
  </p>
  {leadDeals.length === 0 && (
    <p className="text-[13px] text-[#9ca3af]">Nenhuma oportunidade vinculada.</p>
  )}
  <div className="space-y-2">
    {leadDeals.map((deal) => {
      const stageInfo = DEAL_STAGES.find((s) => s.key === deal.stage);
      return (
        <div key={deal.id} className="flex items-center justify-between bg-[#f6f7ed] rounded-lg p-3">
          <div>
            <p className="text-[13px] font-semibold text-[#1f1f1f]">{deal.title}</p>
            <span
              className="text-[10px] font-medium px-2 py-0.5 rounded-md"
              style={{ backgroundColor: (stageInfo?.dotColor || "#9ca3af") + "22", color: stageInfo?.dotColor || "#9ca3af" }}
            >
              {stageInfo?.label || deal.stage}
            </span>
          </div>
          <span className="text-[14px] font-bold text-[#2d6a3f]">
            {deal.value > 0 ? `R$ ${deal.value.toLocaleString("pt-BR")}` : "—"}
          </span>
        </div>
      );
    })}
  </div>
</div>
```

Import `DEAL_STAGES` from constants (replacing the removed `SELLER_STAGES` import).

- [ ] **Step 2: Add active deal badge to `contact-detail.tsx`**

Add a deals fetch inside the component:
```typescript
const [activeDeal, setActiveDeal] = useState<{ title: string; value: number; stage: string } | null>(null);

useEffect(() => {
  if (!lead) return;
  import("@/lib/supabase/client").then(({ createClient: createSbClient }) => {
    const sb = createSbClient();
    sb.from("deals")
      .select("title, value, stage")
      .eq("lead_id", lead.id)
      .not("stage", "in", "(fechado_ganho,fechado_perdido)")
      .order("updated_at", { ascending: false })
      .limit(1)
      .then(({ data }) => {
        if (data && data.length > 0) setActiveDeal(data[0]);
      });
  });
}, [lead?.id]);
```

Add the deal badge in the lead info section (after the stage info):
```typescript
{activeDeal && (
  <div className="bg-[#f6f7ed] border border-[#e5e5dc] rounded-xl p-3">
    <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-1">Oportunidade ativa</span>
    <p className="text-[13px] font-semibold text-[#1f1f1f]">{activeDeal.title}</p>
    <p className="text-[14px] font-bold text-[#2d6a3f]">
      {activeDeal.value > 0 ? `R$ ${activeDeal.value.toLocaleString("pt-BR")}` : "—"}
    </p>
  </div>
)}
```

Remove the `SELLER_STAGES` import and replace with `DEAL_STAGES` if needed.

- [ ] **Step 3: Add deals section to `lead-detail-sidebar.tsx`**

Similar to lead-detail-modal, add a fetch for deals and display them in the sidebar. Add after the existing fields section:

```typescript
const [leadDeals, setLeadDeals] = useState<Array<{ id: string; title: string; value: number; stage: string }>>([]);

useEffect(() => {
  supabase
    .from("deals")
    .select("id, title, value, stage")
    .eq("lead_id", lead.id)
    .order("created_at", { ascending: false })
    .then(({ data }) => {
      if (data) setLeadDeals(data);
    });
}, [lead.id]);
```

Display section:
```typescript
{leadDeals.length > 0 && (
  <div className="mt-4 border-t border-[#e5e5dc] pt-4">
    <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-2">Oportunidades</span>
    {leadDeals.map((deal) => (
      <div key={deal.id} className="flex justify-between items-center py-1.5">
        <span className="text-[13px] text-[#1f1f1f]">{deal.title}</span>
        <span className="text-[12px] font-semibold text-[#2d6a3f]">
          {deal.value > 0 ? `R$ ${deal.value.toLocaleString("pt-BR")}` : "—"}
        </span>
      </div>
    ))}
  </div>
)}
```

- [ ] **Step 4: Commit**

```bash
git add crm/src/components/leads/lead-detail-modal.tsx crm/src/components/conversas/contact-detail.tsx crm/src/components/lead-detail-sidebar.tsx
git commit -m "feat: add deals section to lead detail views and contact detail"
```

---

### Task 10: Final verification and fix

- [ ] **Step 1: Run TypeScript compilation check**

Run: `cd crm && npx tsc --noEmit --pretty`

Fix any errors.

- [ ] **Step 2: Run the dev server and verify pages load**

Run: `cd crm && npm run dev`

Visit:
- `/vendas` — verify the deal kanban loads with drag-and-drop
- `/dashboard` — verify KPIs show deal-based data
- `/leads` — verify no seller_stage references remain
- `/qualificacao` — verify it still works (agent stages only)
- `/conversas` — verify contact detail doesn't crash

- [ ] **Step 3: Test creating a deal**

On `/vendas`, click "+ Nova Oportunidade", select a lead, fill in details, and create. Verify the deal appears in the kanban.

- [ ] **Step 4: Test drag and drop**

Drag a deal between columns. Verify the stage updates. Drag to "Perdido" and verify the lost reason modal appears.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve remaining issues from deals migration"
```

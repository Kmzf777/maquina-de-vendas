# Leads Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `/leads` page with KPI bar, filterable card grid, detail modal (editable), lead creation form, and CSV import.

**Architecture:** Client-side page using existing `useRealtimeLeads` hook. Temperature calculated client-side from `last_msg_at`. New API routes for lead CRUD, notes, events, and CSV import. Two new DB tables (`lead_notes`, `lead_events`).

**Tech Stack:** Next.js App Router, Supabase (realtime + service role), TypeScript, papaparse (CSV)

---

## File Structure

**New files:**
- `backend-evolution/migrations/006_lead_notes_events.sql` — new tables
- `crm/src/lib/temperature.ts` — temperature utility
- `crm/src/app/(authenticated)/leads/page.tsx` — main page
- `crm/src/components/leads/lead-grid-card.tsx` — card for the grid
- `crm/src/components/leads/leads-filter-bar.tsx` — filter bar component
- `crm/src/components/leads/lead-detail-modal.tsx` — detail modal (4 tabs)
- `crm/src/components/leads/lead-create-modal.tsx` — new lead form
- `crm/src/components/leads/lead-import-modal.tsx` — CSV import wizard
- `crm/src/app/api/leads/route.ts` — GET all leads with tags, POST create lead
- `crm/src/app/api/leads/[id]/route.ts` — PATCH update lead
- `crm/src/app/api/leads/[id]/notes/route.ts` — GET/POST notes
- `crm/src/app/api/leads/[id]/events/route.ts` — GET events
- `crm/src/app/api/leads/import/route.ts` — POST bulk CSV import
- `crm/src/app/api/leads/export/route.ts` — GET export CSV

**Modified files:**
- `crm/src/components/sidebar.tsx` — add Leads nav item
- `crm/src/lib/types.ts` — add LeadNote, LeadEvent types

---

### Task 1: Database Migration — lead_notes and lead_events tables

**Files:**
- Create: `backend-evolution/migrations/006_lead_notes_events.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 006_lead_notes_events.sql
-- Lead notes (manual) and events (automatic activity log)

CREATE TABLE IF NOT EXISTS lead_notes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    author text NOT NULL,
    content text NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_lead_notes_lead_id ON lead_notes(lead_id);

CREATE TABLE IF NOT EXISTS lead_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    old_value text,
    new_value text,
    metadata jsonb,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_lead_events_lead_id ON lead_events(lead_id);

ALTER PUBLICATION supabase_realtime ADD TABLE lead_notes;
ALTER PUBLICATION supabase_realtime ADD TABLE lead_events;
```

- [ ] **Step 2: Run the migration against Supabase**

Run the SQL in the Supabase SQL editor or via CLI.

- [ ] **Step 3: Commit**

```bash
git add backend-evolution/migrations/006_lead_notes_events.sql
git commit -m "feat: add lead_notes and lead_events tables"
```

---

### Task 2: Types and Temperature Utility

**Files:**
- Modify: `crm/src/lib/types.ts`
- Create: `crm/src/lib/temperature.ts`

- [ ] **Step 1: Add types to types.ts**

Add at the end of `crm/src/lib/types.ts`:

```typescript
export interface LeadNote {
  id: string;
  lead_id: string;
  author: string;
  content: string;
  created_at: string;
}

export interface LeadEvent {
  id: string;
  lead_id: string;
  event_type: string; // 'stage_change' | 'seller_stage_change' | 'campaign_added' | 'campaign_removed' | 'first_response'
  old_value: string | null;
  new_value: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}
```

- [ ] **Step 2: Create temperature utility**

Create `crm/src/lib/temperature.ts`:

```typescript
export type Temperature = "quente" | "morno" | "frio";

const FORTY_EIGHT_HOURS = 48 * 60 * 60 * 1000;
const SEVEN_DAYS = 7 * 24 * 60 * 60 * 1000;

export function getTemperature(lastMsgAt: string | null): Temperature {
  if (!lastMsgAt) return "frio";
  const diff = Date.now() - new Date(lastMsgAt).getTime();
  if (diff < FORTY_EIGHT_HOURS) return "quente";
  if (diff < SEVEN_DAYS) return "morno";
  return "frio";
}

export const TEMPERATURE_CONFIG = {
  quente: { label: "Quente", color: "#f87171", bg: "#fef2f2", dotColor: "#f87171", borderColor: "#f87171" },
  morno:  { label: "Morno",  color: "#ca8a04", bg: "#fefce8", dotColor: "#e8d44d", borderColor: "#e8d44d" },
  frio:   { label: "Frio",   color: "#60a5fa", bg: "#eff6ff", dotColor: "#60a5fa", borderColor: "#60a5fa" },
} as const;
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/lib/types.ts crm/src/lib/temperature.ts
git commit -m "feat: add LeadNote/LeadEvent types and temperature utility"
```

---

### Task 3: API Routes — Lead CRUD, Notes, Events

**Files:**
- Create: `crm/src/app/api/leads/route.ts`
- Create: `crm/src/app/api/leads/[id]/route.ts`
- Create: `crm/src/app/api/leads/[id]/notes/route.ts`
- Create: `crm/src/app/api/leads/[id]/events/route.ts`

- [ ] **Step 1: Create GET/POST leads route**

Create `crm/src/app/api/leads/route.ts`:

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();

  const { data: leads, error } = await supabase
    .from("leads")
    .select("*, lead_tags(tag_id, tags(*))")
    .order("last_msg_at", { ascending: false, nullsFirst: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(leads);
}

export async function POST(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const body = await request.json();

  // Check for duplicate phone
  const { data: existing } = await supabase
    .from("leads")
    .select("id")
    .eq("phone", body.phone)
    .maybeSingle();

  if (existing) {
    return NextResponse.json(
      { error: "Lead com este telefone ja existe" },
      { status: 409 }
    );
  }

  const { data, error } = await supabase
    .from("leads")
    .insert({
      phone: body.phone,
      name: body.name || null,
      email: body.email || null,
      instagram: body.instagram || null,
      company: body.company || null,
      cnpj: body.cnpj || null,
      stage: body.stage || "secretaria",
      seller_stage: body.seller_stage || "novo",
      channel: body.channel || "manual",
      status: "active",
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Create PATCH lead route**

Create `crm/src/app/api/leads/[id]/route.ts`:

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const body = await request.json();

  // Fetch current lead for event logging
  const { data: currentLead } = await supabase
    .from("leads")
    .select("stage, seller_stage")
    .eq("id", id)
    .single();

  const { data, error } = await supabase
    .from("leads")
    .update(body)
    .eq("id", id)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // Log events for stage changes
  if (currentLead) {
    const events = [];
    if (body.stage && body.stage !== currentLead.stage) {
      events.push({
        lead_id: id,
        event_type: "stage_change",
        old_value: currentLead.stage,
        new_value: body.stage,
      });
    }
    if (body.seller_stage && body.seller_stage !== currentLead.seller_stage) {
      events.push({
        lead_id: id,
        event_type: "seller_stage_change",
        old_value: currentLead.seller_stage,
        new_value: body.seller_stage,
      });
    }
    if (events.length > 0) {
      await supabase.from("lead_events").insert(events);
    }
  }

  return NextResponse.json(data);
}
```

- [ ] **Step 3: Create notes route**

Create `crm/src/app/api/leads/[id]/notes/route.ts`:

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("lead_notes")
    .select("*")
    .eq("lead_id", id)
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { author, content } = await request.json();

  const { data, error } = await supabase
    .from("lead_notes")
    .insert({ lead_id: id, author, content })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 4: Create events route**

Create `crm/src/app/api/leads/[id]/events/route.ts`:

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("lead_events")
    .select("*")
    .eq("lead_id", id)
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}
```

- [ ] **Step 5: Commit**

```bash
git add crm/src/app/api/leads/route.ts crm/src/app/api/leads/[id]/route.ts crm/src/app/api/leads/[id]/notes/route.ts crm/src/app/api/leads/[id]/events/route.ts
git commit -m "feat: add leads CRUD, notes, and events API routes"
```

---

### Task 4: API Routes — Import and Export CSV

**Files:**
- Create: `crm/src/app/api/leads/import/route.ts`
- Create: `crm/src/app/api/leads/export/route.ts`

- [ ] **Step 1: Create import route**

Create `crm/src/app/api/leads/import/route.ts`:

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

interface ImportLead {
  phone: string;
  name?: string;
  email?: string;
  instagram?: string;
  company?: string;
  cnpj?: string;
  razao_social?: string;
  nome_fantasia?: string;
  endereco?: string;
  telefone_comercial?: string;
  stage?: string;
  seller_stage?: string;
}

export async function POST(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { leads, skipDuplicates } = (await request.json()) as {
    leads: ImportLead[];
    skipDuplicates: boolean;
  };

  // Get existing phones
  const phones = leads.map((l) => l.phone);
  const { data: existing } = await supabase
    .from("leads")
    .select("phone")
    .in("phone", phones);

  const existingPhones = new Set((existing || []).map((e) => e.phone));

  const toInsert: ImportLead[] = [];
  const toUpdate: ImportLead[] = [];
  const skipped: string[] = [];

  for (const lead of leads) {
    if (existingPhones.has(lead.phone)) {
      if (skipDuplicates) {
        skipped.push(lead.phone);
      } else {
        toUpdate.push(lead);
      }
    } else {
      toInsert.push(lead);
    }
  }

  let insertedCount = 0;
  let updatedCount = 0;

  if (toInsert.length > 0) {
    const rows = toInsert.map((l) => ({
      phone: l.phone,
      name: l.name || null,
      email: l.email || null,
      instagram: l.instagram || null,
      company: l.company || null,
      cnpj: l.cnpj || null,
      razao_social: l.razao_social || null,
      nome_fantasia: l.nome_fantasia || null,
      endereco: l.endereco || null,
      telefone_comercial: l.telefone_comercial || null,
      stage: l.stage || "secretaria",
      seller_stage: l.seller_stage || "novo",
      channel: "manual" as const,
      status: "active" as const,
    }));
    const { error } = await supabase.from("leads").insert(rows);
    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }
    insertedCount = rows.length;
  }

  for (const lead of toUpdate) {
    const updateData: Record<string, unknown> = {};
    if (lead.name) updateData.name = lead.name;
    if (lead.email) updateData.email = lead.email;
    if (lead.company) updateData.company = lead.company;
    if (lead.cnpj) updateData.cnpj = lead.cnpj;
    if (lead.razao_social) updateData.razao_social = lead.razao_social;
    if (lead.nome_fantasia) updateData.nome_fantasia = lead.nome_fantasia;
    if (lead.endereco) updateData.endereco = lead.endereco;
    if (lead.telefone_comercial) updateData.telefone_comercial = lead.telefone_comercial;

    if (Object.keys(updateData).length > 0) {
      await supabase.from("leads").update(updateData).eq("phone", lead.phone);
      updatedCount++;
    }
  }

  return NextResponse.json({
    inserted: insertedCount,
    updated: updatedCount,
    skipped: skipped.length,
  });
}
```

- [ ] **Step 2: Create export route**

Create `crm/src/app/api/leads/export/route.ts`:

```typescript
import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();

  const { data: leads, error } = await supabase
    .from("leads")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const headers = [
    "nome", "telefone", "email", "instagram", "empresa", "cnpj",
    "razao_social", "nome_fantasia", "endereco", "telefone_comercial",
    "stage", "seller_stage", "canal", "valor_venda", "criado_em",
  ];

  const rows = (leads || []).map((l) => [
    l.name || "",
    l.phone,
    l.email || "",
    l.instagram || "",
    l.company || "",
    l.cnpj || "",
    l.razao_social || "",
    l.nome_fantasia || "",
    l.endereco || "",
    l.telefone_comercial || "",
    l.stage,
    l.seller_stage,
    l.channel,
    l.sale_value || 0,
    l.created_at,
  ]);

  const csvContent = [
    headers.join(","),
    ...rows.map((r) =>
      r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")
    ),
  ].join("\n");

  return new NextResponse(csvContent, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="leads-${new Date().toISOString().slice(0, 10)}.csv"`,
    },
  });
}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/api/leads/import/route.ts crm/src/app/api/leads/export/route.ts
git commit -m "feat: add leads CSV import and export API routes"
```

---

### Task 5: Sidebar — Add Leads Nav Item

**Files:**
- Modify: `crm/src/components/sidebar.tsx`

- [ ] **Step 1: Add Leads item to NAV_ITEMS**

In `crm/src/components/sidebar.tsx`, add the Leads nav item after the Qualificacao item (index 1) in the `NAV_ITEMS` array. Insert this object after the Qualificacao entry:

```typescript
  {
    href: "/leads",
    label: "Leads",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
      </svg>
    ),
  },
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/sidebar.tsx
git commit -m "feat: add Leads item to sidebar navigation"
```

---

### Task 6: Lead Grid Card Component

**Files:**
- Create: `crm/src/components/leads/lead-grid-card.tsx`

- [ ] **Step 1: Create the card component**

Create `crm/src/components/leads/lead-grid-card.tsx`:

```typescript
"use client";

import type { Lead, Tag } from "@/lib/types";
import { getTemperature, TEMPERATURE_CONFIG } from "@/lib/temperature";
import { AGENT_STAGES, SELLER_STAGES } from "@/lib/constants";

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "Nunca";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "agora";
  if (mins < 60) return `${mins}min atras`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h atras`;
  const days = Math.floor(hours / 24);
  return `${days}d atras`;
}

function formatCurrency(value: number): string {
  if (value === 0) return "\u2014";
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

interface LeadGridCardProps {
  lead: Lead;
  tags: Tag[];
  onClick: (lead: Lead) => void;
}

export function LeadGridCard({ lead, tags, onClick }: LeadGridCardProps) {
  const temp = getTemperature(lead.last_msg_at);
  const tempConfig = TEMPERATURE_CONFIG[temp];
  const stageInfo = AGENT_STAGES.find((s) => s.key === lead.stage);
  const sellerInfo = SELLER_STAGES.find((s) => s.key === lead.seller_stage);
  const initials = (lead.name || lead.phone)
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");

  return (
    <button
      onClick={() => onClick(lead)}
      className="w-full text-left bg-white rounded-xl p-[18px] border border-[#e5e5dc] cursor-pointer transition-all duration-150 hover:-translate-y-[2px] hover:shadow-[0_8px_24px_rgba(0,0,0,0.08)]"
      style={{ borderLeft: `4px solid ${tempConfig.borderColor}` }}
    >
      {/* Header: Avatar + Name + Temp Badge */}
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center gap-2.5">
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center font-semibold text-sm"
            style={{ background: stageInfo?.avatarColor || "#c8cc8e", color: "#1f1f1f" }}
          >
            {initials}
          </div>
          <div>
            <p className="text-[14px] font-semibold text-[#1f1f1f]">
              {lead.name || lead.phone}
            </p>
            <p className="text-[12px] text-[#9ca3af]">{lead.phone}</p>
          </div>
        </div>
        <span
          className="text-[10px] font-semibold px-2 py-0.5 rounded-xl"
          style={{ background: tempConfig.bg, color: tempConfig.color }}
        >
          {tempConfig.label.toUpperCase()}
        </span>
      </div>

      {/* Tags */}
      <div className="flex gap-1.5 flex-wrap mb-2.5">
        {stageInfo && (
          <span className="bg-[#f3f4f6] px-2 py-0.5 rounded-[10px] text-[11px] text-[#5f6368]">
            {stageInfo.label}
          </span>
        )}
        {tags.slice(0, 2).map((tag) => (
          <span
            key={tag.id}
            className="px-2 py-0.5 rounded-[10px] text-[11px] font-medium"
            style={{ backgroundColor: tag.color + "22", color: tag.color }}
          >
            {tag.name}
          </span>
        ))}
        {tags.length > 2 && (
          <span className="text-[11px] text-[#9ca3af]">+{tags.length - 2}</span>
        )}
      </div>

      {/* Company + Value */}
      <div className="flex justify-between text-[12px] text-[#9ca3af]">
        <span>{lead.company || lead.razao_social || "\u2014"}</span>
        <span className="font-semibold text-[#4ade80]">
          {formatCurrency(lead.sale_value || 0)}
        </span>
      </div>

      {/* Footer */}
      <div className="flex justify-between text-[11px] text-[#b0b0b0] mt-2 pt-2 border-t border-[#f3f3f0]">
        <span>
          {sellerInfo?.label || "Novo"} · {stageInfo?.label || lead.stage}
        </span>
        <span>Ultima msg: {timeAgo(lead.last_msg_at)}</span>
      </div>
    </button>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/leads/lead-grid-card.tsx
git commit -m "feat: create LeadGridCard component with temperature styling"
```

---

### Task 7: Filter Bar Component

**Files:**
- Create: `crm/src/components/leads/leads-filter-bar.tsx`

- [ ] **Step 1: Create the filter bar**

Create `crm/src/components/leads/leads-filter-bar.tsx`:

```typescript
"use client";

import { AGENT_STAGES, SELLER_STAGES, LEAD_CHANNELS } from "@/lib/constants";
import type { Temperature } from "@/lib/temperature";
import { TEMPERATURE_CONFIG } from "@/lib/temperature";
import type { Tag } from "@/lib/types";

export interface LeadFilters {
  search: string;
  temperature: Temperature | "";
  stage: string;
  sellerStage: string;
  tagId: string;
  channel: string;
}

interface LeadsFilterBarProps {
  filters: LeadFilters;
  onChange: (filters: LeadFilters) => void;
  tags: Tag[];
  totalCount: number;
  filteredCount: number;
}

export function LeadsFilterBar({
  filters,
  onChange,
  tags,
  totalCount,
  filteredCount,
}: LeadsFilterBarProps) {
  function update(partial: Partial<LeadFilters>) {
    onChange({ ...filters, ...partial });
  }

  function clearAll() {
    onChange({ search: "", temperature: "", stage: "", sellerStage: "", tagId: "", channel: "" });
  }

  const activeFilters: { label: string; key: keyof LeadFilters }[] = [];
  if (filters.temperature) {
    activeFilters.push({ label: TEMPERATURE_CONFIG[filters.temperature].label, key: "temperature" });
  }
  if (filters.stage) {
    const s = AGENT_STAGES.find((a) => a.key === filters.stage);
    activeFilters.push({ label: s?.label || filters.stage, key: "stage" });
  }
  if (filters.sellerStage) {
    const s = SELLER_STAGES.find((a) => a.key === filters.sellerStage);
    activeFilters.push({ label: s?.label || filters.sellerStage, key: "sellerStage" });
  }
  if (filters.tagId) {
    const t = tags.find((tag) => tag.id === filters.tagId);
    activeFilters.push({ label: t?.name || "Tag", key: "tagId" });
  }
  if (filters.channel) {
    const c = LEAD_CHANNELS.find((ch) => ch.key === filters.channel);
    activeFilters.push({ label: c?.label || filters.channel, key: "channel" });
  }

  return (
    <div className="bg-white rounded-xl p-4 border border-[#e5e5dc] mb-5">
      <div className="flex gap-2.5 items-center flex-wrap">
        {/* Search */}
        <div className="flex-1 min-w-[220px] relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9ca3af]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            type="text"
            value={filters.search}
            onChange={(e) => update({ search: e.target.value })}
            placeholder="Buscar por nome, telefone, empresa..."
            className="w-full py-2 pl-9 pr-3 rounded-lg border border-[#e5e5dc] text-[13px] outline-none focus:border-[#c8cc8e] transition-colors"
          />
        </div>

        {/* Temperature */}
        <select
          value={filters.temperature}
          onChange={(e) => update({ temperature: e.target.value as Temperature | "" })}
          className="py-2 px-3 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] bg-white cursor-pointer"
        >
          <option value="">Temperatura</option>
          <option value="quente">Quente</option>
          <option value="morno">Morno</option>
          <option value="frio">Frio</option>
        </select>

        {/* Stage */}
        <select
          value={filters.stage}
          onChange={(e) => update({ stage: e.target.value })}
          className="py-2 px-3 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] bg-white cursor-pointer"
        >
          <option value="">Stage</option>
          {AGENT_STAGES.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>

        {/* Seller Stage */}
        <select
          value={filters.sellerStage}
          onChange={(e) => update({ sellerStage: e.target.value })}
          className="py-2 px-3 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] bg-white cursor-pointer"
        >
          <option value="">Etapa Vendas</option>
          {SELLER_STAGES.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>

        {/* Tags */}
        <select
          value={filters.tagId}
          onChange={(e) => update({ tagId: e.target.value })}
          className="py-2 px-3 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] bg-white cursor-pointer"
        >
          <option value="">Tags</option>
          {tags.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>

        {/* Channel */}
        <select
          value={filters.channel}
          onChange={(e) => update({ channel: e.target.value })}
          className="py-2 px-3 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] bg-white cursor-pointer"
        >
          <option value="">Canal</option>
          {LEAD_CHANNELS.map((c) => (
            <option key={c.key} value={c.key}>{c.label}</option>
          ))}
        </select>

        {/* Clear */}
        {activeFilters.length > 0 && (
          <button
            onClick={clearAll}
            className="py-2 px-3.5 rounded-lg border border-[#e5e5dc] bg-white text-[#9ca3af] text-[13px] cursor-pointer hover:bg-[#f6f7ed] transition-colors"
          >
            Limpar
          </button>
        )}
      </div>

      {/* Active filter chips */}
      {activeFilters.length > 0 && (
        <div className="flex gap-2 mt-3 flex-wrap items-center">
          {activeFilters.map((f) => (
            <span
              key={f.key}
              className="bg-[#f6f7ed] text-[#5f6368] px-3 py-1 rounded-full text-[12px] flex items-center gap-1.5"
            >
              {f.label}
              <button
                onClick={() => update({ [f.key]: "" })}
                className="text-[#9ca3af] hover:text-[#5f6368] ml-0.5"
              >
                x
              </button>
            </span>
          ))}
          <span className="text-[12px] text-[#9ca3af]">
            Mostrando {filteredCount} de {totalCount} leads
          </span>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/leads/leads-filter-bar.tsx
git commit -m "feat: create LeadsFilterBar component"
```

---

### Task 8: Lead Detail Modal

**Files:**
- Create: `crm/src/components/leads/lead-detail-modal.tsx`

- [ ] **Step 1: Create the detail modal component**

Create `crm/src/components/leads/lead-detail-modal.tsx`. This is a large component with 4 tabs. Below is the full implementation:

```typescript
"use client";

import { useState, useEffect } from "react";
import type { Lead, Tag, LeadNote, LeadEvent } from "@/lib/types";
import { getTemperature, TEMPERATURE_CONFIG } from "@/lib/temperature";
import { AGENT_STAGES, SELLER_STAGES, LEAD_CHANNELS } from "@/lib/constants";

interface LeadDetailModalProps {
  lead: Lead;
  tags: Tag[];
  leadTagIds: string[];
  onClose: () => void;
  onSave: (leadId: string, data: Partial<Lead>) => Promise<void>;
  onTagsChange: (leadId: string, tagIds: string[]) => Promise<void>;
}

type TabKey = "dados" | "campanhas" | "tags_notas" | "metricas";

const TABS: { key: TabKey; label: string }[] = [
  { key: "dados", label: "Dados Gerais" },
  { key: "campanhas", label: "Campanhas" },
  { key: "tags_notas", label: "Tags & Notas" },
  { key: "metricas", label: "Metricas" },
];

export function LeadDetailModal({
  lead,
  tags,
  leadTagIds,
  onClose,
  onSave,
  onTagsChange,
}: LeadDetailModalProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("dados");
  const [form, setForm] = useState({ ...lead });
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notes, setNotes] = useState<LeadNote[]>([]);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [newNote, setNewNote] = useState("");
  const [campaigns, setCampaigns] = useState<Array<{
    campaign_name: string;
    campaign_created_at: string;
    status: string;
    current_step: number;
    max_messages: number;
    total_messages_sent: number;
    next_send_at: string | null;
    responded_at: string | null;
  }>>([]);
  const [currentTagIds, setCurrentTagIds] = useState<string[]>(leadTagIds);
  const [showTagDropdown, setShowTagDropdown] = useState(false);

  const temp = getTemperature(lead.last_msg_at);
  const tempConfig = TEMPERATURE_CONFIG[temp];
  const initials = (lead.name || lead.phone)
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");

  // Fetch notes and events when tab changes
  useEffect(() => {
    if (activeTab === "tags_notas") {
      fetch(`/api/leads/${lead.id}/notes`).then((r) => r.json()).then(setNotes);
      fetch(`/api/leads/${lead.id}/events`).then((r) => r.json()).then(setEvents);
    }
    if (activeTab === "campanhas") {
      // Fetch cadence_state for this lead
      import("@/lib/supabase/client").then(({ createClient }) => {
        const supabase = createClient();
        supabase
          .from("cadence_state")
          .select("*, campaigns(name, created_at)")
          .eq("lead_id", lead.id)
          .then(({ data }) => {
            if (data) {
              setCampaigns(
                data.map((cs: Record<string, unknown>) => {
                  const camp = cs.campaigns as { name: string; created_at: string } | null;
                  return {
                    campaign_name: camp?.name || "Campanha",
                    campaign_created_at: camp?.created_at || "",
                    status: cs.status as string,
                    current_step: cs.current_step as number,
                    max_messages: cs.max_messages as number,
                    total_messages_sent: cs.total_messages_sent as number,
                    next_send_at: cs.next_send_at as string | null,
                    responded_at: cs.responded_at as string | null,
                  };
                })
              );
            }
          });
      });
    }
  }, [activeTab, lead.id]);

  function updateField(field: string, value: string | number) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setDirty(true);
  }

  async function handleSave() {
    setSaving(true);
    const changes: Record<string, unknown> = {};
    for (const key of Object.keys(form) as (keyof Lead)[]) {
      if (form[key] !== lead[key]) {
        changes[key] = form[key];
      }
    }
    await onSave(lead.id, changes as Partial<Lead>);
    setSaving(false);
    setDirty(false);
  }

  async function handleAddNote() {
    if (!newNote.trim()) return;
    const res = await fetch(`/api/leads/${lead.id}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ author: "Rafael", content: newNote.trim() }),
    });
    const note = await res.json();
    setNotes((prev) => [note, ...prev]);
    setNewNote("");
  }

  async function handleToggleTag(tagId: string) {
    let newTagIds: string[];
    if (currentTagIds.includes(tagId)) {
      newTagIds = currentTagIds.filter((id) => id !== tagId);
    } else {
      newTagIds = [...currentTagIds, tagId];
    }
    setCurrentTagIds(newTagIds);
    await onTagsChange(lead.id, newTagIds);
  }

  const availableTags = tags.filter((t) => !currentTagIds.includes(t.id));
  const activeTags = tags.filter((t) => currentTagIds.includes(t.id));

  // Timeline: merge notes + events sorted by date
  const timeline = [
    ...notes.map((n) => ({ type: "note" as const, data: n, date: n.created_at })),
    ...events.map((e) => ({ type: "event" as const, data: e, date: e.created_at })),
  ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  function formatEventText(event: LeadEvent): string {
    switch (event.event_type) {
      case "stage_change":
        return `Stage alterado de ${event.old_value} para ${event.new_value}`;
      case "seller_stage_change":
        return `Etapa vendas alterada de ${event.old_value} para ${event.new_value}`;
      case "campaign_added":
        return `Adicionado a campanha ${event.new_value}`;
      case "campaign_removed":
        return `Removido de campanha ${event.new_value}`;
      case "first_response":
        return "Primeira resposta recebida";
      default:
        return event.event_type;
    }
  }

  const daysInCrm = Math.floor((Date.now() - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24));
  const firstResponseTime = lead.first_response_at
    ? Math.round((new Date(lead.first_response_at).getTime() - new Date(lead.created_at).getTime()) / 60000)
    : null;
  const firstResponseStr = firstResponseTime !== null
    ? firstResponseTime < 60 ? `${firstResponseTime}min` : `${Math.round(firstResponseTime / 60)}h`
    : "\u2014";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-12" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative bg-white rounded-2xl w-full max-w-[720px] overflow-hidden shadow-[0_25px_50px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-[#f3f3f0] flex justify-between items-center">
          <div className="flex items-center gap-3.5">
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center font-bold text-base"
              style={{ background: "#c8cc8e", color: "#1f1f1f" }}
            >
              {initials}
            </div>
            <div>
              <h3 className="text-[18px] font-semibold text-[#1f1f1f]">
                {lead.name || lead.phone}
              </h3>
              <p className="text-[13px] text-[#9ca3af]">
                {lead.phone}{lead.company ? ` · ${lead.company}` : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2.5">
            <span
              className="text-[10px] font-semibold px-2.5 py-1 rounded-xl"
              style={{ background: tempConfig.bg, color: tempConfig.color }}
            >
              {tempConfig.label.toUpperCase()}
            </span>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg border border-[#e5e5dc] bg-white flex items-center justify-center text-[#9ca3af] hover:text-[#1f1f1f] transition-colors"
            >
              x
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[#f3f3f0] px-6">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-5 py-3 text-[13px] font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? "text-[#1f1f1f] border-[#1f1f1f]"
                  : "text-[#9ca3af] border-transparent hover:text-[#5f6368]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div className="p-6 max-h-[450px] overflow-y-auto">

          {/* TAB: Dados Gerais */}
          {activeTab === "dados" && (
            <div>
              <div className="grid grid-cols-2 gap-5">
                {/* Contato */}
                <div>
                  <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Contato</p>
                  <div className="space-y-3">
                    {([
                      { label: "Nome", field: "name", type: "text" },
                      { label: "Telefone", field: "phone", type: "text", readonly: true },
                      { label: "Email", field: "email", type: "text" },
                      { label: "Instagram", field: "instagram", type: "text" },
                    ] as const).map(({ label, field, readonly }) => (
                      <div key={field}>
                        <label className="text-[11px] text-[#b0b0b0] block mb-0.5">{label}</label>
                        <input
                          value={(form[field] as string) || ""}
                          onChange={(e) => updateField(field, e.target.value)}
                          readOnly={readonly}
                          className={`w-full text-[14px] text-[#1f1f1f] px-2.5 py-1.5 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] transition-colors ${readonly ? "bg-[#f6f7ed] text-[#9ca3af]" : ""}`}
                        />
                      </div>
                    ))}
                    <div>
                      <label className="text-[11px] text-[#b0b0b0] block mb-0.5">Canal</label>
                      <select
                        value={form.channel || ""}
                        onChange={(e) => updateField("channel", e.target.value)}
                        className="w-full text-[14px] text-[#1f1f1f] px-2.5 py-1.5 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] bg-white"
                      >
                        {LEAD_CHANNELS.map((c) => (
                          <option key={c.key} value={c.key}>{c.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>

                {/* Empresa B2B */}
                <div>
                  <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Empresa (B2B)</p>
                  <div className="space-y-3">
                    {([
                      { label: "Razao Social", field: "razao_social" },
                      { label: "Nome Fantasia", field: "nome_fantasia" },
                      { label: "CNPJ", field: "cnpj" },
                      { label: "Telefone Comercial", field: "telefone_comercial" },
                      { label: "Endereco", field: "endereco" },
                    ] as const).map(({ label, field }) => (
                      <div key={field}>
                        <label className="text-[11px] text-[#b0b0b0] block mb-0.5">{label}</label>
                        <input
                          value={(form[field] as string) || ""}
                          onChange={(e) => updateField(field, e.target.value)}
                          className="w-full text-[14px] text-[#1f1f1f] px-2.5 py-1.5 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] transition-colors"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* CRM Status row */}
              <div className="mt-5 pt-4 border-t border-[#f3f3f0]">
                <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Status no CRM</p>
                <div className="grid grid-cols-4 gap-3">
                  <div className="bg-[#f6f7ed] rounded-lg p-3">
                    <label className="text-[11px] text-[#b0b0b0] block mb-1">Stage (IA)</label>
                    <select
                      value={form.stage}
                      onChange={(e) => updateField("stage", e.target.value)}
                      className="w-full text-[13px] font-semibold text-[#1f1f1f] bg-transparent outline-none cursor-pointer"
                    >
                      {AGENT_STAGES.map((s) => (
                        <option key={s.key} value={s.key}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="bg-[#f6f7ed] rounded-lg p-3">
                    <label className="text-[11px] text-[#b0b0b0] block mb-1">Etapa Vendas</label>
                    <select
                      value={form.seller_stage}
                      onChange={(e) => updateField("seller_stage", e.target.value)}
                      className="w-full text-[13px] font-semibold text-[#1f1f1f] bg-transparent outline-none cursor-pointer"
                    >
                      {SELLER_STAGES.map((s) => (
                        <option key={s.key} value={s.key}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="bg-[#f6f7ed] rounded-lg p-3">
                    <label className="text-[11px] text-[#b0b0b0] block mb-1">Atribuido a</label>
                    <input
                      value={(form.assigned_to as string) || ""}
                      onChange={(e) => updateField("assigned_to", e.target.value)}
                      placeholder="Ninguem"
                      className="w-full text-[13px] font-semibold text-[#1f1f1f] bg-transparent outline-none"
                    />
                  </div>
                  <div className="bg-[#f6f7ed] rounded-lg p-3">
                    <label className="text-[11px] text-[#b0b0b0] block mb-1">Valor de Venda</label>
                    <input
                      value={form.sale_value || ""}
                      onChange={(e) => updateField("sale_value", Number(e.target.value) || 0)}
                      type="number"
                      placeholder="0"
                      className="w-full text-[13px] font-semibold text-[#4ade80] bg-transparent outline-none"
                    />
                  </div>
                </div>
              </div>

              {/* Save button */}
              {dirty && (
                <div className="mt-4 flex justify-end">
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="px-5 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors disabled:opacity-50"
                  >
                    {saving ? "Salvando..." : "Salvar alteracoes"}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* TAB: Campanhas */}
          {activeTab === "campanhas" && (
            <div>
              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-4">
                Campanhas participadas ({campaigns.length})
              </p>
              {campaigns.length === 0 && (
                <p className="text-[13px] text-[#9ca3af] text-center py-8">Nenhuma campanha encontrada.</p>
              )}
              <div className="space-y-3">
                {campaigns.map((c, i) => {
                  const statusColors: Record<string, { bg: string; text: string }> = {
                    active: { bg: "#fefce8", text: "#ca8a04" },
                    responded: { bg: "#f0fdf4", text: "#22c55e" },
                    exhausted: { bg: "#fee2e2", text: "#ef4444" },
                    cooled: { bg: "#f4f4f0", text: "#9ca3af" },
                  };
                  const statusLabels: Record<string, string> = {
                    active: "Ativa", responded: "Respondeu", exhausted: "Esgotado", cooled: "Esfriado",
                  };
                  const sc = statusColors[c.status] || statusColors.active;
                  return (
                    <div key={i} className="border border-[#e5e5dc] rounded-[10px] p-4">
                      <div className="flex justify-between items-center mb-2.5">
                        <div>
                          <p className="text-[14px] font-semibold text-[#1f1f1f]">{c.campaign_name}</p>
                          <p className="text-[12px] text-[#9ca3af]">
                            Criada em {new Date(c.campaign_created_at).toLocaleDateString("pt-BR")}
                          </p>
                        </div>
                        <span
                          className="text-[11px] font-semibold px-2.5 py-0.5 rounded-[10px]"
                          style={{ background: sc.bg, color: sc.text }}
                        >
                          {statusLabels[c.status] || c.status}
                        </span>
                      </div>
                      <div className="grid grid-cols-3 gap-2.5">
                        <div className="bg-[#f6f7ed] rounded-md px-3 py-2">
                          <p className="text-[10px] text-[#b0b0b0]">Cadencia</p>
                          <p className="text-[13px] font-semibold text-[#1f1f1f]">Step {c.current_step} de {c.max_messages}</p>
                        </div>
                        <div className="bg-[#f6f7ed] rounded-md px-3 py-2">
                          <p className="text-[10px] text-[#b0b0b0]">Mensagens</p>
                          <p className="text-[13px] font-semibold text-[#1f1f1f]">{c.total_messages_sent} enviadas</p>
                        </div>
                        <div className="bg-[#f6f7ed] rounded-md px-3 py-2">
                          <p className="text-[10px] text-[#b0b0b0]">
                            {c.responded_at ? "Respondeu em" : "Proximo envio"}
                          </p>
                          <p className="text-[13px] font-semibold text-[#1f1f1f]">
                            {c.responded_at
                              ? new Date(c.responded_at).toLocaleDateString("pt-BR")
                              : c.next_send_at
                                ? new Date(c.next_send_at).toLocaleDateString("pt-BR")
                                : "\u2014"}
                          </p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* TAB: Tags & Notas */}
          {activeTab === "tags_notas" && (
            <div>
              {/* Tags */}
              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Tags</p>
              <div className="flex gap-2 flex-wrap mb-3">
                {activeTags.map((tag) => (
                  <span
                    key={tag.id}
                    className="px-3 py-1 rounded-full text-[12px] flex items-center gap-1.5"
                    style={{ background: tag.color + "22", color: tag.color }}
                  >
                    {tag.name}
                    <button
                      onClick={() => handleToggleTag(tag.id)}
                      className="opacity-60 hover:opacity-100"
                    >
                      x
                    </button>
                  </span>
                ))}
                <div className="relative">
                  <button
                    onClick={() => setShowTagDropdown(!showTagDropdown)}
                    className="px-3 py-1 rounded-full text-[12px] border border-dashed border-[#d1d5db] text-[#9ca3af] hover:border-[#9ca3af] transition-colors"
                  >
                    + Adicionar tag
                  </button>
                  {showTagDropdown && availableTags.length > 0 && (
                    <div className="absolute top-full left-0 mt-1 bg-white border border-[#e5e5dc] rounded-lg shadow-lg z-10 py-1 min-w-[150px]">
                      {availableTags.map((tag) => (
                        <button
                          key={tag.id}
                          onClick={() => { handleToggleTag(tag.id); setShowTagDropdown(false); }}
                          className="w-full text-left px-3 py-1.5 text-[12px] hover:bg-[#f6f7ed] flex items-center gap-2"
                        >
                          <span className="w-2.5 h-2.5 rounded-full" style={{ background: tag.color }} />
                          {tag.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Add note */}
              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mt-5 mb-3">Notas & Timeline</p>
              <div className="flex gap-2 mb-4">
                <input
                  value={newNote}
                  onChange={(e) => setNewNote(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddNote()}
                  placeholder="Adicionar uma nota..."
                  className="flex-1 px-3.5 py-2 rounded-lg border border-[#e5e5dc] text-[13px] outline-none focus:border-[#c8cc8e]"
                />
                <button
                  onClick={handleAddNote}
                  className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors"
                >
                  Salvar
                </button>
              </div>

              {/* Timeline */}
              <div className="space-y-2.5">
                {timeline.map((item) => (
                  <div
                    key={`${item.type}-${item.data.id}`}
                    className={`rounded-[10px] p-3.5 border ${
                      item.type === "note"
                        ? "border-[#e5e5dc] bg-white"
                        : "border-[#f3f3f0] bg-[#f6f7ed]"
                    }`}
                  >
                    <div className="flex justify-between mb-1">
                      <p className="text-[12px] font-semibold text-[#1f1f1f]">
                        {item.type === "note"
                          ? (item.data as LeadNote).author
                          : "Sistema"}
                      </p>
                      <p className="text-[11px] text-[#b0b0b0]">
                        {new Date(item.date).toLocaleString("pt-BR", {
                          day: "2-digit", month: "2-digit", year: "numeric",
                          hour: "2-digit", minute: "2-digit",
                        })}
                      </p>
                    </div>
                    <p className="text-[13px] text-[#5f6368] leading-relaxed">
                      {item.type === "note"
                        ? (item.data as LeadNote).content
                        : formatEventText(item.data as LeadEvent)}
                    </p>
                  </div>
                ))}
                {timeline.length === 0 && (
                  <p className="text-[13px] text-[#9ca3af] text-center py-4">Nenhuma nota ou evento ainda.</p>
                )}
              </div>
            </div>
          )}

          {/* TAB: Metricas */}
          {activeTab === "metricas" && (
            <div>
              {/* KPI cards */}
              <div className="grid grid-cols-3 gap-3 mb-5">
                <div className="bg-[#f6f7ed] rounded-[10px] p-4 text-center">
                  <p className="text-[11px] text-[#b0b0b0] uppercase">Temperatura</p>
                  <p className="text-[14px] font-bold mt-2" style={{ color: tempConfig.color }}>
                    {tempConfig.label}
                  </p>
                  <p className="text-[11px] text-[#9ca3af] mt-0.5">
                    Ultima msg: {lead.last_msg_at ? new Date(lead.last_msg_at).toLocaleDateString("pt-BR") : "Nunca"}
                  </p>
                </div>
                <div className="bg-[#f6f7ed] rounded-[10px] p-4 text-center">
                  <p className="text-[11px] text-[#b0b0b0] uppercase">Valor de Venda</p>
                  <p className="text-[24px] font-bold text-[#4ade80] mt-1">
                    {lead.sale_value ? `R$ ${lead.sale_value.toLocaleString("pt-BR")}` : "\u2014"}
                  </p>
                </div>
                <div className="bg-[#f6f7ed] rounded-[10px] p-4 text-center">
                  <p className="text-[11px] text-[#b0b0b0] uppercase">1a Resposta</p>
                  <p className="text-[24px] font-bold text-[#1f1f1f] mt-1">{firstResponseStr}</p>
                </div>
              </div>

              {/* Engagement */}
              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Engajamento</p>
              <div className="grid grid-cols-3 gap-2.5">
                <div className="border border-[#e5e5dc] rounded-lg p-3 text-center">
                  <p className="text-[20px] font-bold text-[#1f1f1f]">{campaigns.length}</p>
                  <p className="text-[11px] text-[#9ca3af] mt-1">Campanhas</p>
                </div>
                <div className="border border-[#e5e5dc] rounded-lg p-3 text-center">
                  <p className="text-[20px] font-bold text-[#1f1f1f]">{daysInCrm}d</p>
                  <p className="text-[11px] text-[#9ca3af] mt-1">No CRM</p>
                </div>
                <div className="border border-[#e5e5dc] rounded-lg p-3 text-center">
                  <p className="text-[20px] font-bold text-[#1f1f1f]">
                    {lead.entered_stage_at
                      ? `${Math.floor((Date.now() - new Date(lead.entered_stage_at).getTime()) / (1000 * 60 * 60 * 24))}d`
                      : "\u2014"}
                  </p>
                  <p className="text-[11px] text-[#9ca3af] mt-1">No stage atual</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/leads/lead-detail-modal.tsx
git commit -m "feat: create LeadDetailModal with 4 tabs (dados, campanhas, tags/notas, metricas)"
```

---

### Task 9: Lead Create Modal

**Files:**
- Create: `crm/src/components/leads/lead-create-modal.tsx`

- [ ] **Step 1: Create the new lead form modal**

Create `crm/src/components/leads/lead-create-modal.tsx`:

```typescript
"use client";

import { useState } from "react";
import { AGENT_STAGES, SELLER_STAGES, LEAD_CHANNELS } from "@/lib/constants";

interface LeadCreateModalProps {
  onClose: () => void;
  onCreate: (data: Record<string, string>) => Promise<{ error?: string }>;
}

export function LeadCreateModal({ onClose, onCreate }: LeadCreateModalProps) {
  const [form, setForm] = useState({
    name: "",
    phone: "",
    email: "",
    instagram: "",
    company: "",
    cnpj: "",
    stage: "secretaria",
    seller_stage: "novo",
    channel: "manual",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function update(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim() || !form.phone.trim()) {
      setError("Nome e telefone sao obrigatorios.");
      return;
    }
    setSaving(true);
    const result = await onCreate(form);
    setSaving(false);
    if (result.error) {
      setError(result.error);
    } else {
      onClose();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-16" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative bg-white rounded-2xl w-full max-w-[500px] overflow-hidden shadow-[0_25px_50px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-5 border-b border-[#f3f3f0] flex justify-between items-center">
          <h3 className="text-[18px] font-semibold text-[#1f1f1f]">Novo Lead</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-lg border border-[#e5e5dc] flex items-center justify-center text-[#9ca3af] hover:text-[#1f1f1f]">
            x
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6">
          <div className="space-y-3">
            {/* Required */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Nome *</label>
                <input
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                  placeholder="Nome do lead"
                />
              </div>
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Telefone *</label>
                <input
                  value={form.phone}
                  onChange={(e) => update("phone", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                  placeholder="+55 11 99999-9999"
                />
              </div>
            </div>

            {/* Optional */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Email</label>
                <input
                  value={form.email}
                  onChange={(e) => update("email", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                />
              </div>
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Instagram</label>
                <input
                  value={form.instagram}
                  onChange={(e) => update("instagram", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Empresa</label>
                <input
                  value={form.company}
                  onChange={(e) => update("company", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                />
              </div>
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">CNPJ</label>
                <input
                  value={form.cnpj}
                  onChange={(e) => update("cnpj", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                />
              </div>
            </div>

            {/* Selects */}
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Stage</label>
                <select
                  value={form.stage}
                  onChange={(e) => update("stage", e.target.value)}
                  className="w-full text-[13px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none bg-white"
                >
                  {AGENT_STAGES.map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Etapa Vendas</label>
                <select
                  value={form.seller_stage}
                  onChange={(e) => update("seller_stage", e.target.value)}
                  className="w-full text-[13px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none bg-white"
                >
                  {SELLER_STAGES.map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Canal</label>
                <select
                  value={form.channel}
                  onChange={(e) => update("channel", e.target.value)}
                  className="w-full text-[13px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none bg-white"
                >
                  {LEAD_CHANNELS.map((c) => (
                    <option key={c.key} value={c.key}>{c.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {error && (
            <p className="text-[13px] text-[#ef4444] mt-3">{error}</p>
          )}

          <div className="flex justify-end mt-5">
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2.5 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors disabled:opacity-50"
            >
              {saving ? "Criando..." : "Criar Lead"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/leads/lead-create-modal.tsx
git commit -m "feat: create LeadCreateModal form component"
```

---

### Task 10: Lead Import Modal (CSV)

**Files:**
- Create: `crm/src/components/leads/lead-import-modal.tsx`

- [ ] **Step 1: Install papaparse**

```bash
cd crm && npm install papaparse && npm install -D @types/papaparse
```

- [ ] **Step 2: Create the import modal**

Create `crm/src/components/leads/lead-import-modal.tsx`:

```typescript
"use client";

import { useState, useRef } from "react";
import Papa from "papaparse";

const LEAD_FIELDS = [
  { key: "", label: "Pular coluna" },
  { key: "phone", label: "Telefone" },
  { key: "name", label: "Nome" },
  { key: "email", label: "Email" },
  { key: "instagram", label: "Instagram" },
  { key: "company", label: "Empresa" },
  { key: "cnpj", label: "CNPJ" },
  { key: "razao_social", label: "Razao Social" },
  { key: "nome_fantasia", label: "Nome Fantasia" },
  { key: "endereco", label: "Endereco" },
  { key: "telefone_comercial", label: "Telefone Comercial" },
  { key: "stage", label: "Stage" },
  { key: "seller_stage", label: "Etapa Vendas" },
];

// Auto-detect mapping by header name
const AUTO_MAP: Record<string, string> = {
  telefone: "phone", phone: "phone", celular: "phone", whatsapp: "phone",
  nome: "name", name: "name",
  email: "email", "e-mail": "email",
  instagram: "instagram",
  empresa: "company", company: "company",
  cnpj: "cnpj",
  "razao social": "razao_social", razao_social: "razao_social",
  "nome fantasia": "nome_fantasia", nome_fantasia: "nome_fantasia",
  endereco: "endereco", address: "endereco",
  "telefone comercial": "telefone_comercial",
  stage: "stage", etapa: "stage",
  seller_stage: "seller_stage", "etapa vendas": "seller_stage",
};

interface LeadImportModalProps {
  onClose: () => void;
  onImportDone: () => void;
}

type Step = "upload" | "mapping" | "confirm";

export function LeadImportModal({ onClose, onImportDone }: LeadImportModalProps) {
  const [step, setStep] = useState<Step>("upload");
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [mapping, setMapping] = useState<Record<number, string>>({});
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<{ inserted: number; updated: number; skipped: number } | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function handleFile(file: File) {
    Papa.parse(file, {
      skipEmptyLines: true,
      complete: (results) => {
        const data = results.data as string[][];
        if (data.length < 2) return;
        const headers = data[0];
        setCsvHeaders(headers);
        setCsvRows(data.slice(1));

        // Auto-detect mapping
        const autoMapping: Record<number, string> = {};
        headers.forEach((h, i) => {
          const normalized = h.toLowerCase().trim();
          if (AUTO_MAP[normalized]) {
            autoMapping[i] = AUTO_MAP[normalized];
          }
        });
        setMapping(autoMapping);
        setStep("mapping");
      },
    });
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".csv")) handleFile(file);
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  async function handleImport() {
    setImporting(true);

    // Build leads from mapping
    const leads = csvRows.map((row) => {
      const lead: Record<string, string> = {};
      Object.entries(mapping).forEach(([colIdx, field]) => {
        if (field) {
          lead[field] = row[Number(colIdx)] || "";
        }
      });
      return lead;
    }).filter((l) => l.phone); // Must have phone

    const res = await fetch("/api/leads/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leads, skipDuplicates }),
    });
    const data = await res.json();
    setResult(data);
    setImporting(false);
    onImportDone();
  }

  const phoneColumnMapped = Object.values(mapping).includes("phone");

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-12" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative bg-white rounded-2xl w-full max-w-[640px] overflow-hidden shadow-[0_25px_50px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-[#f3f3f0] flex justify-between items-center">
          <h3 className="text-[18px] font-semibold text-[#1f1f1f]">Importar Leads (CSV)</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-lg border border-[#e5e5dc] flex items-center justify-center text-[#9ca3af] hover:text-[#1f1f1f]">
            x
          </button>
        </div>

        {/* Steps indicator */}
        <div className="px-6 py-3 flex items-center gap-2 text-[12px] border-b border-[#f3f3f0]">
          {(["Upload", "Mapeamento", "Confirmacao"] as const).map((label, i) => {
            const stepKeys: Step[] = ["upload", "mapping", "confirm"];
            const isActive = stepKeys.indexOf(step) >= i;
            return (
              <div key={label} className="flex items-center gap-2">
                {i > 0 && <span className="text-[#e5e5dc]">&rarr;</span>}
                <span className={`px-2.5 py-0.5 rounded-full ${isActive ? "bg-[#1f1f1f] text-white" : "bg-[#f4f4f0] text-[#9ca3af]"}`}>
                  {i + 1}. {label}
                </span>
              </div>
            );
          })}
        </div>

        <div className="p-6 max-h-[450px] overflow-y-auto">

          {/* Step 1: Upload */}
          {step === "upload" && (
            <div
              className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors ${
                dragActive ? "border-[#c8cc8e] bg-[#f6f7ed]" : "border-[#e5e5dc]"
              }`}
              onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
            >
              <p className="text-[14px] text-[#5f6368] mb-2">Arraste um arquivo CSV aqui</p>
              <p className="text-[12px] text-[#9ca3af] mb-4">ou</p>
              <button
                onClick={() => fileRef.current?.click()}
                className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333]"
              >
                Selecionar arquivo
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".csv"
                onChange={handleFileInput}
                className="hidden"
              />
            </div>
          )}

          {/* Step 2: Mapping */}
          {step === "mapping" && (
            <div>
              <p className="text-[13px] text-[#5f6368] mb-4">
                {csvRows.length} linhas encontradas. Mapeie as colunas do CSV para os campos do lead:
              </p>
              <div className="space-y-2 mb-4">
                {csvHeaders.map((header, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="text-[13px] text-[#1f1f1f] w-40 truncate font-medium">{header}</span>
                    <span className="text-[#9ca3af]">&rarr;</span>
                    <select
                      value={mapping[i] || ""}
                      onChange={(e) => setMapping((prev) => ({ ...prev, [i]: e.target.value }))}
                      className="flex-1 text-[13px] px-3 py-1.5 rounded-lg border border-[#e5e5dc] outline-none bg-white"
                    >
                      {LEAD_FIELDS.map((f) => (
                        <option key={f.key} value={f.key}>{f.label}</option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>

              {/* Preview */}
              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase mb-2">Preview (5 primeiras linhas)</p>
              <div className="overflow-x-auto border border-[#e5e5dc] rounded-lg">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-[#f6f7ed]">
                      {csvHeaders.map((h, i) => (
                        <th key={i} className="px-2 py-1.5 text-left text-[#9ca3af] font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {csvRows.slice(0, 5).map((row, i) => (
                      <tr key={i} className="border-t border-[#f3f3f0]">
                        {row.map((cell, j) => (
                          <td key={j} className="px-2 py-1 text-[#5f6368] truncate max-w-[120px]">{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex justify-end mt-4">
                <button
                  onClick={() => setStep("confirm")}
                  disabled={!phoneColumnMapped}
                  className="px-5 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] disabled:opacity-50"
                >
                  Proximo
                </button>
              </div>
              {!phoneColumnMapped && (
                <p className="text-[12px] text-[#ef4444] mt-2 text-right">Mapeie pelo menos a coluna de telefone.</p>
              )}
            </div>
          )}

          {/* Step 3: Confirm */}
          {step === "confirm" && !result && (
            <div>
              <div className="bg-[#f6f7ed] rounded-xl p-5 mb-4">
                <p className="text-[14px] font-semibold text-[#1f1f1f] mb-2">Resumo da importacao</p>
                <p className="text-[13px] text-[#5f6368]">{csvRows.length} leads serao processados</p>
                <p className="text-[13px] text-[#5f6368]">
                  Campos mapeados: {Object.values(mapping).filter(Boolean).join(", ")}
                </p>
              </div>

              <label className="flex items-center gap-2 mb-4 cursor-pointer">
                <input
                  type="checkbox"
                  checked={skipDuplicates}
                  onChange={(e) => setSkipDuplicates(e.target.checked)}
                  className="rounded"
                />
                <span className="text-[13px] text-[#5f6368]">
                  Pular leads duplicados (mesmo telefone). Desmarque para atualizar dados existentes.
                </span>
              </label>

              <div className="flex justify-between">
                <button
                  onClick={() => setStep("mapping")}
                  className="px-4 py-2 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] hover:bg-[#f6f7ed]"
                >
                  Voltar
                </button>
                <button
                  onClick={handleImport}
                  disabled={importing}
                  className="px-5 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] disabled:opacity-50"
                >
                  {importing ? "Importando..." : "Importar"}
                </button>
              </div>
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="text-center py-6">
              <p className="text-[18px] font-semibold text-[#1f1f1f] mb-3">Importacao concluida!</p>
              <div className="flex justify-center gap-6 mb-5">
                <div>
                  <p className="text-[24px] font-bold text-[#4ade80]">{result.inserted}</p>
                  <p className="text-[12px] text-[#9ca3af]">Inseridos</p>
                </div>
                <div>
                  <p className="text-[24px] font-bold text-[#e8d44d]">{result.updated}</p>
                  <p className="text-[12px] text-[#9ca3af]">Atualizados</p>
                </div>
                <div>
                  <p className="text-[24px] font-bold text-[#9ca3af]">{result.skipped}</p>
                  <p className="text-[12px] text-[#9ca3af]">Pulados</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="px-5 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333]"
              >
                Fechar
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/leads/lead-import-modal.tsx
git commit -m "feat: create LeadImportModal with CSV upload, column mapping, and preview"
```

---

### Task 11: Main Leads Page

**Files:**
- Create: `crm/src/app/(authenticated)/leads/page.tsx`

- [ ] **Step 1: Create the leads page**

Create `crm/src/app/(authenticated)/leads/page.tsx`:

```typescript
"use client";

import { useState, useMemo, useEffect } from "react";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { getTemperature } from "@/lib/temperature";
import { LeadGridCard } from "@/components/leads/lead-grid-card";
import { LeadsFilterBar, type LeadFilters } from "@/components/leads/leads-filter-bar";
import { LeadDetailModal } from "@/components/leads/lead-detail-modal";
import { LeadCreateModal } from "@/components/leads/lead-create-modal";
import { LeadImportModal } from "@/components/leads/lead-import-modal";
import type { Lead, Tag } from "@/lib/types";
import { createClient } from "@/lib/supabase/client";

const LEADS_PER_PAGE = 30;

export default function LeadsPage() {
  const { leads, loading } = useRealtimeLeads();
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, string[]>>({});
  const [filters, setFilters] = useState<LeadFilters>({
    search: "", temperature: "", stage: "", sellerStage: "", tagId: "", channel: "",
  });
  const [page, setPage] = useState(1);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);

  const supabase = createClient();

  // Fetch tags and lead_tags
  useEffect(() => {
    async function fetchTags() {
      const { data: tagsData } = await supabase.from("tags").select("*");
      if (tagsData) setTags(tagsData);

      const { data: ltData } = await supabase.from("lead_tags").select("lead_id, tag_id");
      if (ltData) {
        const map: Record<string, string[]> = {};
        for (const lt of ltData) {
          if (!map[lt.lead_id]) map[lt.lead_id] = [];
          map[lt.lead_id].push(lt.tag_id);
        }
        setLeadTagsMap(map);
      }
    }
    fetchTags();
  }, []);

  // Apply filters
  const filtered = useMemo(() => {
    return leads.filter((lead) => {
      if (filters.search) {
        const q = filters.search.toLowerCase();
        const match =
          (lead.name || "").toLowerCase().includes(q) ||
          lead.phone.includes(q) ||
          (lead.company || "").toLowerCase().includes(q) ||
          (lead.razao_social || "").toLowerCase().includes(q);
        if (!match) return false;
      }
      if (filters.temperature && getTemperature(lead.last_msg_at) !== filters.temperature) return false;
      if (filters.stage && lead.stage !== filters.stage) return false;
      if (filters.sellerStage && lead.seller_stage !== filters.sellerStage) return false;
      if (filters.channel && lead.channel !== filters.channel) return false;
      if (filters.tagId) {
        const leadTags = leadTagsMap[lead.id] || [];
        if (!leadTags.includes(filters.tagId)) return false;
      }
      return true;
    });
  }, [leads, filters, leadTagsMap]);

  // Pagination
  const totalPages = Math.ceil(filtered.length / LEADS_PER_PAGE);
  const paginated = filtered.slice((page - 1) * LEADS_PER_PAGE, page * LEADS_PER_PAGE);

  // Reset page when filters change
  useEffect(() => { setPage(1); }, [filters]);

  // KPIs
  const kpis = useMemo(() => {
    const total = leads.length;
    let quentes = 0, mornos = 0, frios = 0, totalValue = 0;
    for (const lead of leads) {
      const temp = getTemperature(lead.last_msg_at);
      if (temp === "quente") quentes++;
      else if (temp === "morno") mornos++;
      else frios++;
      totalValue += lead.sale_value || 0;
    }
    return { total, quentes, mornos, frios, totalValue };
  }, [leads]);

  function getLeadTags(leadId: string): Tag[] {
    const tagIds = leadTagsMap[leadId] || [];
    return tags.filter((t) => tagIds.includes(t.id));
  }

  async function handleSaveLead(leadId: string, data: Partial<Lead>) {
    await fetch(`/api/leads/${leadId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  }

  async function handleTagsChange(leadId: string, tagIds: string[]) {
    await fetch(`/api/leads/${leadId}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tagIds }),
    });
    setLeadTagsMap((prev) => ({ ...prev, [leadId]: tagIds }));
  }

  async function handleCreateLead(data: Record<string, string>): Promise<{ error?: string }> {
    const res = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json();
      return { error: err.error || "Erro ao criar lead" };
    }
    return {};
  }

  async function handleExport() {
    const res = await fetch("/api/leads/export");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const fmt = (v: number) =>
    v >= 1000000
      ? `R$ ${(v / 1000000).toFixed(1)}M`
      : `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <div className="h-8 w-32 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
          <div className="h-4 w-64 rounded-lg animate-pulse mt-2" style={{ backgroundColor: "#e5e5dc" }} />
        </div>
        <div className="grid grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="card p-5 h-24 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
        <div className="grid grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card p-5 h-40 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-[28px] font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
            Leads
          </h1>
          <p className="text-[14px] mt-1" style={{ color: "var(--text-muted)" }}>
            Gestao completa dos seus contatos
          </p>
        </div>
        <div className="flex gap-2.5">
          <button
            onClick={() => setShowImport(true)}
            className="px-4 py-2 rounded-lg border border-[#e5e5dc] bg-white text-[#1f1f1f] text-[13px] font-medium hover:bg-[#f6f7ed] transition-colors flex items-center gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
            Importar
          </button>
          <button
            onClick={handleExport}
            className="px-4 py-2 rounded-lg border border-[#e5e5dc] bg-white text-[#1f1f1f] text-[13px] font-medium hover:bg-[#f6f7ed] transition-colors flex items-center gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12M12 16.5V3" />
            </svg>
            Exportar
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors flex items-center gap-1.5"
          >
            <span className="text-[16px] leading-none">+</span>
            Novo Lead
          </button>
        </div>
      </div>

      {/* KPI Bar */}
      <div className="grid grid-cols-5 gap-4 mb-6">
        <div className="card p-4">
          <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Total de Leads</p>
          <p className="text-[28px] font-bold text-[#1f1f1f] mt-1">{kpis.total}</p>
        </div>
        <div className="card p-4">
          <div className="flex justify-between items-start">
            <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Quentes</p>
            <span className="w-2.5 h-2.5 rounded-full bg-[#f87171]" />
          </div>
          <p className="text-[28px] font-bold text-[#f87171] mt-1">{kpis.quentes}</p>
          <p className="text-[11px] text-[#9ca3af]">Ultima msg &lt; 48h</p>
        </div>
        <div className="card p-4">
          <div className="flex justify-between items-start">
            <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Mornos</p>
            <span className="w-2.5 h-2.5 rounded-full bg-[#e8d44d]" />
          </div>
          <p className="text-[28px] font-bold text-[#e8d44d] mt-1">{kpis.mornos}</p>
          <p className="text-[11px] text-[#9ca3af]">Ultima msg 48h-7d</p>
        </div>
        <div className="card p-4">
          <div className="flex justify-between items-start">
            <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Frios</p>
            <span className="w-2.5 h-2.5 rounded-full bg-[#60a5fa]" />
          </div>
          <p className="text-[28px] font-bold text-[#60a5fa] mt-1">{kpis.frios}</p>
          <p className="text-[11px] text-[#9ca3af]">Ultima msg &gt; 7d</p>
        </div>
        <div className="card p-4">
          <p className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Valor Total Pipeline</p>
          <p className="text-[28px] font-bold text-[#4ade80] mt-1">{fmt(kpis.totalValue)}</p>
        </div>
      </div>

      {/* Filters */}
      <LeadsFilterBar
        filters={filters}
        onChange={setFilters}
        tags={tags}
        totalCount={leads.length}
        filteredCount={filtered.length}
      />

      {/* Cards Grid */}
      {paginated.length > 0 ? (
        <div className="grid grid-cols-3 gap-4">
          {paginated.map((lead) => (
            <LeadGridCard
              key={lead.id}
              lead={lead}
              tags={getLeadTags(lead.id)}
              onClick={setSelectedLead}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-12">
          <p className="text-[14px] text-[#9ca3af]">Nenhum lead encontrado.</p>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center items-center gap-2 mt-6">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 rounded-md border border-[#e5e5dc] bg-white text-[13px] text-[#9ca3af] disabled:opacity-40"
          >
            &larr;
          </button>
          {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
            let pageNum: number;
            if (totalPages <= 7) {
              pageNum = i + 1;
            } else if (page <= 4) {
              pageNum = i + 1;
            } else if (page >= totalPages - 3) {
              pageNum = totalPages - 6 + i;
            } else {
              pageNum = page - 3 + i;
            }
            return (
              <button
                key={pageNum}
                onClick={() => setPage(pageNum)}
                className={`px-3 py-1.5 rounded-md text-[13px] ${
                  page === pageNum
                    ? "bg-[#1f1f1f] text-white"
                    : "border border-[#e5e5dc] bg-white text-[#5f6368] hover:bg-[#f6f7ed]"
                }`}
              >
                {pageNum}
              </button>
            );
          })}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1.5 rounded-md border border-[#e5e5dc] bg-white text-[13px] text-[#9ca3af] disabled:opacity-40"
          >
            &rarr;
          </button>
        </div>
      )}

      {/* Modals */}
      {selectedLead && (
        <LeadDetailModal
          lead={selectedLead}
          tags={tags}
          leadTagIds={leadTagsMap[selectedLead.id] || []}
          onClose={() => setSelectedLead(null)}
          onSave={handleSaveLead}
          onTagsChange={handleTagsChange}
        />
      )}
      {showCreate && (
        <LeadCreateModal
          onClose={() => setShowCreate(false)}
          onCreate={handleCreateLead}
        />
      )}
      {showImport && (
        <LeadImportModal
          onClose={() => setShowImport(false)}
          onImportDone={() => {}}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify the app compiles**

```bash
cd crm && npm run build
```

Fix any TypeScript errors if present.

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/\(authenticated\)/leads/page.tsx
git commit -m "feat: create /leads page with KPIs, filters, card grid, and pagination"
```

---

### Task 12: Integration Verification

- [ ] **Step 1: Run the dev server and verify**

```bash
cd crm && npm run dev
```

Open `http://localhost:3000/leads` and verify:
1. KPI bar shows correct counts
2. Filters work (search, temperature, stage, etc.)
3. Cards render with temperature borders
4. Clicking a card opens detail modal
5. Editing fields and saving works
6. Tags tab works (add/remove tags)
7. Notes tab works (add note)
8. "Novo Lead" modal creates a lead
9. "Importar" modal accepts CSV
10. "Exportar" downloads a CSV
11. Sidebar shows "Leads" link

- [ ] **Step 2: Fix any issues found**

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "fix: address leads page integration issues"
```

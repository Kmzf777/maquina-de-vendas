# CRM Kommo Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the ValerIA CRM to match key Kommo features: enriched lead model with B2B fields and sale value, rich kanban cards, comprehensive dashboard, enhanced conversations, and a new statistics page.

**Architecture:** Incremental page-by-page evolution. SQL migration adds new columns (all nullable/defaulted so existing data is safe). Frontend components are enhanced in-place. New `/estatisticas` page added. All data from Supabase with existing realtime hooks.

**Tech Stack:** Next.js 16, React 19, Supabase, Recharts, TailwindCSS 4, @dnd-kit/core

**Spec:** `docs/superpowers/specs/2026-03-27-crm-kommo-migration-design.md`

---

## File Structure

### New Files
- `backend-evolution/migrations/002_lead_enrichment.sql` — SQL migration for new lead fields
- `crm/src/components/kanban-metrics-bar.tsx` — Top metrics bar for kanban pages
- `crm/src/components/quick-add-lead.tsx` — Inline quick-add form for kanban columns
- `crm/src/components/kanban-filters.tsx` — Filter bar (search + active toggle)
- `crm/src/components/dashboard/lead-sources-chart.tsx` — Donut chart for lead sources
- `crm/src/components/dashboard/funnel-movement.tsx` — Funnel movement bar (Kommo style)
- `crm/src/components/conversas/audio-player.tsx` — Inline audio player for chat bubbles
- `crm/src/components/conversas/action-buttons.tsx` — Chat action buttons (Fechar, Em espera)
- `crm/src/components/conversas/editable-field.tsx` — Inline editable field component
- `crm/src/app/(authenticated)/estatisticas/page.tsx` — Statistics page
- `crm/src/components/estatisticas/vendas-analysis.tsx` — Sales analysis by funnel
- `crm/src/components/estatisticas/tempo-report.tsx` — Time report
- `crm/src/components/estatisticas/vendedor-report.tsx` — Seller performance report
- `crm/src/components/estatisticas/period-filter.tsx` — Reusable period filter

### Modified Files
- `crm/src/lib/types.ts` — Add new Lead fields
- `crm/src/lib/constants.ts` — Add LEAD_CHANNELS constant
- `crm/src/components/lead-card.tsx` — Enrich with value, days, tags, preview
- `crm/src/components/kanban-column.tsx` — Add quick-add slot, value summary
- `crm/src/app/(authenticated)/qualificacao/page.tsx` — Add metrics bar, filters
- `crm/src/app/(authenticated)/vendas/page.tsx` — Add metrics bar, filters
- `crm/src/app/(authenticated)/dashboard/page.tsx` — Overhaul with new KPIs, charts
- `crm/src/components/kpi-card.tsx` — Add subtitle prop for R$ values
- `crm/src/components/funnel-chart.tsx` — Add R$ values per bar
- `crm/src/components/conversas/contact-detail.tsx` — B2B fields, inline edit, stats
- `crm/src/components/conversas/chat-view.tsx` — Audio player, action buttons
- `crm/src/components/sidebar.tsx` — Add Estatisticas nav item
- `crm/src/hooks/use-realtime-leads.ts` — Ensure new fields are fetched

---

## Task 1: SQL Migration + TypeScript Types

**Files:**
- Create: `backend-evolution/migrations/002_lead_enrichment.sql`
- Modify: `crm/src/lib/types.ts`
- Modify: `crm/src/lib/constants.ts`

- [ ] **Step 1: Create SQL migration**

Create `backend-evolution/migrations/002_lead_enrichment.sql`:

```sql
-- 002_lead_enrichment.sql
-- Run this in Supabase SQL Editor

-- B2B fields
ALTER TABLE leads ADD COLUMN IF NOT EXISTS cnpj text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS razao_social text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS nome_fantasia text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS endereco text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS telefone_comercial text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS inscricao_estadual text;

-- Sale value
ALTER TABLE leads ADD COLUMN IF NOT EXISTS sale_value numeric DEFAULT 0;

-- Metric fields
ALTER TABLE leads ADD COLUMN IF NOT EXISTS entered_stage_at timestamptz DEFAULT now();
ALTER TABLE leads ADD COLUMN IF NOT EXISTS first_response_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS on_hold boolean DEFAULT false;

-- Index for stats queries
CREATE INDEX IF NOT EXISTS idx_leads_seller_stage ON leads(seller_stage);
CREATE INDEX IF NOT EXISTS idx_leads_entered_stage_at ON leads(entered_stage_at);

-- Trigger to auto-update entered_stage_at when stage changes
CREATE OR REPLACE FUNCTION update_entered_stage_at()
RETURNS trigger AS $$
BEGIN
    IF OLD.stage IS DISTINCT FROM NEW.stage OR OLD.seller_stage IS DISTINCT FROM NEW.seller_stage THEN
        NEW.entered_stage_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_entered_stage_at ON leads;
CREATE TRIGGER trg_update_entered_stage_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_entered_stage_at();
```

- [ ] **Step 2: Update TypeScript Lead interface**

In `crm/src/lib/types.ts`, replace the existing `Lead` interface with:

```typescript
export interface Lead {
  id: string;
  phone: string;
  name: string | null;
  company: string | null;
  stage: string;
  status: string;
  campaign_id: string | null;
  last_msg_at: string | null;
  created_at: string;
  seller_stage: string;
  assigned_to: string | null;
  human_control: boolean;
  channel: string;
  // B2B fields
  cnpj: string | null;
  razao_social: string | null;
  nome_fantasia: string | null;
  endereco: string | null;
  telefone_comercial: string | null;
  email: string | null;
  instagram: string | null;
  inscricao_estadual: string | null;
  // Sale
  sale_value: number;
  // Metrics
  entered_stage_at: string | null;
  first_response_at: string | null;
  on_hold: boolean;
}
```

- [ ] **Step 3: Add LEAD_CHANNELS constant**

In `crm/src/lib/constants.ts`, add at the end:

```typescript
export const LEAD_CHANNELS = [
  { key: "evolution", label: "WhatsApp", color: "#5aad65" },
  { key: "campaign", label: "Campanha", color: "#5b8aad" },
  { key: "manual", label: "Manual", color: "#ad9c4a" },
] as const;
```

- [ ] **Step 4: Commit**

```bash
git add backend-evolution/migrations/002_lead_enrichment.sql crm/src/lib/types.ts crm/src/lib/constants.ts
git commit -m "feat: add lead enrichment migration and updated types (B2B, sale_value, metrics)"
```

---

## Task 2: Enrich LeadCard Component

**Files:**
- Modify: `crm/src/components/lead-card.tsx`

- [ ] **Step 1: Rewrite LeadCard with enriched data**

Replace the entire content of `crm/src/components/lead-card.tsx` with:

```tsx
import type { Lead, Tag } from "@/lib/types";

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "agora";
  if (mins < 60) return `${mins}min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

function daysInStage(enteredAt: string | null): number | null {
  if (!enteredAt) return null;
  const diff = Date.now() - new Date(enteredAt).getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function formatCurrency(value: number): string {
  if (value === 0) return "";
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

interface LeadCardProps {
  lead: Lead;
  onClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  unreadCount?: number;
  tags?: Tag[];
  lastMessage?: string | null;
}

export function LeadCard({ lead, onClick, showAgentStage, unreadCount, tags, lastMessage }: LeadCardProps) {
  const days = daysInStage(lead.entered_stage_at);
  const isStale = days !== null && days > 30;
  const currencyStr = formatCurrency(lead.sale_value);

  return (
    <button
      onClick={() => onClick(lead)}
      className="card card-hover w-full text-left rounded-xl border border-[#e5e5dc] bg-white p-3.5 transition-all duration-200 hover:-translate-y-[1px] hover:shadow-md"
    >
      {/* Row 1: Name + unread badge */}
      <div className="flex items-center justify-between mb-1">
        <span className="text-[13px] font-semibold text-[#1f1f1f] truncate">
          {lead.name || lead.phone}
        </span>
        {unreadCount && unreadCount > 0 ? (
          <span className="bg-[#e8d44d] text-[#1f1f1f] text-[10px] font-semibold rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
            {unreadCount}
          </span>
        ) : null}
      </div>

      {/* Row 2: Company / nome fantasia */}
      {(lead.nome_fantasia || lead.company) && (
        <p className="text-[11px] text-[#5f6368] truncate mb-1.5">
          {lead.nome_fantasia || lead.company}
        </p>
      )}

      {/* Row 3: Value badge + days in stage */}
      <div className="flex items-center gap-2 mb-2">
        {currencyStr && (
          <span className="text-[11px] font-medium text-[#2d6a3f] bg-[#d8f0dc] px-2 py-0.5 rounded-full">
            {currencyStr}
          </span>
        )}
        {days !== null && (
          <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${
            isStale
              ? "text-[#a33] bg-[#f0d8d8]"
              : "text-[#5f6368] bg-[#f4f4f0]"
          }`}>
            {days}d
          </span>
        )}
        {showAgentStage && (
          <span className="text-[11px] text-[#5f6368] bg-[#f4f4f0] px-2 py-0.5 rounded-full">
            {lead.stage}
          </span>
        )}
      </div>

      {/* Row 4: Tags */}
      {tags && tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {tags.slice(0, 3).map((tag) => (
            <span
              key={tag.id}
              className="text-[10px] font-medium text-white px-1.5 py-0.5 rounded-full"
              style={{ backgroundColor: tag.color }}
            >
              {tag.name}
            </span>
          ))}
          {tags.length > 3 && (
            <span className="text-[10px] text-[#9ca3af]">+{tags.length - 3}</span>
          )}
        </div>
      )}

      {/* Row 5: Last message preview */}
      {lastMessage && (
        <p className="text-[11px] text-[#9ca3af] truncate mb-2 italic">
          {lastMessage}
        </p>
      )}

      {/* Row 6: Time info */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-[#9ca3af]">
          {lead.phone}
        </span>
        <span className="text-[10px] text-[#9ca3af]">
          {timeAgo(lead.last_msg_at)}
        </span>
      </div>
    </button>
  );
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd crm && npx next build --no-lint 2>&1 | head -30`

Note: Some pages may have TypeScript errors because they pass different props to LeadCard — we'll fix those in the next tasks. Just verify the component file itself has no syntax errors.

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/lead-card.tsx
git commit -m "feat: enrich LeadCard with sale value, days in stage, tags, and message preview"
```

---

## Task 3: Kanban Support Components (Metrics Bar, Quick Add, Filters)

**Files:**
- Create: `crm/src/components/kanban-metrics-bar.tsx`
- Create: `crm/src/components/quick-add-lead.tsx`
- Create: `crm/src/components/kanban-filters.tsx`

- [ ] **Step 1: Create KanbanMetricsBar**

Create `crm/src/components/kanban-metrics-bar.tsx`:

```tsx
import type { Lead } from "@/lib/types";

interface KanbanMetricsBarProps {
  leads: Lead[];
}

export function KanbanMetricsBar({ leads }: KanbanMetricsBarProps) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const totalValue = leads.reduce((sum, l) => sum + (l.sale_value || 0), 0);
  const leadsToday = leads.filter((l) => new Date(l.created_at) >= today).length;
  const leadsYesterday = leads.filter((l) => {
    const d = new Date(l.created_at);
    return d >= yesterday && d < today;
  }).length;
  const potentialValue = leads
    .filter((l) => l.seller_stage !== "perdido" && l.seller_stage !== "fechado")
    .reduce((sum, l) => sum + (l.sale_value || 0), 0);

  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  return (
    <div className="flex items-center gap-6 px-4 py-3 mb-4 rounded-xl bg-white border border-[#e5e5dc]">
      <div className="flex items-center gap-2">
        <span className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Total</span>
        <span className="text-[14px] font-bold text-[#1f1f1f]">{leads.length} leads</span>
        <span className="text-[13px] font-medium text-[#5f6368]">{fmt(totalValue)}</span>
      </div>
      <div className="w-px h-5 bg-[#e5e5dc]" />
      <div className="flex items-center gap-2">
        <span className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Novo hoje / ontem</span>
        <span className="text-[14px] font-bold text-[#1f1f1f]">{leadsToday} / {leadsYesterday}</span>
      </div>
      <div className="w-px h-5 bg-[#e5e5dc]" />
      <div className="flex items-center gap-2">
        <span className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Vendas em potencial</span>
        <span className="text-[14px] font-bold text-[#2d6a3f]">{fmt(potentialValue)}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create QuickAddLead**

Create `crm/src/components/quick-add-lead.tsx`:

```tsx
"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

interface QuickAddLeadProps {
  stage: string;
  sellerStage?: string;
  humanControl?: boolean;
}

export function QuickAddLead({ stage, sellerStage = "novo", humanControl = false }: QuickAddLeadProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [company, setCompany] = useState("");
  const [saving, setSaving] = useState(false);
  const supabase = createClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!phone.trim()) return;
    setSaving(true);

    await supabase.from("leads").insert({
      name: name.trim() || null,
      phone: phone.trim(),
      company: company.trim() || null,
      stage,
      seller_stage: sellerStage,
      human_control: humanControl,
      status: "active",
      channel: "manual",
      sale_value: 0,
    });

    setName("");
    setPhone("");
    setCompany("");
    setOpen(false);
    setSaving(false);
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full text-center py-2 text-[12px] text-[#9ca3af] hover:text-[#5f6368] hover:bg-[#f6f7ed] rounded-lg transition-colors"
      >
        + Adicao rapida
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-[#e5e5dc] rounded-xl p-3 space-y-2">
      <input
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        placeholder="Telefone *"
        className="input-field w-full text-[12px] rounded-lg px-3 py-1.5"
        required
      />
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Nome"
        className="input-field w-full text-[12px] rounded-lg px-3 py-1.5"
      />
      <input
        value={company}
        onChange={(e) => setCompany(e.target.value)}
        placeholder="Empresa"
        className="input-field w-full text-[12px] rounded-lg px-3 py-1.5"
      />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="btn-primary flex-1 py-1.5 rounded-lg text-[12px] font-medium disabled:opacity-50"
        >
          {saving ? "..." : "Criar"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="btn-secondary flex-1 py-1.5 rounded-lg text-[12px] font-medium"
        >
          Cancelar
        </button>
      </div>
    </form>
  );
}
```

- [ ] **Step 3: Create KanbanFilters**

Create `crm/src/components/kanban-filters.tsx`:

```tsx
"use client";

interface KanbanFiltersProps {
  search: string;
  onSearchChange: (val: string) => void;
  showActive: boolean;
  onToggleActive: () => void;
}

export function KanbanFilters({ search, onSearchChange, showActive, onToggleActive }: KanbanFiltersProps) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <input
        type="text"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
        placeholder="Buscar por nome, empresa ou telefone..."
        className="input-field text-[13px] rounded-xl px-4 py-2 w-80"
      />
      <button
        onClick={onToggleActive}
        className={`px-3 py-2 rounded-xl text-[12px] font-medium transition-colors ${
          showActive
            ? "bg-[#1f1f1f] text-white"
            : "bg-[#f6f7ed] text-[#5f6368] border border-[#e5e5dc] hover:bg-[#e5e5dc]"
        }`}
      >
        Leads ativos
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add crm/src/components/kanban-metrics-bar.tsx crm/src/components/quick-add-lead.tsx crm/src/components/kanban-filters.tsx
git commit -m "feat: add kanban support components (metrics bar, quick add, filters)"
```

---

## Task 4: Update Qualificacao Page with Enriched Kanban

**Files:**
- Modify: `crm/src/app/(authenticated)/qualificacao/page.tsx`
- Modify: `crm/src/components/kanban-column.tsx`

- [ ] **Step 1: Update KanbanColumn to accept quick-add and value summary**

Replace entire content of `crm/src/components/kanban-column.tsx`:

```tsx
import type { Lead } from "@/lib/types";
import { LeadCard } from "./lead-card";
import type { Tag } from "@/lib/types";

interface KanbanColumnProps {
  title: string;
  leads: Lead[];
  colorClass: string;
  onLeadClick: (lead: Lead) => void;
  showAgentStage?: boolean;
  id?: string;
  tags?: Tag[];
  leadTagsMap?: Record<string, Tag[]>;
  lastMessagesMap?: Record<string, string>;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}

export function KanbanColumn({
  title,
  leads,
  colorClass,
  onLeadClick,
  showAgentStage,
  tags,
  leadTagsMap,
  lastMessagesMap,
  children,
  footer,
}: KanbanColumnProps) {
  const totalValue = leads.reduce((sum, l) => sum + (l.sale_value || 0), 0);
  const valueStr = totalValue > 0
    ? `R$ ${totalValue.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`
    : null;

  return (
    <div className="flex-shrink-0 w-[280px]">
      <div className="px-3 py-3 mb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`w-2.5 h-2.5 rounded-full ${colorClass}`} />
            <h3 className="text-[14px] font-semibold text-[#1f1f1f]">
              {title}
            </h3>
          </div>
          <span className="text-[12px] font-medium text-[#5f6368] border border-[#e5e5dc] rounded-full px-2.5 py-0.5">
            {leads.length}
          </span>
        </div>
        {valueStr && (
          <p className="text-[11px] text-[#2d6a3f] font-medium mt-1 pl-4">
            {valueStr}
          </p>
        )}
      </div>
      <div className="rounded-xl p-2 min-h-[calc(100vh-260px)] space-y-2.5 overflow-y-auto">
        {children}
        {!children &&
          leads.map((lead) => (
            <LeadCard
              key={lead.id}
              lead={lead}
              onClick={onLeadClick}
              showAgentStage={showAgentStage}
              tags={leadTagsMap?.[lead.id]}
              lastMessage={lastMessagesMap?.[lead.id]}
            />
          ))}
        {footer}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update Qualificacao page**

Replace entire content of `crm/src/app/(authenticated)/qualificacao/page.tsx`:

```tsx
"use client";

import { useState, useEffect } from "react";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { AGENT_STAGES } from "@/lib/constants";
import { KanbanColumn } from "@/components/kanban-column";
import { KanbanMetricsBar } from "@/components/kanban-metrics-bar";
import { KanbanFilters } from "@/components/kanban-filters";
import { QuickAddLead } from "@/components/quick-add-lead";
import { ChatPanel } from "@/components/chat-panel";
import { createClient } from "@/lib/supabase/client";
import type { Lead, Tag } from "@/lib/types";

export default function QualificacaoPage() {
  const { leads, loading } = useRealtimeLeads();
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [search, setSearch] = useState("");
  const [showActive, setShowActive] = useState(true);
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, Tag[]>>({});
  const supabase = createClient();

  useEffect(() => {
    async function loadTags() {
      const { data: tagsData } = await supabase.from("tags").select("*");
      if (!tagsData) return;
      setTags(tagsData);

      const { data: ltData } = await supabase.from("lead_tags").select("lead_id, tag_id");
      if (!ltData) return;

      const map: Record<string, Tag[]> = {};
      ltData.forEach((row: { lead_id: string; tag_id: string }) => {
        const tag = tagsData.find((t: Tag) => t.id === row.tag_id);
        if (tag) {
          if (!map[row.lead_id]) map[row.lead_id] = [];
          map[row.lead_id].push(tag);
        }
      });
      setLeadTagsMap(map);
    }
    loadTags();
  }, []);

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

  const filteredLeads = leads.filter((l) => {
    if (showActive && (l.seller_stage === "perdido" || l.seller_stage === "fechado")) return false;
    if (search) {
      const q = search.toLowerCase();
      const match =
        (l.name || "").toLowerCase().includes(q) ||
        (l.company || "").toLowerCase().includes(q) ||
        (l.nome_fantasia || "").toLowerCase().includes(q) ||
        l.phone.includes(q);
      if (!match) return false;
    }
    return true;
  });

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-[28px] font-bold text-[#1f1f1f]">Qualificacao</h1>
        <p className="text-[14px] text-[#5f6368] mt-1">
          Funil de qualificacao do agente IA
        </p>
      </div>

      <KanbanMetricsBar leads={filteredLeads} />
      <KanbanFilters
        search={search}
        onSearchChange={setSearch}
        showActive={showActive}
        onToggleActive={() => setShowActive(!showActive)}
      />

      <div className="flex gap-5 overflow-x-auto pb-4">
        {AGENT_STAGES.map((stage) => {
          const stageLeads = filteredLeads.filter((l) => l.stage === stage.key);
          return (
            <KanbanColumn
              key={stage.key}
              title={stage.label}
              leads={stageLeads}
              colorClass={stage.color}
              onLeadClick={setSelectedLead}
              leadTagsMap={leadTagsMap}
              footer={<QuickAddLead stage={stage.key} />}
            />
          );
        })}
      </div>

      {selectedLead && (
        <ChatPanel
          lead={selectedLead}
          onClose={() => setSelectedLead(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify it compiles**

Run: `cd crm && npx next build --no-lint 2>&1 | tail -20`

- [ ] **Step 4: Commit**

```bash
git add crm/src/components/kanban-column.tsx crm/src/app/\(authenticated\)/qualificacao/page.tsx
git commit -m "feat: enrich Qualificacao kanban with metrics bar, filters, quick add, and rich cards"
```

---

## Task 5: Update Vendas Page with Enriched Kanban

**Files:**
- Modify: `crm/src/app/(authenticated)/vendas/page.tsx`

- [ ] **Step 1: Rewrite Vendas page with enriched kanban**

Replace entire content of `crm/src/app/(authenticated)/vendas/page.tsx`:

```tsx
"use client";

import { useState, useEffect } from "react";
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
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { SELLER_STAGES } from "@/lib/constants";
import { LeadCard } from "@/components/lead-card";
import { KanbanMetricsBar } from "@/components/kanban-metrics-bar";
import { KanbanFilters } from "@/components/kanban-filters";
import { QuickAddLead } from "@/components/quick-add-lead";
import { ChatActive } from "@/components/chat-active";
import { LeadDetailSidebar } from "@/components/lead-detail-sidebar";
import { createClient } from "@/lib/supabase/client";
import type { Lead, Tag } from "@/lib/types";

function DroppableColumn({
  id,
  title,
  colorClass,
  leads,
  onLeadClick,
  leadTagsMap,
}: {
  id: string;
  title: string;
  colorClass: string;
  leads: Lead[];
  onLeadClick: (lead: Lead) => void;
  leadTagsMap: Record<string, Tag[]>;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  const totalValue = leads.reduce((sum, l) => sum + (l.sale_value || 0), 0);
  const valueStr = totalValue > 0
    ? `R$ ${totalValue.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`
    : null;

  return (
    <div className="flex-shrink-0 w-[280px]">
      <div className="px-3 py-3 mb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`w-2.5 h-2.5 rounded-full ${colorClass}`} />
            <h3 className="text-[14px] font-semibold text-[#1f1f1f]">{title}</h3>
          </div>
          <span className="text-[12px] font-medium text-[#5f6368] border border-[#e5e5dc] rounded-full px-2.5 py-0.5">
            {leads.length}
          </span>
        </div>
        {valueStr && (
          <p className="text-[11px] text-[#2d6a3f] font-medium mt-1 pl-4">{valueStr}</p>
        )}
      </div>
      <div
        ref={setNodeRef}
        className={`rounded-xl p-2 min-h-[calc(100vh-260px)] space-y-2.5 overflow-y-auto transition-all duration-200 ${
          isOver
            ? "border-2 border-dashed border-[#c8cc8e] bg-[#c8cc8e]/5"
            : "border-2 border-transparent"
        }`}
      >
        {leads.map((lead) => (
          <DraggableLeadCard
            key={lead.id}
            lead={lead}
            onClick={onLeadClick}
            tags={leadTagsMap[lead.id]}
          />
        ))}
        <QuickAddLead stage="secretaria" sellerStage={id} humanControl />
      </div>
    </div>
  );
}

function DraggableLeadCard({
  lead,
  onClick,
  tags,
}: {
  lead: Lead;
  onClick: (lead: Lead) => void;
  tags?: Tag[];
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: lead.id,
    data: lead,
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={isDragging ? "opacity-30" : ""}
    >
      <LeadCard lead={lead} onClick={onClick} showAgentStage tags={tags} />
    </div>
  );
}

export default function VendasPage() {
  const { leads, loading } = useRealtimeLeads({ human_control: true });
  const [chatLead, setChatLead] = useState<Lead | null>(null);
  const [detailLead, setDetailLead] = useState<Lead | null>(null);
  const [activeDrag, setActiveDrag] = useState<Lead | null>(null);
  const [search, setSearch] = useState("");
  const [showActive, setShowActive] = useState(true);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, Tag[]>>({});
  const supabase = createClient();

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  useEffect(() => {
    async function loadTags() {
      const { data: tagsData } = await supabase.from("tags").select("*");
      if (!tagsData) return;

      const { data: ltData } = await supabase.from("lead_tags").select("lead_id, tag_id");
      if (!ltData) return;

      const map: Record<string, Tag[]> = {};
      ltData.forEach((row: { lead_id: string; tag_id: string }) => {
        const tag = tagsData.find((t: Tag) => t.id === row.tag_id);
        if (tag) {
          if (!map[row.lead_id]) map[row.lead_id] = [];
          map[row.lead_id].push(tag);
        }
      });
      setLeadTagsMap(map);
    }
    loadTags();
  }, []);

  function handleDragStart(event: DragStartEvent) {
    setActiveDrag(event.active.data.current as Lead);
  }

  async function handleDragEnd(event: DragEndEvent) {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;

    const lead = active.data.current as Lead;
    const newStage = over.id as string;

    if (lead.seller_stage === newStage) return;

    await supabase
      .from("leads")
      .update({ seller_stage: newStage })
      .eq("id", lead.id);
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

  const filteredLeads = leads.filter((l) => {
    if (showActive && (l.seller_stage === "perdido" || l.seller_stage === "fechado")) return false;
    if (search) {
      const q = search.toLowerCase();
      const match =
        (l.name || "").toLowerCase().includes(q) ||
        (l.company || "").toLowerCase().includes(q) ||
        (l.nome_fantasia || "").toLowerCase().includes(q) ||
        l.phone.includes(q);
      if (!match) return false;
    }
    return true;
  });

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-[28px] font-bold text-[#1f1f1f]">Vendas</h1>
        <p className="text-[14px] text-[#5f6368] mt-1">Pipeline de vendas</p>
      </div>

      <KanbanMetricsBar leads={filteredLeads} />
      <KanbanFilters
        search={search}
        onSearchChange={setSearch}
        showActive={showActive}
        onToggleActive={() => setShowActive(!showActive)}
      />

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex gap-5 overflow-x-auto pb-4">
          {SELLER_STAGES.map((stage) => {
            const stageLeads = filteredLeads.filter(
              (l) => l.seller_stage === stage.key
            );
            return (
              <DroppableColumn
                key={stage.key}
                id={stage.key}
                title={stage.label}
                colorClass={stage.color}
                leads={stageLeads}
                onLeadClick={setChatLead}
                leadTagsMap={leadTagsMap}
              />
            );
          })}
        </div>
        <DragOverlay>
          {activeDrag ? (
            <div className="w-[280px] opacity-90 rotate-[2deg] shadow-xl">
              <LeadCard lead={activeDrag} onClick={() => {}} showAgentStage />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

      {chatLead && !detailLead && (
        <ChatActive
          lead={chatLead}
          onClose={() => setChatLead(null)}
          onOpenDetails={() => setDetailLead(chatLead)}
        />
      )}

      {detailLead && (
        <LeadDetailSidebar
          lead={detailLead}
          onClose={() => setDetailLead(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd crm && npx next build --no-lint 2>&1 | tail -20`

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/\(authenticated\)/vendas/page.tsx
git commit -m "feat: enrich Vendas kanban with metrics bar, filters, quick add, and rich cards"
```

---

## Task 6: Dashboard Overhaul - KPI Cards + Lead Sources Chart

**Files:**
- Modify: `crm/src/components/kpi-card.tsx`
- Create: `crm/src/components/dashboard/lead-sources-chart.tsx`
- Modify: `crm/src/app/(authenticated)/dashboard/page.tsx` (partial — KPIs and sources)

- [ ] **Step 1: Add subtitle prop to KpiCard**

Replace entire content of `crm/src/components/kpi-card.tsx`:

```tsx
import type { ReactNode } from "react";

interface KpiCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  trend?: string;
}

export function KpiCard({ label, value, subtitle, icon, trend }: KpiCardProps) {
  return (
    <div className="card group relative p-5 overflow-hidden">
      <div className="flex items-start justify-between">
        <p
          className="text-[13px] font-medium"
          style={{ color: "var(--text-secondary)" }}
        >
          {label}
        </p>
        {icon && (
          <span
            className="text-[18px] opacity-60"
            style={{ color: "var(--text-secondary)" }}
          >
            {icon}
          </span>
        )}
      </div>
      <div className="flex items-end gap-2 mt-2">
        <p
          className="text-[32px] font-bold tracking-tight leading-none"
          style={{ color: "var(--text-primary)" }}
        >
          {value}
        </p>
        {trend && (
          <span
            className="text-[13px] font-medium mb-1"
            style={{ color: "#6b8e5a" }}
          >
            {trend}
          </span>
        )}
      </div>
      {subtitle && (
        <p className="text-[13px] font-medium mt-1" style={{ color: "var(--text-secondary)" }}>
          {subtitle}
        </p>
      )}
      <div
        className="absolute bottom-0 left-4 right-4 h-[4px] rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300"
        style={{ backgroundColor: "var(--accent-olive)" }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Create LeadSourcesChart (SVG donut)**

Create `crm/src/components/dashboard/lead-sources-chart.tsx`:

```tsx
"use client";

import { LEAD_CHANNELS } from "@/lib/constants";
import type { Lead } from "@/lib/types";

interface LeadSourcesChartProps {
  leads: Lead[];
}

export function LeadSourcesChart({ leads }: LeadSourcesChartProps) {
  const counts = LEAD_CHANNELS.map((ch) => ({
    ...ch,
    count: leads.filter((l) => l.channel === ch.key).length,
  }));

  // Add "Outros" for unmatched channels
  const knownKeys = new Set(LEAD_CHANNELS.map((c) => c.key));
  const othersCount = leads.filter((l) => !knownKeys.has(l.channel)).length;
  if (othersCount > 0) {
    counts.push({ key: "outros", label: "Outros", color: "#8a8a80", count: othersCount });
  }

  const total = counts.reduce((sum, c) => sum + c.count, 0);
  if (total === 0) {
    return (
      <div className="card p-5">
        <h3 className="text-[13px] font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
          Fontes de Lead
        </h3>
        <p className="text-[#9ca3af] text-sm text-center py-8">Sem dados</p>
      </div>
    );
  }

  // Build SVG donut segments
  const radius = 70;
  const cx = 90;
  const cy = 90;
  const strokeWidth = 28;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  const segments = counts
    .filter((c) => c.count > 0)
    .map((c) => {
      const pct = c.count / total;
      const dashLen = pct * circumference;
      const seg = {
        ...c,
        pct,
        dashLen,
        dashOffset: -offset,
      };
      offset += dashLen;
      return seg;
    });

  return (
    <div className="card p-5">
      <h3 className="text-[13px] font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
        Fontes de Lead
      </h3>
      <div className="flex items-center gap-6">
        <svg width={180} height={180} viewBox="0 0 180 180">
          {segments.map((seg) => (
            <circle
              key={seg.key}
              cx={cx}
              cy={cy}
              r={radius}
              fill="none"
              stroke={seg.color}
              strokeWidth={strokeWidth}
              strokeDasharray={`${seg.dashLen} ${circumference - seg.dashLen}`}
              strokeDashoffset={seg.dashOffset}
              transform={`rotate(-90 ${cx} ${cy})`}
            />
          ))}
          <text x={cx} y={cy - 6} textAnchor="middle" className="text-[24px] font-bold" fill="#1f1f1f">
            {total}
          </text>
          <text x={cx} y={cy + 14} textAnchor="middle" className="text-[11px]" fill="#9ca3af">
            leads
          </text>
        </svg>
        <div className="space-y-2">
          {segments.map((seg) => (
            <div key={seg.key} className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: seg.color }} />
              <span className="text-[13px] text-[#1f1f1f]">{seg.label}</span>
              <span className="text-[13px] font-bold text-[#1f1f1f]">{seg.count}</span>
              <span className="text-[11px] text-[#9ca3af]">{Math.round(seg.pct * 100)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/kpi-card.tsx crm/src/components/dashboard/lead-sources-chart.tsx
git commit -m "feat: add KpiCard subtitle and LeadSourcesChart donut component"
```

---

## Task 7: Dashboard Overhaul - Funnel Movement + Full Page Rewrite

**Files:**
- Create: `crm/src/components/dashboard/funnel-movement.tsx`
- Modify: `crm/src/components/funnel-chart.tsx`
- Modify: `crm/src/app/(authenticated)/dashboard/page.tsx`

- [ ] **Step 1: Create FunnelMovement component**

Create `crm/src/components/dashboard/funnel-movement.tsx`:

```tsx
"use client";

import { useState } from "react";
import { SELLER_STAGES } from "@/lib/constants";
import type { Lead } from "@/lib/types";

interface FunnelMovementProps {
  leads: Lead[];
}

type Period = "today" | "7d" | "30d";

function getPeriodStart(period: Period): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  if (period === "7d") d.setDate(d.getDate() - 7);
  if (period === "30d") d.setDate(d.getDate() - 30);
  return d;
}

export function FunnelMovement({ leads }: FunnelMovementProps) {
  const [period, setPeriod] = useState<Period>("30d");
  const periodStart = getPeriodStart(period);

  // "Entered" = entered_stage_at is within period (approximation: leads whose entered_stage_at >= periodStart)
  // "Inside" = current stage count
  // "Lost" = seller_stage === "perdido" within period

  const stages = SELLER_STAGES.filter((s) => s.key !== "perdido");

  const data = stages.map((stage) => {
    const inStage = leads.filter((l) => l.seller_stage === stage.key);
    const entered = inStage.filter(
      (l) => l.entered_stage_at && new Date(l.entered_stage_at) >= periodStart
    );
    const value = inStage.reduce((sum, l) => sum + (l.sale_value || 0), 0);

    return {
      ...stage,
      count: inStage.length,
      entered: entered.length,
      value,
    };
  });

  const lost = leads.filter(
    (l) =>
      l.seller_stage === "perdido" &&
      l.entered_stage_at &&
      new Date(l.entered_stage_at) >= periodStart
  );
  const lostValue = lost.reduce((sum, l) => sum + (l.sale_value || 0), 0);

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
          Movimentacao do Funil
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
              <td className="py-2 px-3 text-[#9ca3af] text-[11px] uppercase">Dentro da etapa</td>
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
            <tr className="border-t border-[#e5e5dc]">
              <td className="py-2 px-3 text-[#9ca3af] text-[11px] uppercase">Perda</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-2 px-3 text-[#9ca3af] text-[12px]">
                  0 leads, R$ 0
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      {/* Lost summary */}
      <div className="mt-3 pt-3 border-t border-[#e5e5dc] flex items-center gap-4">
        <span className="text-[12px] text-[#9ca3af] uppercase tracking-wider">Total perdidos no periodo:</span>
        <span className="text-[14px] font-bold text-[#a33]">{lost.length} leads</span>
        <span className="text-[12px] text-[#5f6368]">{fmt(lostValue)}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update FunnelChart to show R$ values**

Replace entire content of `crm/src/components/funnel-chart.tsx`:

```tsx
"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface FunnelChartProps {
  data: { name: string; count: number; value?: number }[];
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number; payload?: { value?: number } }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const val = payload[0].payload?.value;
  const valStr = val ? `R$ ${val.toLocaleString("pt-BR")}` : null;
  return (
    <div className="rounded-lg px-3 py-2 shadow-lg text-[13px]" style={{ backgroundColor: "#1f1f1f", color: "#fff" }}>
      <p className="font-medium">{label}</p>
      <p className="opacity-80">{payload[0].value} leads</p>
      {valStr && <p className="opacity-60">{valStr}</p>}
    </div>
  );
}

export function FunnelChart({ data }: FunnelChartProps) {
  return (
    <div className="card p-5">
      <h3
        className="text-[13px] font-semibold uppercase tracking-wider mb-5 flex items-center gap-2"
        style={{ color: "var(--text-secondary)" }}
      >
        Funil de Qualificacao
        <span className="text-[14px] opacity-50">&rarr;</span>
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} layout="vertical" margin={{ left: 80 }}>
          <XAxis
            type="number"
            tick={{ fontSize: 12, fill: "#9ca3af" }}
            axisLine={{ stroke: "#e5e5dc" }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={80}
            tick={{ fontSize: 12, fill: "#5f6368" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(200,204,142,0.1)" }} />
          <Bar dataKey="count" fill="#1f1f1f" radius={[0, 6, 6, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 3: Rewrite Dashboard page**

Replace entire content of `crm/src/app/(authenticated)/dashboard/page.tsx`:

```tsx
"use client";

import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
import { AGENT_STAGES } from "@/lib/constants";
import { KpiCard } from "@/components/kpi-card";
import { FunnelChart } from "@/components/funnel-chart";
import { CampaignMetricsTable } from "@/components/campaign-table";
import { LeadSourcesChart } from "@/components/dashboard/lead-sources-chart";
import { FunnelMovement } from "@/components/dashboard/funnel-movement";

const TrendUpIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M3 14l4-4 3 3 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M13 6h4v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const UsersIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="7.5" cy="7" r="2.5" stroke="currentColor" strokeWidth="1.8" />
    <path d="M2.5 16c0-2.5 2-4.5 5-4.5s5 2 5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    <circle cx="14" cy="7.5" r="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M14 11.5c2 0 3.5 1.2 3.5 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);
const CheckIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M5 10l3.5 3.5L15 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const XIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);
const ChatIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M4 14l-1 4 4-2c1.2.5 2.5.8 3.8.8 4.4 0 8-3 8-6.8S15.2 3 10.8 3 2.8 6 2.8 9.8c0 1.5.5 2.9 1.2 4.2z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const ClockIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.8" />
    <path d="M10 6.5V10l2.5 2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export default function DashboardPage() {
  const { leads, loading: leadsLoading } = useRealtimeLeads();
  const { campaigns, loading: campaignsLoading } = useRealtimeCampaigns();

  if (leadsLoading || campaignsLoading) {
    return (
      <div className="space-y-6">
        <div>
          <div className="h-8 w-48 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
          <div className="h-4 w-72 rounded-lg animate-pulse mt-2" style={{ backgroundColor: "#e5e5dc" }} />
        </div>
        <div className="grid grid-cols-3 gap-5">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card p-5 h-28 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
      </div>
    );
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const leadsToday = leads.filter((l) => new Date(l.created_at) >= today).length;

  const activeLeads = leads.filter((l) => l.seller_stage !== "perdido" && l.seller_stage !== "fechado");
  const activeValue = activeLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);

  const wonLeads = leads.filter((l) => l.seller_stage === "fechado");
  const wonValue = wonLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);

  const lostLeads = leads.filter((l) => l.seller_stage === "perdido");
  const lostValue = lostLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);

  // Chats sem resposta: leads where last_msg_at > 1 hour ago (approximation without message role)
  const oneHourAgo = Date.now() - 60 * 60 * 1000;
  const unanswered = leads.filter(
    (l) => l.last_msg_at && new Date(l.last_msg_at).getTime() < oneHourAgo && !l.human_control
  ).length;

  // Average first response time
  const withResponse = leads.filter((l) => l.first_response_at);
  const avgResponseMs = withResponse.length > 0
    ? withResponse.reduce((sum, l) => {
        return sum + (new Date(l.first_response_at!).getTime() - new Date(l.created_at).getTime());
      }, 0) / withResponse.length
    : 0;
  const avgResponseMin = Math.round(avgResponseMs / 60000);
  const responseStr = avgResponseMin > 0 ? `${avgResponseMin}m` : "\u2014";

  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  const funnelData = AGENT_STAGES.map((stage) => {
    const stageLeads = leads.filter((l) => l.stage === stage.key);
    return {
      name: stage.label,
      count: stageLeads.length,
      value: stageLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0),
    };
  });
  const humanLeads = leads.filter((l) => l.human_control);
  funnelData.push({
    name: "Convertidos",
    count: humanLeads.length,
    value: humanLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0),
  });

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-[28px] font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
          Dashboard
        </h1>
        <p className="text-[14px] mt-1" style={{ color: "var(--text-muted)" }}>
          Visao geral do desempenho e metricas
        </p>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-3 gap-5 mb-8">
        <KpiCard label="Leads hoje" value={leadsToday} icon={TrendUpIcon} />
        <KpiCard label="Leads ativos" value={activeLeads.length} subtitle={fmt(activeValue)} icon={UsersIcon} />
        <KpiCard label="Leads ganhos" value={wonLeads.length} subtitle={fmt(wonValue)} icon={CheckIcon} />
        <KpiCard label="Leads perdidos" value={lostLeads.length} subtitle={fmt(lostValue)} icon={XIcon} />
        <KpiCard label="Chats sem resposta" value={unanswered} icon={ChatIcon} />
        <KpiCard label="Tempo de resposta" value={responseStr} icon={ClockIcon} />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-2 gap-5 mb-8">
        <FunnelChart data={funnelData} />
        <LeadSourcesChart leads={leads} />
      </div>

      {/* Funnel Movement */}
      <div className="mb-8">
        <FunnelMovement leads={leads} />
      </div>

      {/* Campaigns */}
      <CampaignMetricsTable campaigns={campaigns} />
    </div>
  );
}
```

- [ ] **Step 4: Verify it compiles**

Run: `cd crm && npx next build --no-lint 2>&1 | tail -20`

- [ ] **Step 5: Commit**

```bash
git add crm/src/components/funnel-chart.tsx crm/src/components/dashboard/funnel-movement.tsx crm/src/app/\(authenticated\)/dashboard/page.tsx
git commit -m "feat: overhaul dashboard with 6 KPIs, lead sources donut, and funnel movement"
```

---

## Task 8: Enriched Conversas - Editable B2B Fields + Contact Stats

**Files:**
- Create: `crm/src/components/conversas/editable-field.tsx`
- Modify: `crm/src/components/conversas/contact-detail.tsx`

- [ ] **Step 1: Create EditableField component**

Create `crm/src/components/conversas/editable-field.tsx`:

```tsx
"use client";

import { useState, useRef, useEffect } from "react";

interface EditableFieldProps {
  label: string;
  value: string | null;
  onSave: (value: string) => void;
  placeholder?: string;
  mask?: "currency";
}

export function EditableField({ label, value, onSave, placeholder, mask }: EditableFieldProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function handleSave() {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed !== (value || "")) {
      onSave(trimmed);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleSave();
    if (e.key === "Escape") {
      setDraft(value || "");
      setEditing(false);
    }
  }

  const displayValue = mask === "currency" && value
    ? `R$ ${Number(value).toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`
    : value;

  return (
    <div>
      <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-0.5">
        {label}
      </span>
      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={handleSave}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="input-field text-[14px] rounded-lg px-2 py-1 w-full"
        />
      ) : (
        <button
          onClick={() => { setDraft(value || ""); setEditing(true); }}
          className="text-[14px] text-[#1f1f1f] hover:bg-[#f6f7ed] px-2 py-0.5 rounded -ml-2 transition-colors w-full text-left min-h-[28px]"
        >
          {displayValue || <span className="text-[#c8cc8e] italic">{placeholder || "Clique para editar"}</span>}
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Rewrite ContactDetail with B2B fields and stats**

Replace entire content of `crm/src/components/conversas/contact-detail.tsx`:

```tsx
"use client";

import { useState } from "react";
import { SELLER_STAGES, AGENT_STAGES } from "@/lib/constants";
import { EditableField } from "./editable-field";
import { createClient } from "@/lib/supabase/client";
import type { Lead, Tag } from "@/lib/types";

interface ContactDetailProps {
  phone: string;
  pushName: string | null;
  lead: Lead | null;
  tags: Tag[];
  leadTags: Tag[];
  onTagToggle: (tagId: string, add: boolean) => void;
  onCreateLead: () => void;
  onSellerStageChange: (stage: string) => void;
}

export function ContactDetail({
  phone,
  pushName,
  lead,
  tags,
  leadTags,
  onTagToggle,
  onCreateLead,
  onSellerStageChange,
}: ContactDetailProps) {
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const displayName = lead?.name || pushName || phone;
  const supabase = createClient();

  const stageInfo = lead ? AGENT_STAGES.find((s) => s.key === lead.stage) : null;
  const leadTagIds = new Set(leadTags.map((t) => t.id));
  const availableTags = tags.filter((t) => !leadTagIds.has(t.id));

  async function updateLeadField(field: string, value: string) {
    if (!lead) return;
    const numericFields = ["sale_value"];
    const updateValue = numericFields.includes(field) ? Number(value) || 0 : value;
    await supabase.from("leads").update({ [field]: updateValue }).eq("id", lead.id);
  }

  // Contact stats
  const daysActive = lead
    ? Math.floor((Date.now() - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24))
    : 0;

  return (
    <div className="w-[320px] bg-white border-l border-[#e5e5dc] flex flex-col h-full overflow-y-auto">
      {/* Avatar + Name */}
      <div className="flex flex-col items-center pt-8 pb-4 px-4 border-b border-[#e5e5dc]">
        <div className="w-20 h-20 rounded-full bg-[#c8cc8e] flex items-center justify-center text-white text-2xl font-bold mb-3">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <h3 className="text-[18px] font-semibold text-[#1f1f1f]">{displayName}</h3>
        <p className="text-[13px] text-[#5f6368]">{phone}</p>
        {lead?.on_hold && (
          <span className="mt-2 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-[#f0ecd0] text-[#8a7a2a]">
            Em espera
          </span>
        )}
      </div>

      {lead ? (
        <div className="p-4 space-y-4 text-sm">
          {/* Stage info */}
          <div className="space-y-3">
            <div>
              <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-0.5">Stage (Agente)</span>
              <span className="text-[14px] text-[#1f1f1f]">{stageInfo?.label || lead.stage}</span>
            </div>
            <div>
              <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-0.5">Stage (Vendedor)</span>
              <select
                value={lead.seller_stage}
                onChange={(e) => onSellerStageChange(e.target.value)}
                className="input-field text-[14px] rounded-xl px-3 py-1.5 mt-1 w-full"
              >
                {SELLER_STAGES.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Sale Value */}
          <EditableField
            label="Valor da Venda"
            value={String(lead.sale_value || 0)}
            onSave={(v) => updateLeadField("sale_value", v)}
            placeholder="0"
            mask="currency"
          />

          {/* B2B Fields */}
          <div className="border-t border-[#e5e5dc] pt-4 space-y-3">
            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-[#9ca3af]">Dados da Empresa</h4>
            <EditableField label="CNPJ" value={lead.cnpj} onSave={(v) => updateLeadField("cnpj", v)} placeholder="00.000.000/0000-00" />
            <EditableField label="Razao Social" value={lead.razao_social} onSave={(v) => updateLeadField("razao_social", v)} />
            <EditableField label="Nome Fantasia" value={lead.nome_fantasia} onSave={(v) => updateLeadField("nome_fantasia", v)} />
            <EditableField label="Inscricao Estadual" value={lead.inscricao_estadual} onSave={(v) => updateLeadField("inscricao_estadual", v)} />
            <EditableField label="Endereco" value={lead.endereco} onSave={(v) => updateLeadField("endereco", v)} />
          </div>

          {/* Contact Info */}
          <div className="border-t border-[#e5e5dc] pt-4 space-y-3">
            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-[#9ca3af]">Contato</h4>
            <EditableField label="Telefone Comercial" value={lead.telefone_comercial} onSave={(v) => updateLeadField("telefone_comercial", v)} />
            <EditableField label="Email" value={lead.email} onSave={(v) => updateLeadField("email", v)} />
            <EditableField label="Instagram" value={lead.instagram} onSave={(v) => updateLeadField("instagram", v)} placeholder="@usuario" />
          </div>

          {/* Tags */}
          <div className="border-t border-[#e5e5dc] pt-4">
            <span className="text-[11px] uppercase tracking-wider text-[#9ca3af] block mb-2">Tags</span>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {leadTags.map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs text-white"
                  style={{ backgroundColor: tag.color }}
                >
                  {tag.name}
                  <button onClick={() => onTagToggle(tag.id, false)} className="hover:opacity-70 ml-0.5">x</button>
                </span>
              ))}
            </div>
            <div className="relative">
              <button
                onClick={() => setShowTagDropdown(!showTagDropdown)}
                className="text-[12px] text-[#5f6368] hover:underline"
              >
                + Adicionar tag
              </button>
              {showTagDropdown && availableTags.length > 0 && (
                <div className="absolute top-6 left-0 bg-white rounded-xl shadow-lg border border-[#e5e5dc] py-1 z-10 min-w-[160px]">
                  {availableTags.map((tag) => (
                    <button
                      key={tag.id}
                      onClick={() => { onTagToggle(tag.id, true); setShowTagDropdown(false); }}
                      className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-[#1f1f1f] hover:bg-[#f6f7ed] transition-colors"
                    >
                      <span className="w-3 h-3 rounded-full" style={{ backgroundColor: tag.color }} />
                      {tag.name}
                    </button>
                  ))}
                </div>
              )}
              {showTagDropdown && availableTags.length === 0 && (
                <div className="absolute top-6 left-0 bg-white rounded-xl shadow-lg border border-[#e5e5dc] p-3 z-10">
                  <p className="text-[#9ca3af] text-xs">Nenhuma tag disponivel.</p>
                </div>
              )}
            </div>
          </div>

          {/* Contact Stats */}
          <div className="border-t border-[#e5e5dc] pt-4 space-y-2">
            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-[#9ca3af]">Estatisticas</h4>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#5f6368]">Dias ativos</span>
              <span className="text-[13px] font-medium text-[#1f1f1f]">{daysActive}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#5f6368]">Fonte</span>
              <span className="text-[13px] font-medium text-[#1f1f1f]">{lead.channel}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#5f6368]">Criado em</span>
              <span className="text-[13px] font-medium text-[#1f1f1f]">
                {new Date(lead.created_at).toLocaleDateString("pt-BR")}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="p-4 space-y-4">
          <div className="bg-[#f6f7ed] border border-[#e5e5dc] rounded-xl p-3">
            <p className="text-[#5f6368] text-sm font-medium">Contato pessoal</p>
            <p className="text-[#9ca3af] text-xs mt-1">Este contato nao esta cadastrado como lead.</p>
          </div>
          <button onClick={onCreateLead} className="btn-primary w-full py-2 rounded-xl text-sm">
            Criar Lead
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/conversas/editable-field.tsx crm/src/components/conversas/contact-detail.tsx
git commit -m "feat: enrich ContactDetail with inline-editable B2B fields and contact stats"
```

---

## Task 9: Chat Action Buttons + Audio Player

**Files:**
- Create: `crm/src/components/conversas/action-buttons.tsx`
- Create: `crm/src/components/conversas/audio-player.tsx`
- Modify: `crm/src/components/conversas/chat-view.tsx`

- [ ] **Step 1: Create ActionButtons component**

Create `crm/src/components/conversas/action-buttons.tsx`:

```tsx
"use client";

import { createClient } from "@/lib/supabase/client";
import type { Lead } from "@/lib/types";

interface ActionButtonsProps {
  lead: Lead;
  onLeadUpdated: (updates: Partial<Lead>) => void;
}

export function ActionButtons({ lead, onLeadUpdated }: ActionButtonsProps) {
  const supabase = createClient();

  async function handleClose() {
    await supabase.from("leads").update({ seller_stage: "perdido" }).eq("id", lead.id);
    onLeadUpdated({ seller_stage: "perdido" });
  }

  async function handleHold() {
    const newHold = !lead.on_hold;
    await supabase.from("leads").update({ on_hold: newHold }).eq("id", lead.id);
    onLeadUpdated({ on_hold: newHold });
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handleClose}
        className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-[#a33] bg-[#f0d8d8] hover:bg-[#e8c0c0] transition-colors"
      >
        Fechar conversa
      </button>
      <button
        onClick={handleHold}
        className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors ${
          lead.on_hold
            ? "text-[#1f1f1f] bg-[#e5e5dc] hover:bg-[#d5d5cc]"
            : "text-[#8a7a2a] bg-[#f0ecd0] hover:bg-[#e8e0b8]"
        }`}
      >
        {lead.on_hold ? "Remover espera" : "Colocar em espera"}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Create AudioPlayer component**

Create `crm/src/components/conversas/audio-player.tsx`:

```tsx
"use client";

import { useState, useRef } from "react";

interface AudioPlayerProps {
  src: string;
}

export function AudioPlayer({ src }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);

  function togglePlay() {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
    } else {
      audio.play();
    }
    setPlaying(!playing);
  }

  function handleTimeUpdate() {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;
    setProgress((audio.currentTime / audio.duration) * 100);
  }

  function handleLoadedMetadata() {
    const audio = audioRef.current;
    if (audio) setDuration(audio.duration);
  }

  function handleEnded() {
    setPlaying(false);
    setProgress(0);
  }

  function handleSeek(e: React.MouseEvent<HTMLDivElement>) {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    audio.currentTime = pct * audio.duration;
  }

  function formatTime(s: number): string {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  return (
    <div className="flex items-center gap-2 min-w-[200px]">
      <audio
        ref={audioRef}
        src={src}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onEnded={handleEnded}
        preload="metadata"
      />
      <button
        onClick={togglePlay}
        className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center flex-shrink-0 hover:bg-white/30 transition-colors"
      >
        {playing ? (
          <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
            <rect x="2" y="1" width="3" height="10" rx="1" />
            <rect x="7" y="1" width="3" height="10" rx="1" />
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
            <path d="M3 1.5v9l7.5-4.5L3 1.5z" />
          </svg>
        )}
      </button>
      <div className="flex-1 flex items-center gap-2">
        <div
          className="flex-1 h-1.5 rounded-full bg-white/20 cursor-pointer"
          onClick={handleSeek}
        >
          <div
            className="h-full rounded-full bg-white/60 transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="text-[10px] opacity-60 min-w-[32px]">
          {duration > 0 ? formatTime(duration) : "0:00"}
        </span>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Update ChatView to use ActionButtons and AudioPlayer**

Replace entire content of `crm/src/components/conversas/chat-view.tsx`:

```tsx
"use client";

import { useState, useEffect, useRef } from "react";
import { AudioPlayer } from "./audio-player";
import { ActionButtons } from "./action-buttons";
import type { EvolutionMessage, Lead, Tag } from "@/lib/types";

interface ChatViewProps {
  phone: string;
  lead: Lead | null;
  tags: Tag[];
  pushName: string | null;
  onLeadCreated?: (lead: Lead) => void;
  onLeadUpdated?: (updates: Partial<Lead>) => void;
}

function extractText(msg: EvolutionMessage): string {
  if (msg.message.conversation) return msg.message.conversation;
  if (msg.message.imageMessage?.caption) return msg.message.imageMessage.caption;
  if (msg.message.documentMessage?.fileName) return `[Documento: ${msg.message.documentMessage.fileName}]`;
  if (msg.message.audioMessage) return "";
  if (msg.message.imageMessage) return "[Imagem]";
  if (msg.message.stickerMessage) return "[Sticker]";
  if (msg.message.videoMessage?.caption) return msg.message.videoMessage.caption;
  if (msg.message.videoMessage) return "[Video]";
  return "[Midia]";
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export function ChatView({ phone, lead, tags, pushName, onLeadCreated, onLeadUpdated }: ChatViewProps) {
  const [messages, setMessages] = useState<EvolutionMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setLoading(true);
    setMessages([]);
    fetchMessages();
  }, [phone]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function fetchMessages() {
    try {
      const res = await fetch(`/api/evolution/messages/${phone}`);
      if (res.ok) {
        const data = await res.json();
        const sorted = (Array.isArray(data) ? data : []).sort(
          (a: EvolutionMessage, b: EvolutionMessage) => a.messageTimestamp - b.messageTimestamp
        );
        setMessages(sorted);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  async function handleSend() {
    if (!text.trim() || sending) return;
    setSending(true);
    try {
      const res = await fetch("/api/evolution/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, text: text.trim() }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.lead && onLeadCreated) onLeadCreated(data.lead);
        setText("");
        setTimeout(fetchMessages, 500);
      }
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const displayName = lead?.name || pushName || phone;

  const leadTags = lead
    ? tags.filter((t) => lead && (lead as Lead & { tag_ids?: string[] }).tag_ids?.includes(t.id))
    : [];

  return (
    <div className="flex-1 flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-white border-b border-[#e5e5dc]">
        <div className="w-10 h-10 rounded-full bg-[#c8cc8e] flex items-center justify-center text-white font-medium">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1">
          <h2 className="text-[#1f1f1f] font-medium text-sm">{displayName}</h2>
          <p className="text-[#9ca3af] text-xs">{phone}</p>
        </div>
        {leadTags.length > 0 && (
          <div className="flex gap-1">
            {leadTags.map((tag) => (
              <span key={tag.id} className="px-2 py-0.5 rounded-full text-xs text-white" style={{ backgroundColor: tag.color }}>
                {tag.name}
              </span>
            ))}
          </div>
        )}
        {lead && onLeadUpdated && (
          <ActionButtons lead={lead} onLeadUpdated={onLeadUpdated} />
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2 bg-[#f6f7ed]">
        {loading && (
          <div className="flex justify-center py-8">
            <div className="w-6 h-6 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {!loading && messages.length === 0 && (
          <p className="text-[#9ca3af] text-sm text-center py-8">Nenhuma mensagem.</p>
        )}
        {messages.map((msg) => {
          const isAudio = !!msg.message.audioMessage?.url;
          const textContent = extractText(msg);

          return (
            <div key={msg.key.id} className={`flex ${msg.key.fromMe ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[70%] px-3 py-2 ${
                  msg.key.fromMe
                    ? "bg-[#1f1f1f] text-white rounded-2xl rounded-br-sm"
                    : "bg-white border border-[#e5e5dc] text-[#1f1f1f] rounded-2xl rounded-bl-sm"
                }`}
              >
                {msg.message.imageMessage?.url && (
                  <img src={msg.message.imageMessage.url} alt="" className="max-w-full rounded mb-1" />
                )}
                {isAudio && (
                  <AudioPlayer src={msg.message.audioMessage!.url!} />
                )}
                {textContent && (
                  <p className="text-sm whitespace-pre-wrap break-words">{textContent}</p>
                )}
                <p className={`text-[11px] mt-1 ${msg.key.fromMe ? "text-white/50" : "text-[#9ca3af]"}`}>
                  {formatTime(msg.messageTimestamp)}
                </p>
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 bg-white border-t border-[#e5e5dc]">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Digitar mensagem..."
            rows={1}
            className="flex-1 bg-[#f6f7ed] text-[#1f1f1f] text-sm rounded-2xl px-4 py-2.5 placeholder-[#9ca3af] outline-none focus:ring-1 focus:ring-[#c8cc8e] resize-none max-h-32 border border-[#e5e5dc]"
          />
          <button
            onClick={handleSend}
            disabled={sending || !text.trim()}
            className="bg-[#1f1f1f] text-white p-2.5 rounded-full hover:bg-[#333] disabled:opacity-50 flex-shrink-0 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Update ConversasPage to pass onLeadUpdated**

In `crm/src/app/(authenticated)/conversas/page.tsx`, find the `<ChatView` component call and add `onLeadUpdated`:

In the component, add a handler function after `handleSellerStageChange`:

```typescript
function handleLeadUpdated(updates: Partial<Lead>) {
  if (!selectedLead) return;
  setLeads((prev) =>
    prev.map((l) =>
      l.id === selectedLead.id ? { ...l, ...updates } : l
    )
  );
}
```

Then update the `<ChatView` JSX to include:
```tsx
<ChatView
  phone={selectedPhone}
  lead={selectedLead}
  tags={tags}
  pushName={selectedPushName}
  onLeadCreated={handleLeadCreated}
  onLeadUpdated={handleLeadUpdated}
/>
```

- [ ] **Step 5: Verify it compiles**

Run: `cd crm && npx next build --no-lint 2>&1 | tail -20`

- [ ] **Step 6: Commit**

```bash
git add crm/src/components/conversas/action-buttons.tsx crm/src/components/conversas/audio-player.tsx crm/src/components/conversas/chat-view.tsx crm/src/app/\(authenticated\)/conversas/page.tsx
git commit -m "feat: add chat action buttons, audio player, and pass onLeadUpdated to ChatView"
```

---

## Task 10: Estatisticas Page - Period Filter + Vendas Analysis

**Files:**
- Create: `crm/src/components/estatisticas/period-filter.tsx`
- Create: `crm/src/components/estatisticas/vendas-analysis.tsx`

- [ ] **Step 1: Create PeriodFilter component**

Create `crm/src/components/estatisticas/period-filter.tsx`:

```tsx
"use client";

export type PeriodKey = "7d" | "30d" | "90d" | "custom";

interface PeriodFilterProps {
  period: PeriodKey;
  onPeriodChange: (p: PeriodKey) => void;
  customStart?: string;
  customEnd?: string;
  onCustomStartChange?: (v: string) => void;
  onCustomEndChange?: (v: string) => void;
}

const PRESETS: { key: PeriodKey; label: string }[] = [
  { key: "7d", label: "7 dias" },
  { key: "30d", label: "30 dias" },
  { key: "90d", label: "90 dias" },
  { key: "custom", label: "Customizado" },
];

export function getPeriodStartDate(period: PeriodKey, customStart?: string): Date {
  if (period === "custom" && customStart) return new Date(customStart);
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  if (period === "7d") d.setDate(d.getDate() - 7);
  if (period === "30d") d.setDate(d.getDate() - 30);
  if (period === "90d") d.setDate(d.getDate() - 90);
  return d;
}

export function PeriodFilter({
  period,
  onPeriodChange,
  customStart,
  customEnd,
  onCustomStartChange,
  onCustomEndChange,
}: PeriodFilterProps) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex gap-1">
        {PRESETS.map((p) => (
          <button
            key={p.key}
            onClick={() => onPeriodChange(p.key)}
            className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors ${
              period === p.key
                ? "bg-[#1f1f1f] text-white"
                : "text-[#5f6368] hover:bg-[#f6f7ed] border border-[#e5e5dc]"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      {period === "custom" && (
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={customStart || ""}
            onChange={(e) => onCustomStartChange?.(e.target.value)}
            className="input-field text-[12px] rounded-lg px-2 py-1.5"
          />
          <span className="text-[#9ca3af] text-xs">ate</span>
          <input
            type="date"
            value={customEnd || ""}
            onChange={(e) => onCustomEndChange?.(e.target.value)}
            className="input-field text-[12px] rounded-lg px-2 py-1.5"
          />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create VendasAnalysis component**

Create `crm/src/components/estatisticas/vendas-analysis.tsx`:

```tsx
"use client";

import { SELLER_STAGES } from "@/lib/constants";
import type { Lead } from "@/lib/types";

interface VendasAnalysisProps {
  leads: Lead[];
  periodStart: Date;
}

export function VendasAnalysis({ leads, periodStart }: VendasAnalysisProps) {
  const stages = SELLER_STAGES;
  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  const data = stages.map((stage) => {
    const inStage = leads.filter((l) => l.seller_stage === stage.key);
    const entered = inStage.filter(
      (l) => l.entered_stage_at && new Date(l.entered_stage_at) >= periodStart
    );
    const lost = leads.filter(
      (l) =>
        l.seller_stage === "perdido" &&
        l.entered_stage_at &&
        new Date(l.entered_stage_at) >= periodStart
    );
    const value = inStage.reduce((sum, l) => sum + (l.sale_value || 0), 0);
    const enteredValue = entered.reduce((sum, l) => sum + (l.sale_value || 0), 0);
    const lostForStage = lost.filter(() => false); // Per-stage loss tracking requires historical data

    return {
      ...stage,
      count: inStage.length,
      value,
      entered: entered.length,
      enteredValue,
      lost: lostForStage.length,
      lostValue: 0,
    };
  });

  // Conversion rates
  const totalLeads = leads.length;
  const closedLeads = leads.filter((l) => l.seller_stage === "fechado");

  return (
    <div className="space-y-6">
      {/* Funnel Table */}
      <div className="card overflow-hidden">
        <table className="w-full text-[12px]">
          <thead>
            <tr>
              <th className="text-left py-3 px-4 text-[#9ca3af] font-medium uppercase tracking-wider text-[11px] bg-[#f6f7ed]" />
              {data.map((d) => (
                <th key={d.key} className="text-center py-3 px-4 min-w-[140px] bg-[#f6f7ed]">
                  <div className={`h-1.5 rounded-full mb-2 ${d.color}`} />
                  <span className="text-[12px] font-semibold text-[#1f1f1f]">{d.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-[#e5e5dc]">
              <td className="py-3 px-4 text-[#5f6368] font-medium">Dentro da etapa</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-3 px-4">
                  <div className="text-[16px] font-bold text-[#1f1f1f]">{d.count}</div>
                  <div className="text-[11px] text-[#5f6368]">{fmt(d.value)}</div>
                </td>
              ))}
            </tr>
            <tr className="border-t border-[#e5e5dc]">
              <td className="py-3 px-4 text-[#5f6368] font-medium">Entrou na etapa</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-3 px-4">
                  <div className={`text-[16px] font-bold ${d.entered > 0 ? "text-[#2d6a3f]" : "text-[#9ca3af]"}`}>
                    {d.entered > 0 ? `+${d.entered}` : "0"}
                  </div>
                  {d.entered > 0 && (
                    <div className="text-[11px] text-[#5f6368]">{fmt(d.enteredValue)}</div>
                  )}
                </td>
              ))}
            </tr>
            <tr className="border-t border-[#e5e5dc]">
              <td className="py-3 px-4 text-[#5f6368] font-medium">Perda</td>
              {data.map((d) => (
                <td key={d.key} className="text-center py-3 px-4 text-[#9ca3af]">
                  {d.lost} leads, {fmt(d.lostValue)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      {/* Conversion summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="card p-4 text-center">
          <div className="text-[11px] uppercase tracking-wider text-[#9ca3af] mb-1">Total leads</div>
          <div className="text-[24px] font-bold text-[#1f1f1f]">{totalLeads}</div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-[11px] uppercase tracking-wider text-[#9ca3af] mb-1">Fechados</div>
          <div className="text-[24px] font-bold text-[#2d6a3f]">{closedLeads.length}</div>
          <div className="text-[12px] text-[#5f6368]">
            {fmt(closedLeads.reduce((s, l) => s + (l.sale_value || 0), 0))}
          </div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-[11px] uppercase tracking-wider text-[#9ca3af] mb-1">Taxa de conversao</div>
          <div className="text-[24px] font-bold text-[#1f1f1f]">
            {totalLeads > 0 ? `${Math.round((closedLeads.length / totalLeads) * 100)}%` : "\u2014"}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/estatisticas/period-filter.tsx crm/src/components/estatisticas/vendas-analysis.tsx
git commit -m "feat: add period filter and vendas analysis components for estatisticas"
```

---

## Task 11: Estatisticas Page - Tempo Report + Vendedor Report

**Files:**
- Create: `crm/src/components/estatisticas/tempo-report.tsx`
- Create: `crm/src/components/estatisticas/vendedor-report.tsx`

- [ ] **Step 1: Create TempoReport component**

Create `crm/src/components/estatisticas/tempo-report.tsx`:

```tsx
"use client";

import { SELLER_STAGES } from "@/lib/constants";
import type { Lead } from "@/lib/types";

interface TempoReportProps {
  leads: Lead[];
}

export function TempoReport({ leads }: TempoReportProps) {
  const now = Date.now();

  // Average time in each stage
  const stageData = SELLER_STAGES.map((stage) => {
    const inStage = leads.filter((l) => l.seller_stage === stage.key && l.entered_stage_at);
    const totalDays = inStage.reduce((sum, l) => {
      const days = (now - new Date(l.entered_stage_at!).getTime()) / (1000 * 60 * 60 * 24);
      return sum + days;
    }, 0);
    const avgDays = inStage.length > 0 ? Math.round(totalDays / inStage.length) : 0;
    const maxDays = inStage.length > 0
      ? Math.round(Math.max(...inStage.map((l) => (now - new Date(l.entered_stage_at!).getTime()) / (1000 * 60 * 60 * 24))))
      : 0;

    return { ...stage, count: inStage.length, avgDays, maxDays };
  });

  // Sort by avgDays descending (bottleneck ranking)
  const bottlenecks = [...stageData].sort((a, b) => b.avgDays - a.avgDays);

  // Average first response time
  const withResponse = leads.filter((l) => l.first_response_at);
  const avgResponseMin = withResponse.length > 0
    ? Math.round(
        withResponse.reduce((sum, l) => {
          return sum + (new Date(l.first_response_at!).getTime() - new Date(l.created_at).getTime());
        }, 0) / withResponse.length / 60000
      )
    : 0;

  // Leads stuck > 30 days
  const stuckLeads = leads.filter((l) => {
    if (!l.entered_stage_at) return false;
    if (l.seller_stage === "fechado" || l.seller_stage === "perdido") return false;
    const days = (now - new Date(l.entered_stage_at).getTime()) / (1000 * 60 * 60 * 24);
    return days > 30;
  });

  return (
    <div className="space-y-6">
      {/* First Response Time */}
      <div className="card p-5">
        <h4 className="text-[13px] font-semibold uppercase tracking-wider text-[#9ca3af] mb-3">
          Tempo medio de primeira resposta
        </h4>
        <div className="text-[32px] font-bold text-[#1f1f1f]">
          {avgResponseMin > 0 ? `${avgResponseMin}m` : "\u2014"}
        </div>
        <p className="text-[12px] text-[#5f6368] mt-1">
          Baseado em {withResponse.length} leads com resposta registrada
        </p>
      </div>

      {/* Time per Stage */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 bg-[#f6f7ed] border-b border-[#e5e5dc]">
          <h4 className="text-[13px] font-semibold uppercase tracking-wider text-[#9ca3af]">
            Tempo medio por etapa
          </h4>
        </div>
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-[#e5e5dc]">
              <th className="text-left px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Etapa</th>
              <th className="text-center px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Leads</th>
              <th className="text-center px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Media (dias)</th>
              <th className="text-center px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Maximo (dias)</th>
            </tr>
          </thead>
          <tbody>
            {stageData.map((s) => (
              <tr key={s.key} className="border-b border-[#e5e5dc] last:border-0 hover:bg-[#f6f7ed]/50">
                <td className="px-5 py-3">
                  <div className="flex items-center gap-2">
                    <span className={`w-2.5 h-2.5 rounded-full ${s.color}`} />
                    <span className="font-medium text-[#1f1f1f]">{s.label}</span>
                  </div>
                </td>
                <td className="text-center px-5 py-3 text-[#5f6368]">{s.count}</td>
                <td className="text-center px-5 py-3 font-medium text-[#1f1f1f]">{s.avgDays}d</td>
                <td className={`text-center px-5 py-3 font-medium ${s.maxDays > 30 ? "text-[#a33]" : "text-[#5f6368]"}`}>
                  {s.maxDays}d
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Bottleneck Ranking */}
      <div className="card p-5">
        <h4 className="text-[13px] font-semibold uppercase tracking-wider text-[#9ca3af] mb-3">
          Ranking de gargalos
        </h4>
        <div className="space-y-2">
          {bottlenecks.map((s, i) => (
            <div key={s.key} className="flex items-center gap-3">
              <span className="text-[14px] font-bold text-[#9ca3af] w-6">{i + 1}.</span>
              <span className={`w-2.5 h-2.5 rounded-full ${s.color}`} />
              <span className="text-[13px] text-[#1f1f1f] flex-1">{s.label}</span>
              <span className={`text-[13px] font-bold ${s.avgDays > 30 ? "text-[#a33]" : "text-[#1f1f1f]"}`}>
                {s.avgDays}d media
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Stuck Leads */}
      {stuckLeads.length > 0 && (
        <div className="card p-5 border-l-4 border-l-[#a33]">
          <h4 className="text-[13px] font-semibold uppercase tracking-wider text-[#a33] mb-2">
            Leads parados ha mais de 30 dias
          </h4>
          <p className="text-[24px] font-bold text-[#a33]">{stuckLeads.length}</p>
          <div className="mt-3 space-y-1">
            {stuckLeads.slice(0, 10).map((l) => {
              const days = Math.round((now - new Date(l.entered_stage_at!).getTime()) / (1000 * 60 * 60 * 24));
              return (
                <div key={l.id} className="flex items-center justify-between text-[12px]">
                  <span className="text-[#1f1f1f]">{l.name || l.phone}</span>
                  <span className="text-[#a33] font-medium">{days}d em {l.seller_stage}</span>
                </div>
              );
            })}
            {stuckLeads.length > 10 && (
              <p className="text-[11px] text-[#9ca3af]">e mais {stuckLeads.length - 10} leads...</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create VendedorReport component**

Create `crm/src/components/estatisticas/vendedor-report.tsx`:

```tsx
"use client";

import type { Lead } from "@/lib/types";

interface VendedorReportProps {
  leads: Lead[];
  periodStart: Date;
}

export function VendedorReport({ leads, periodStart }: VendedorReportProps) {
  // Group leads by assigned_to
  const vendedorMap = new Map<string, Lead[]>();

  leads.forEach((l) => {
    const vendedor = l.assigned_to || "Nao atribuido";
    if (!vendedorMap.has(vendedor)) vendedorMap.set(vendedor, []);
    vendedorMap.get(vendedor)!.push(l);
  });

  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  type SortKey = "vendedor" | "ativos" | "ganhos" | "perdidos" | "valor" | "taxa";

  const rows = Array.from(vendedorMap.entries()).map(([vendedor, vLeads]) => {
    const ativos = vLeads.filter((l) => l.seller_stage !== "perdido" && l.seller_stage !== "fechado");
    const ganhos = vLeads.filter((l) => l.seller_stage === "fechado");
    const perdidos = vLeads.filter((l) => l.seller_stage === "perdido");
    const valor = vLeads.reduce((sum, l) => sum + (l.sale_value || 0), 0);
    const taxa = vLeads.length > 0 ? Math.round((ganhos.length / vLeads.length) * 100) : 0;

    return {
      vendedor,
      ativos: ativos.length,
      ganhos: ganhos.length,
      perdidos: perdidos.length,
      valor,
      taxa,
    };
  });

  // Sort by valor descending
  rows.sort((a, b) => b.valor - a.valor);

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 bg-[#f6f7ed] border-b border-[#e5e5dc]">
        <h4 className="text-[13px] font-semibold uppercase tracking-wider text-[#9ca3af]">
          Performance por Vendedor
        </h4>
      </div>
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-[#e5e5dc]">
            <th className="text-left px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Vendedor</th>
            <th className="text-center px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Ativos</th>
            <th className="text-center px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Ganhos</th>
            <th className="text-center px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Perdidos</th>
            <th className="text-center px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Valor Total</th>
            <th className="text-center px-5 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Taxa de Conversao</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.vendedor} className="border-b border-[#e5e5dc] last:border-0 hover:bg-[#f6f7ed]/50">
              <td className="px-5 py-3 font-medium text-[#1f1f1f]">{r.vendedor}</td>
              <td className="text-center px-5 py-3 text-[#5f6368]">{r.ativos}</td>
              <td className="text-center px-5 py-3 text-[#2d6a3f] font-medium">{r.ganhos}</td>
              <td className="text-center px-5 py-3 text-[#a33] font-medium">{r.perdidos}</td>
              <td className="text-center px-5 py-3 font-medium text-[#1f1f1f]">{fmt(r.valor)}</td>
              <td className="text-center px-5 py-3">
                <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                  r.taxa >= 50
                    ? "bg-[#d8f0dc] text-[#2d6a3f]"
                    : r.taxa >= 25
                    ? "bg-[#f0ecd0] text-[#8a7a2a]"
                    : "bg-[#f0d8d8] text-[#a33]"
                }`}>
                  {r.taxa}%
                </span>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="text-center py-8 text-[#9ca3af]">
                Nenhum dado disponivel
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/estatisticas/tempo-report.tsx crm/src/components/estatisticas/vendedor-report.tsx
git commit -m "feat: add tempo report and vendedor report components for estatisticas"
```

---

## Task 12: Estatisticas Page + Sidebar Update

**Files:**
- Create: `crm/src/app/(authenticated)/estatisticas/page.tsx`
- Modify: `crm/src/components/sidebar.tsx`

- [ ] **Step 1: Create Estatisticas page**

Create `crm/src/app/(authenticated)/estatisticas/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useRealtimeLeads } from "@/hooks/use-realtime-leads";
import { PeriodFilter, getPeriodStartDate, type PeriodKey } from "@/components/estatisticas/period-filter";
import { VendasAnalysis } from "@/components/estatisticas/vendas-analysis";
import { TempoReport } from "@/components/estatisticas/tempo-report";
import { VendedorReport } from "@/components/estatisticas/vendedor-report";

type Tab = "vendas" | "tempo" | "vendedor";

const TABS: { key: Tab; label: string }[] = [
  { key: "vendas", label: "Analise de vendas" },
  { key: "tempo", label: "Relatorio de tempo" },
  { key: "vendedor", label: "Relatorio por vendedor" },
];

export default function EstatisticasPage() {
  const { leads, loading } = useRealtimeLeads();
  const [activeTab, setActiveTab] = useState<Tab>("vendas");
  const [period, setPeriod] = useState<PeriodKey>("30d");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  const periodStart = getPeriodStartDate(period, customStart);

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

  return (
    <div className="flex gap-6 h-full">
      {/* Left nav */}
      <div className="w-[200px] flex-shrink-0">
        <h1 className="text-[28px] font-bold text-[#1f1f1f] mb-6">Estatisticas</h1>
        <nav className="space-y-1">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`w-full text-left px-3 py-2 rounded-lg text-[13px] font-medium transition-colors ${
                activeTab === tab.key
                  ? "bg-[#1f1f1f] text-white"
                  : "text-[#5f6368] hover:bg-[#f6f7ed] hover:text-[#1f1f1f]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="mb-6">
          <PeriodFilter
            period={period}
            onPeriodChange={setPeriod}
            customStart={customStart}
            customEnd={customEnd}
            onCustomStartChange={setCustomStart}
            onCustomEndChange={setCustomEnd}
          />
        </div>

        {activeTab === "vendas" && (
          <VendasAnalysis leads={leads} periodStart={periodStart} />
        )}
        {activeTab === "tempo" && (
          <TempoReport leads={leads} />
        )}
        {activeTab === "vendedor" && (
          <VendedorReport leads={leads} periodStart={periodStart} />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add Estatisticas to sidebar**

In `crm/src/components/sidebar.tsx`, add a new nav item after the "Campanhas" entry and before the "Configuracoes" entry in the `NAV_ITEMS` array:

```tsx
  {
    href: "/estatisticas",
    label: "Estatisticas",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
    ),
  },
```

Insert this object between the Campanhas entry (href: "/campanhas") and the Configuracoes entry (href: "/config") in the NAV_ITEMS array.

- [ ] **Step 3: Verify it compiles**

Run: `cd crm && npx next build --no-lint 2>&1 | tail -20`

- [ ] **Step 4: Commit**

```bash
git add crm/src/app/\(authenticated\)/estatisticas/page.tsx crm/src/components/sidebar.tsx
git commit -m "feat: add Estatisticas page with vendas analysis, tempo report, and vendedor report"
```

---

## Task 13: Final Verification and Integration Fix

**Files:**
- Various — fix any compilation errors from the full build

- [ ] **Step 1: Run full build**

Run: `cd crm && npx next build --no-lint 2>&1`

Check for TypeScript errors. Common issues to watch for:
- Missing props passed to components that were updated
- Import paths for new files
- Type mismatches from the enriched Lead interface

- [ ] **Step 2: Fix any errors found**

Address each compilation error. Common fixes:
- If `LeadCard` is called without new optional props, that's fine — they're all optional
- If `ChatView` gets a type error on `onLeadUpdated`, verify it was added to the props interface
- If `campaign-table.tsx` or other unchanged files error, check if they reference Lead fields that moved

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "fix: resolve compilation errors after Kommo migration integration"
```

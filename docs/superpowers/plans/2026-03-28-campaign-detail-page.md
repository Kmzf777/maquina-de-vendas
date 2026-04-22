# Campaign Detail Page + Enhanced Campaign List — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the CRM campaign page with expanded cards showing cadence metrics, and add a new `/campanhas/[id]` detail page with KPIs, leads in cadence, steps editing, and activity timeline.

**Architecture:** Client-side React components using Supabase Realtime for campaigns and direct Supabase queries for cadence data. All pages are `"use client"` following existing patterns. FastAPI backend already has cadence endpoints (`/api/campaigns/{id}/cadence`, `/api/leads/{lead_id}/cadence`).

**Tech Stack:** Next.js 16.2.1 (App Router), React 19, Tailwind CSS 4, Supabase JS client, DM Sans font, design system from `globals.css`.

**IMPORTANT — Next.js 16 notes:**
- `useParams` from `next/navigation` (not `next/router`)
- `useRouter` from `next/navigation`
- Dynamic routes use `[id]` folder convention
- All pages here are `"use client"` components

---

### Task 1: Update TypeScript Types

**Files:**
- Modify: `crm/src/lib/types.ts`

- [ ] **Step 1: Add cadence fields to Campaign interface and new types**

Add cadence configuration and counter fields to the existing `Campaign` interface, plus new `CadenceStep` and `CadenceState` interfaces:

```typescript
// In crm/src/lib/types.ts — replace the Campaign interface (lines 80-93) with:

export interface Campaign {
  id: string;
  name: string;
  template_name: string;
  template_params: Record<string, unknown> | null;
  total_leads: number;
  sent: number;
  failed: number;
  replied: number;
  status: string;
  send_interval_min: number;
  send_interval_max: number;
  created_at: string;
  // Cadence config
  cadence_interval_hours: number;
  cadence_send_start_hour: number;
  cadence_send_end_hour: number;
  cadence_cooldown_hours: number;
  cadence_max_messages: number;
  // Cadence counters
  cadence_sent: number;
  cadence_responded: number;
  cadence_exhausted: number;
  cadence_cooled: number;
}

export interface CadenceStep {
  id: string;
  campaign_id: string;
  stage: string;
  step_order: number;
  message_text: string;
  created_at: string;
}

export interface CadenceState {
  id: string;
  lead_id: string;
  campaign_id: string;
  current_step: number;
  status: "active" | "responded" | "exhausted" | "cooled";
  total_messages_sent: number;
  max_messages: number;
  next_send_at: string | null;
  cooldown_until: string | null;
  responded_at: string | null;
  created_at: string;
  leads?: Lead;
}
```

- [ ] **Step 2: Verify build compiles**

Run: `cd crm && npx next build --no-lint 2>&1 | head -20`
Expected: No type errors related to Campaign interface changes (existing code uses `c.sent`, `c.replied`, etc. which are preserved).

- [ ] **Step 3: Commit**

```bash
git add crm/src/lib/types.ts
git commit -m "feat(crm): add cadence fields to Campaign type and new CadenceStep/CadenceState types"
```

---

### Task 2: Add Cadence Status Constants

**Files:**
- Modify: `crm/src/lib/constants.ts`

- [ ] **Step 1: Add cadence status colors and labels**

Append to the end of `crm/src/lib/constants.ts`:

```typescript
export const CADENCE_STATUS_COLORS: Record<string, { dot: string; bg: string; text: string }> = {
  active: { dot: "#f59e0b", bg: "bg-[#fef3c7]", text: "text-[#92400e]" },
  responded: { dot: "#4ade80", bg: "bg-[#d8f0dc]", text: "text-[#2d6a3f]" },
  exhausted: { dot: "#f87171", bg: "bg-[#fee2e2]", text: "text-[#991b1b]" },
  cooled: { dot: "#9ca3af", bg: "bg-[#f4f4f0]", text: "text-[#5f6368]" },
};

export const CADENCE_STATUS_LABELS: Record<string, string> = {
  active: "Ativo",
  responded: "Respondeu",
  exhausted: "Esgotado",
  cooled: "Esfriado",
};
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/lib/constants.ts
git commit -m "feat(crm): add cadence status colors and labels constants"
```

---

### Task 3: Create Campaign Card Component

**Files:**
- Create: `crm/src/components/campaign-card.tsx`

- [ ] **Step 1: Create the campaign card component**

Create `crm/src/components/campaign-card.tsx`:

```typescript
"use client";

import Link from "next/link";
import type { Campaign } from "@/lib/types";
import { CAMPAIGN_STATUS_COLORS } from "@/lib/constants";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

interface CampaignCardProps {
  campaign: Campaign;
}

export function CampaignCard({ campaign: c }: CampaignCardProps) {
  const totalCadence = (c.cadence_responded || 0) + (c.cadence_exhausted || 0) + (c.cadence_cooled || 0);
  const activeCadence = c.sent - totalCadence;
  const total = c.total_leads || 1;

  // Segmented progress bar widths (percentages of total leads)
  const respondedPct = ((c.cadence_responded || 0) / total) * 100;
  const activePct = (Math.max(0, activeCadence) / total) * 100;
  const exhaustedPct = ((c.cadence_exhausted || 0) / total) * 100;
  const sentOnlyPct = Math.max(0, ((c.sent - (c.cadence_responded || 0) - Math.max(0, activeCadence) - (c.cadence_exhausted || 0) - (c.cadence_cooled || 0)) / total) * 100);

  async function handleAction(action: "start" | "pause") {
    await fetch(`${FASTAPI_URL}/api/campaigns/${c.id}/${action}`, {
      method: "POST",
    });
  }

  return (
    <div className="card card-hover p-6">
      {/* Top row: name + status + actions */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <h3 className="text-[16px] font-semibold text-[#1f1f1f]">{c.name}</h3>
          <span
            className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium ${
              CAMPAIGN_STATUS_COLORS[c.status] || ""
            }`}
          >
            {c.status}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {(c.status === "draft" || c.status === "paused") && (
            <button
              onClick={() => handleAction("start")}
              className="btn-primary px-4 py-1.5 text-[12px] rounded-lg"
            >
              Iniciar
            </button>
          )}
          {c.status === "running" && (
            <button
              onClick={() => handleAction("pause")}
              className="btn-secondary px-4 py-1.5 text-[12px] rounded-lg"
            >
              Pausar
            </button>
          )}
          <Link
            href={`/campanhas/${c.id}`}
            className="btn-secondary px-4 py-1.5 text-[12px] rounded-lg inline-flex items-center gap-1"
          >
            Abrir <span aria-hidden>&rarr;</span>
          </Link>
        </div>
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-4 mb-5 text-[12px] text-[#5f6368]">
        <span>Template: <strong className="text-[#1f1f1f]">{c.template_name}</strong></span>
        <span>Criada em: {new Date(c.created_at).toLocaleDateString("pt-BR")}</span>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-6 gap-4 mb-5">
        <MetricCell label="Total Leads" value={c.total_leads} />
        <MetricCell label="Templates Enviados" value={c.sent} />
        <MetricCell label="Responderam" value={c.cadence_responded || 0} valueColor="#4ade80" />
        <MetricCell label="Em Cadencia" value={Math.max(0, activeCadence)} valueColor="#f59e0b" />
        <MetricCell label="Esgotados" value={c.cadence_exhausted || 0} valueColor="#f87171" />
        <MetricCell label="Esfriados" value={c.cadence_cooled || 0} valueColor="#9ca3af" />
      </div>

      {/* Segmented progress bar */}
      <div className="w-full h-2.5 bg-[#e5e5dc] rounded-full overflow-hidden flex mb-3">
        {respondedPct > 0 && (
          <div className="h-full bg-[#4ade80]" style={{ width: `${respondedPct}%` }} />
        )}
        {activePct > 0 && (
          <div className="h-full bg-[#f59e0b]" style={{ width: `${activePct}%` }} />
        )}
        {exhaustedPct > 0 && (
          <div className="h-full bg-[#f87171]" style={{ width: `${exhaustedPct}%` }} />
        )}
        {sentOnlyPct > 0 && (
          <div className="h-full bg-[#1f1f1f]" style={{ width: `${sentOnlyPct}%` }} />
        )}
      </div>

      {/* Config tags */}
      <div className="flex items-center gap-2 text-[11px] text-[#5f6368]">
        <span className="px-2 py-0.5 rounded-md bg-[#f4f4f0]">
          Intervalo: {c.cadence_interval_hours || 24}h
        </span>
        <span className="px-2 py-0.5 rounded-md bg-[#f4f4f0]">
          Janela: {c.cadence_send_start_hour || 7}h–{c.cadence_send_end_hour || 18}h
        </span>
        <span className="px-2 py-0.5 rounded-md bg-[#f4f4f0]">
          Max: {c.cadence_max_messages || 8} msgs
        </span>
      </div>
    </div>
  );
}

function MetricCell({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: number;
  valueColor?: string;
}) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-wider text-[#9ca3af] mb-1">
        {label}
      </p>
      <p
        className="text-[20px] font-bold"
        style={{ color: valueColor || "#1f1f1f" }}
      >
        {value}
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/campaign-card.tsx
git commit -m "feat(crm): create CampaignCard component with cadence metrics and progress bar"
```

---

### Task 4: Refactor Campaign List Page

**Files:**
- Modify: `crm/src/app/(authenticated)/campanhas/page.tsx`

- [ ] **Step 1: Replace table with card layout**

Replace the entire contents of `crm/src/app/(authenticated)/campanhas/page.tsx` with:

```typescript
"use client";

import { useState, useRef } from "react";
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
import { CampaignCard } from "@/components/campaign-card";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

export default function CampanhasPage() {
  const { campaigns, loading } = useRealtimeCampaigns();
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [intervalMin, setIntervalMin] = useState(3);
  const [intervalMax, setIntervalMax] = useState(8);
  const [creating, setCreating] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);

    const res = await fetch(`${FASTAPI_URL}/api/campaigns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        template_name: templateName,
        send_interval_min: intervalMin,
        send_interval_max: intervalMax,
      }),
    });

    if (res.ok) {
      const campaign = await res.json();

      const file = fileRef.current?.files?.[0];
      if (file) {
        const formData = new FormData();
        formData.append("file", file);
        await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}/import`, {
          method: "POST",
          body: formData,
        });
      }

      setShowForm(false);
      setName("");
      setTemplateName("");
    }
    setCreating(false);
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-12">
        <div className="w-5 h-5 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
        <p className="text-[#5f6368] text-[14px]">Carregando...</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-[28px] font-bold text-[#1f1f1f]">Campanhas</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="btn-primary flex items-center gap-2 px-5 py-2.5 rounded-xl text-[13px] font-medium"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="8" y1="3" x2="8" y2="13" />
            <line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          Nova Campanha
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleCreate}
          className="card p-6 mb-6 grid grid-cols-2 gap-5"
        >
          <div>
            <label className="block text-[12px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
              Nome
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input-field w-full"
              required
            />
          </div>
          <div>
            <label className="block text-[12px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
              Template
            </label>
            <input
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
              className="input-field w-full"
              required
            />
          </div>
          <div>
            <label className="block text-[12px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
              Intervalo min (s)
            </label>
            <input
              type="number"
              value={intervalMin}
              onChange={(e) => setIntervalMin(Number(e.target.value))}
              className="input-field w-full"
            />
          </div>
          <div>
            <label className="block text-[12px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
              Intervalo max (s)
            </label>
            <input
              type="number"
              value={intervalMax}
              onChange={(e) => setIntervalMax(Number(e.target.value))}
              className="input-field w-full"
            />
          </div>
          <div className="col-span-2">
            <label className="block text-[12px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
              CSV de leads
            </label>
            <label className="flex flex-col items-center justify-center w-full h-28 border-2 border-dashed border-[#e5e5dc] rounded-xl cursor-pointer hover:border-[#c8cc8e] hover:bg-[#f6f7ed]/50 transition-colors">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <span className="text-[13px] text-[#9ca3af] mt-2">
                {fileRef.current?.files?.[0]?.name || "Clique para selecionar um arquivo CSV"}
              </span>
              <input
                ref={fileRef}
                type="file"
                accept=".csv"
                className="hidden"
              />
            </label>
          </div>
          <div className="col-span-2 flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="btn-secondary px-5 py-2.5 rounded-xl text-[13px] font-medium"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={creating}
              className="btn-primary px-5 py-2.5 rounded-xl text-[13px] font-medium disabled:opacity-50"
            >
              {creating ? "Criando..." : "Criar"}
            </button>
          </div>
        </form>
      )}

      <div className="flex flex-col gap-4">
        {campaigns.map((c) => (
          <CampaignCard key={c.id} campaign={c} />
        ))}
        {campaigns.length === 0 && (
          <div className="card p-12 text-center">
            <p className="text-[14px] text-[#5f6368]">Nenhuma campanha criada ainda.</p>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the page renders**

Run: `cd crm && npx next build --no-lint 2>&1 | tail -10`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/(authenticated)/campanhas/page.tsx
git commit -m "feat(crm): refactor campaign list from table to cards with cadence metrics"
```

---

### Task 5: Create Campaign KPIs Component

**Files:**
- Create: `crm/src/components/campaign-kpis.tsx`

- [ ] **Step 1: Create the KPI grid component**

Create `crm/src/components/campaign-kpis.tsx`:

```typescript
import type { Campaign } from "@/lib/types";

interface CampaignKpisProps {
  campaign: Campaign;
}

export function CampaignKpis({ campaign: c }: CampaignKpisProps) {
  const activeCadence = c.sent - (c.cadence_responded || 0) - (c.cadence_exhausted || 0) - (c.cadence_cooled || 0);
  const sentPct = c.total_leads > 0 ? Math.round((c.sent / c.total_leads) * 100) : 0;
  const respondedPct = c.sent > 0 ? Math.round(((c.cadence_responded || 0) / c.sent) * 100) : 0;
  const activePct = c.sent > 0 ? Math.round((Math.max(0, activeCadence) / c.sent) * 100) : 0;

  return (
    <div className="grid grid-cols-6 gap-4">
      <KpiCard label="Total Leads" value={c.total_leads} />
      <KpiCard label="Templates Enviados" value={c.sent} subtitle={`${sentPct}% do total`} />
      <KpiCard label="Responderam" value={c.cadence_responded || 0} valueColor="#4ade80" subtitle={`${respondedPct}% dos enviados`} />
      <KpiCard label="Em Cadencia" value={Math.max(0, activeCadence)} valueColor="#f59e0b" subtitle={`${activePct}% ativos`} />
      <KpiCard label="Esgotados" value={c.cadence_exhausted || 0} valueColor="#f87171" subtitle="bateram limite" />
      <KpiCard label="Esfriados" value={c.cadence_cooled || 0} valueColor="#888" subtitle="sem mais steps" />
    </div>
  );
}

function KpiCard({
  label,
  value,
  valueColor,
  subtitle,
}: {
  label: string;
  value: number;
  valueColor?: string;
  subtitle?: string;
}) {
  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: "var(--bg-dark)" }}
    >
      <p className="text-[10px] font-medium uppercase tracking-wider mb-2" style={{ color: "#888" }}>
        {label}
      </p>
      <p
        className="text-[28px] font-bold"
        style={{ color: valueColor || "#ffffff" }}
      >
        {value}
      </p>
      {subtitle && (
        <p className="text-[11px] mt-1" style={{ color: "#888" }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/campaign-kpis.tsx
git commit -m "feat(crm): create CampaignKpis component with dark KPI cards"
```

---

### Task 6: Create Cadence Leads Table Component

**Files:**
- Create: `crm/src/components/cadence-leads-table.tsx`

- [ ] **Step 1: Create the leads table with filters and actions**

Create `crm/src/components/cadence-leads-table.tsx`:

```typescript
"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import type { CadenceState, Lead } from "@/lib/types";
import { CADENCE_STATUS_COLORS, CADENCE_STATUS_LABELS, AGENT_STAGES } from "@/lib/constants";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

interface CadenceLeadsTableProps {
  campaignId: string;
}

type StatusFilter = "active" | "responded" | "exhausted" | "cooled" | "all";

interface CadenceRow extends CadenceState {
  leads: Lead;
}

export function CadenceLeadsTable({ campaignId }: CadenceLeadsTableProps) {
  const [rows, setRows] = useState<CadenceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("active");
  const [search, setSearch] = useState("");
  const router = useRouter();
  const supabase = createClient();

  const fetchCadenceStates = useCallback(async () => {
    const query = supabase
      .from("cadence_state")
      .select("*, leads(*)")
      .eq("campaign_id", campaignId)
      .order("created_at", { ascending: false });

    const { data } = await query;
    if (data) setRows(data as CadenceRow[]);
    setLoading(false);
  }, [campaignId]);

  useEffect(() => {
    fetchCadenceStates();

    const channel = supabase
      .channel(`cadence-${campaignId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "cadence_state", filter: `campaign_id=eq.${campaignId}` },
        () => fetchCadenceStates()
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [fetchCadenceStates, campaignId]);

  const filtered = rows.filter((r) => {
    if (filter !== "all" && r.status !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      const lead = r.leads;
      if (!lead) return false;
      return (
        (lead.name || "").toLowerCase().includes(q) ||
        (lead.company || "").toLowerCase().includes(q) ||
        lead.phone.includes(q)
      );
    }
    return true;
  });

  async function handlePause(leadId: string) {
    await fetch(`${FASTAPI_URL}/api/leads/${leadId}/cadence/pause`, { method: "POST" });
  }

  async function handleResume(leadId: string) {
    await fetch(`${FASTAPI_URL}/api/leads/${leadId}/cadence/resume`, { method: "POST" });
  }

  async function handleReset(leadId: string) {
    await fetch(`${FASTAPI_URL}/api/leads/${leadId}/cadence`, { method: "DELETE" });
  }

  async function handleHuman(leadId: string) {
    await fetch(`${FASTAPI_URL}/api/leads/${leadId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ human_control: true }),
    });
  }

  function goToConversation(phone: string) {
    router.push(`/conversas?phone=${encodeURIComponent(phone)}`);
  }

  const filters: { key: StatusFilter; label: string }[] = [
    { key: "active", label: "Leads ativos" },
    { key: "responded", label: "Responderam" },
    { key: "exhausted", label: "Esgotados" },
    { key: "cooled", label: "Esfriados" },
    { key: "all", label: "Todos" },
  ];

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-8">
        <div className="w-4 h-4 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
        <span className="text-[13px] text-[#5f6368]">Carregando leads...</span>
      </div>
    );
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex items-center gap-2 mb-4">
        {filters.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3.5 py-1.5 rounded-lg text-[12px] font-medium transition-colors ${
              filter === f.key
                ? "bg-[#1f1f1f] text-white"
                : "bg-[#f4f4f0] text-[#5f6368] hover:bg-[#e5e5dc]"
            }`}
          >
            {f.label}
          </button>
        ))}
        <div className="ml-auto">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar nome, empresa, telefone..."
            className="input-field text-[13px] w-64"
          />
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left border-b border-[#e5e5dc]">
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Lead</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Stage</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Status</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Progresso</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Proximo Envio</th>
              <th className="px-5 py-3.5 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => {
              const lead = r.leads;
              if (!lead) return null;
              const stageInfo = AGENT_STAGES.find((s) => s.key === lead.stage);
              const statusStyle = CADENCE_STATUS_COLORS[r.status];
              const progressText = `${r.total_messages_sent}/${r.max_messages}`;
              const progressPct = r.max_messages > 0 ? (r.total_messages_sent / r.max_messages) * 100 : 0;

              return (
                <tr key={r.id} className="border-b border-[#e5e5dc] last:border-0 hover:bg-[#f6f7ed]/50 transition-colors">
                  <td className="px-5 py-4">
                    <p className="font-medium text-[#1f1f1f]">{lead.name || lead.phone}</p>
                    <p className="text-[11px] text-[#9ca3af]">{lead.phone}</p>
                  </td>
                  <td className="px-5 py-4">
                    {stageInfo && (
                      <span
                        className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium ${stageInfo.color}`}
                      >
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: stageInfo.dotColor }} />
                        {stageInfo.label}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-4">
                    {statusStyle && (
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium ${statusStyle.bg} ${statusStyle.text}`}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: statusStyle.dot }} />
                        {CADENCE_STATUS_LABELS[r.status]}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-16 bg-[#e5e5dc] rounded-full h-1.5">
                        <div className="bg-[#1f1f1f] rounded-full h-1.5 transition-all" style={{ width: `${Math.min(100, progressPct)}%` }} />
                      </div>
                      <span className="text-[11px] text-[#9ca3af]">{progressText}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4 text-[12px] text-[#5f6368]">
                    {r.status === "responded"
                      ? "Com a Valeria"
                      : r.next_send_at
                        ? new Date(r.next_send_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
                        : "\u2014"}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-1.5">
                      {r.status === "active" && (
                        <button onClick={() => handlePause(lead.id)} className="text-[11px] font-medium text-[#5f6368] bg-[#f4f4f0] hover:bg-[#e5e5dc] px-2.5 py-1 rounded-md transition-colors">
                          Pausar
                        </button>
                      )}
                      {(r.status === "exhausted" || r.status === "cooled") && (
                        <button onClick={() => handleReset(lead.id)} className="text-[11px] font-medium text-[#5f6368] bg-[#f4f4f0] hover:bg-[#e5e5dc] px-2.5 py-1 rounded-md transition-colors">
                          Resetar
                        </button>
                      )}
                      <button onClick={() => goToConversation(lead.phone)} className="text-[11px] font-medium text-[#5f6368] bg-[#f4f4f0] hover:bg-[#e5e5dc] px-2.5 py-1 rounded-md transition-colors">
                        Conversa
                      </button>
                      {(r.status === "active" || r.status === "responded") && (
                        <button onClick={() => handleHuman(lead.id)} className="text-[11px] font-medium text-[#5f6368] bg-[#f4f4f0] hover:bg-[#e5e5dc] px-2.5 py-1 rounded-md transition-colors">
                          Humano
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center text-[13px] text-[#9ca3af]">
                  Nenhum lead encontrado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/cadence-leads-table.tsx
git commit -m "feat(crm): create CadenceLeadsTable with filters, search, and lead actions"
```

---

### Task 7: Create Cadence Steps Modal Component

**Files:**
- Create: `crm/src/components/cadence-steps-modal.tsx`

- [ ] **Step 1: Create the steps editing modal**

Create `crm/src/components/cadence-steps-modal.tsx`:

```typescript
"use client";

import { useState, useEffect, useCallback } from "react";
import type { CadenceStep, Campaign } from "@/lib/types";
import { AGENT_STAGES } from "@/lib/constants";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

interface CadenceStepsModalProps {
  campaign: Campaign;
  open: boolean;
  onClose: () => void;
}

export function CadenceStepsModal({ campaign, open, onClose }: CadenceStepsModalProps) {
  const [steps, setSteps] = useState<CadenceStep[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [expandedStage, setExpandedStage] = useState<string | null>(null);

  // Config state
  const [intervalHours, setIntervalHours] = useState(campaign.cadence_interval_hours || 24);
  const [startHour, setStartHour] = useState(campaign.cadence_send_start_hour || 7);
  const [endHour, setEndHour] = useState(campaign.cadence_send_end_hour || 18);
  const [cooldownHours, setCooldownHours] = useState(campaign.cadence_cooldown_hours || 48);
  const [maxMessages, setMaxMessages] = useState(campaign.cadence_max_messages || 8);

  const fetchSteps = useCallback(async () => {
    setLoading(true);
    const res = await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}/cadence`);
    if (res.ok) {
      const data = await res.json();
      setSteps(data.steps || []);
    }
    setLoading(false);
  }, [campaign.id]);

  useEffect(() => {
    if (open) fetchSteps();
  }, [open, fetchSteps]);

  const stages = AGENT_STAGES.filter((s) => s.key !== "secretaria");

  function getStageSteps(stage: string) {
    return steps
      .filter((s) => s.stage === stage)
      .sort((a, b) => a.step_order - b.step_order);
  }

  function updateStepText(stepId: string, text: string) {
    setSteps((prev) => prev.map((s) => (s.id === stepId ? { ...s, message_text: text } : s)));
  }

  function addStep(stage: string) {
    const stageSteps = getStageSteps(stage);
    const newStep: CadenceStep = {
      id: `new-${Date.now()}`,
      campaign_id: campaign.id,
      stage,
      step_order: stageSteps.length + 1,
      message_text: "",
      created_at: new Date().toISOString(),
    };
    setSteps((prev) => [...prev, newStep]);
  }

  function removeStep(stepId: string) {
    setSteps((prev) => prev.filter((s) => s.id !== stepId));
  }

  async function handleSave() {
    setSaving(true);

    // Save steps per stage
    for (const stage of stages) {
      const stageSteps = getStageSteps(stage.key);
      for (let i = 0; i < stageSteps.length; i++) {
        const step = stageSteps[i];
        const body = {
          stage: step.stage,
          step_order: i + 1,
          message_text: step.message_text,
        };

        if (step.id.startsWith("new-")) {
          await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}/cadence`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        } else {
          await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}/cadence/${step.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        }
      }
    }

    // Save campaign config
    await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cadence_interval_hours: intervalHours,
        cadence_send_start_hour: startHour,
        cadence_send_end_hour: endHour,
        cadence_cooldown_hours: cooldownHours,
        cadence_max_messages: maxMessages,
      }),
    });

    setSaving(false);
    onClose();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#ededea] flex items-center justify-between">
          <h2 className="text-[18px] font-bold text-[#1f1f1f]">Configurar Cadencia</h2>
          <button onClick={onClose} className="text-[#9ca3af] hover:text-[#1f1f1f] transition-colors">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="5" y1="5" x2="15" y2="15" />
              <line x1="15" y1="5" x2="5" y2="15" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading ? (
            <div className="flex items-center gap-3 py-8 justify-center">
              <div className="w-4 h-4 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
              <span className="text-[13px] text-[#5f6368]">Carregando...</span>
            </div>
          ) : (
            <>
              {/* Steps by stage */}
              {stages.map((stage) => {
                const stageSteps = getStageSteps(stage.key);
                const isExpanded = expandedStage === stage.key;

                return (
                  <div key={stage.key} className="mb-4">
                    <button
                      onClick={() => setExpandedStage(isExpanded ? null : stage.key)}
                      className="w-full flex items-center justify-between px-4 py-3 rounded-xl bg-[#f4f4f0] hover:bg-[#e5e5dc] transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full" style={{ background: stage.dotColor }} />
                        <span className="text-[14px] font-medium text-[#1f1f1f]">{stage.label}</span>
                        <span className="text-[12px] text-[#9ca3af]">({stageSteps.length} steps)</span>
                      </div>
                      <svg
                        width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#9ca3af" strokeWidth="2" strokeLinecap="round"
                        className={`transition-transform ${isExpanded ? "rotate-180" : ""}`}
                      >
                        <polyline points="4 6 8 10 12 6" />
                      </svg>
                    </button>

                    {isExpanded && (
                      <div className="mt-2 pl-4 space-y-3">
                        {stageSteps.map((step, idx) => (
                          <div key={step.id} className="flex gap-3 items-start">
                            <span className="text-[12px] font-medium text-[#9ca3af] mt-2.5 w-6 shrink-0">
                              #{idx + 1}
                            </span>
                            <textarea
                              value={step.message_text}
                              onChange={(e) => updateStepText(step.id, e.target.value)}
                              className="input-field flex-1 text-[13px] min-h-[60px] resize-y"
                              placeholder="Texto da mensagem..."
                            />
                            <button
                              onClick={() => removeStep(step.id)}
                              className="mt-2 text-[#f87171] hover:text-[#dc2626] transition-colors shrink-0"
                            >
                              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                                <line x1="4" y1="4" x2="12" y2="12" />
                                <line x1="12" y1="4" x2="4" y2="12" />
                              </svg>
                            </button>
                          </div>
                        ))}
                        <button
                          onClick={() => addStep(stage.key)}
                          className="text-[12px] font-medium text-[#5f6368] hover:text-[#1f1f1f] transition-colors flex items-center gap-1"
                        >
                          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                            <line x1="7" y1="3" x2="7" y2="11" />
                            <line x1="3" y1="7" x2="11" y2="7" />
                          </svg>
                          Adicionar step
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Config section */}
              <div className="mt-6 pt-6 border-t border-[#ededea]">
                <h3 className="text-[14px] font-semibold text-[#1f1f1f] mb-4">Configuracao Geral</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-1.5">
                      Intervalo entre msgs (horas)
                    </label>
                    <input
                      type="number"
                      value={intervalHours}
                      onChange={(e) => setIntervalHours(Number(e.target.value))}
                      className="input-field w-full text-[13px]"
                      min={1}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-1.5">
                      Max mensagens por lead
                    </label>
                    <input
                      type="number"
                      value={maxMessages}
                      onChange={(e) => setMaxMessages(Number(e.target.value))}
                      className="input-field w-full text-[13px]"
                      min={1}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-1.5">
                      Janela de envio (inicio)
                    </label>
                    <input
                      type="number"
                      value={startHour}
                      onChange={(e) => setStartHour(Number(e.target.value))}
                      className="input-field w-full text-[13px]"
                      min={0}
                      max={23}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-1.5">
                      Janela de envio (fim)
                    </label>
                    <input
                      type="number"
                      value={endHour}
                      onChange={(e) => setEndHour(Number(e.target.value))}
                      className="input-field w-full text-[13px]"
                      min={0}
                      max={23}
                    />
                  </div>
                  <div className="col-span-2">
                    <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-1.5">
                      Cooldown apos resposta (horas)
                    </label>
                    <input
                      type="number"
                      value={cooldownHours}
                      onChange={(e) => setCooldownHours(Number(e.target.value))}
                      className="input-field w-full text-[13px]"
                      min={1}
                    />
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#ededea] flex justify-end gap-3">
          <button onClick={onClose} className="btn-secondary px-5 py-2.5 rounded-xl text-[13px] font-medium">
            Cancelar
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn-primary px-5 py-2.5 rounded-xl text-[13px] font-medium disabled:opacity-50"
          >
            {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/cadence-steps-modal.tsx
git commit -m "feat(crm): create CadenceStepsModal with accordion stages and config editing"
```

---

### Task 8: Create Cadence Activity Component

**Files:**
- Create: `crm/src/components/cadence-activity.tsx`

- [ ] **Step 1: Create the activity timeline**

Create `crm/src/components/cadence-activity.tsx`:

```typescript
"use client";

import { useState, useEffect, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";

interface ActivityItem {
  id: string;
  type: "sent" | "responded" | "exhausted" | "cooled";
  leadName: string;
  detail: string;
  timestamp: string;
}

interface CadenceActivityProps {
  campaignId: string;
}

export function CadenceActivity({ campaignId }: CadenceActivityProps) {
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchActivity = useCallback(async () => {
    // Fetch recent cadence messages
    const { data: messages } = await supabase
      .from("messages")
      .select("id, content, created_at, sent_by, leads!inner(name, phone, campaign_id)")
      .eq("sent_by", "cadence")
      .eq("leads.campaign_id", campaignId)
      .order("created_at", { ascending: false })
      .limit(50);

    // Fetch recent cadence state changes
    const { data: states } = await supabase
      .from("cadence_state")
      .select("id, status, created_at, responded_at, leads(name, phone)")
      .eq("campaign_id", campaignId)
      .in("status", ["responded", "exhausted", "cooled"])
      .order("created_at", { ascending: false })
      .limit(50);

    const items: ActivityItem[] = [];

    if (messages) {
      for (const msg of messages) {
        const lead = msg.leads as unknown as { name: string | null; phone: string };
        items.push({
          id: `msg-${msg.id}`,
          type: "sent",
          leadName: lead?.name || lead?.phone || "Lead",
          detail: msg.content.substring(0, 80) + (msg.content.length > 80 ? "..." : ""),
          timestamp: msg.created_at,
        });
      }
    }

    if (states) {
      for (const state of states) {
        const lead = state.leads as unknown as { name: string | null; phone: string } | null;
        const name = lead?.name || lead?.phone || "Lead";
        const ts = state.status === "responded" && state.responded_at ? state.responded_at : state.created_at;

        items.push({
          id: `state-${state.id}`,
          type: state.status as "responded" | "exhausted" | "cooled",
          leadName: name,
          detail:
            state.status === "responded"
              ? "respondeu a cadencia"
              : state.status === "exhausted"
                ? "esgotou limite de mensagens"
                : "sem mais steps disponiveis",
          timestamp: ts,
        });
      }
    }

    items.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
    setActivities(items.slice(0, 50));
    setLoading(false);
  }, [campaignId]);

  useEffect(() => {
    fetchActivity();
  }, [fetchActivity]);

  const typeIcons: Record<string, { color: string; label: string }> = {
    sent: { color: "#1f1f1f", label: "Enviado" },
    responded: { color: "#4ade80", label: "Respondeu" },
    exhausted: { color: "#f87171", label: "Esgotado" },
    cooled: { color: "#9ca3af", label: "Esfriado" },
  };

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-8">
        <div className="w-4 h-4 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
        <span className="text-[13px] text-[#5f6368]">Carregando atividade...</span>
      </div>
    );
  }

  if (activities.length === 0) {
    return (
      <div className="card p-8 text-center">
        <p className="text-[13px] text-[#9ca3af]">Nenhuma atividade registrada ainda.</p>
      </div>
    );
  }

  return (
    <div className="card p-5">
      <div className="space-y-0">
        {activities.map((item, idx) => {
          const icon = typeIcons[item.type];
          const isLast = idx === activities.length - 1;

          return (
            <div key={item.id} className="flex gap-3">
              {/* Timeline dot + line */}
              <div className="flex flex-col items-center">
                <div
                  className="w-2.5 h-2.5 rounded-full mt-1.5 shrink-0"
                  style={{ background: icon.color }}
                />
                {!isLast && <div className="w-px flex-1 bg-[#ededea]" />}
              </div>

              {/* Content */}
              <div className={`pb-4 ${isLast ? "" : ""}`}>
                <p className="text-[13px] text-[#1f1f1f]">
                  <strong>{item.leadName}</strong>{" "}
                  <span className="text-[#5f6368]">{item.detail}</span>
                </p>
                <p className="text-[11px] text-[#9ca3af] mt-0.5">
                  {new Date(item.timestamp).toLocaleString("pt-BR", {
                    day: "2-digit",
                    month: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/cadence-activity.tsx
git commit -m "feat(crm): create CadenceActivity timeline component"
```

---

### Task 9: Create Campaign Detail Page

**Files:**
- Create: `crm/src/app/(authenticated)/campanhas/[id]/page.tsx`

This is the main page that assembles all components. Uses `useParams` from `next/navigation` (Next.js 16 pattern for client components).

- [ ] **Step 1: Create the detail page**

Create directory and file `crm/src/app/(authenticated)/campanhas/[id]/page.tsx`:

```typescript
"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
import { CAMPAIGN_STATUS_COLORS } from "@/lib/constants";
import { CampaignKpis } from "@/components/campaign-kpis";
import { CadenceLeadsTable } from "@/components/cadence-leads-table";
import { CadenceStepsModal } from "@/components/cadence-steps-modal";
import { CadenceActivity } from "@/components/cadence-activity";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

type Tab = "leads" | "steps" | "atividade";

export default function CampaignDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { campaigns, loading } = useRealtimeCampaigns();
  const [tab, setTab] = useState<Tab>("leads");
  const [showModal, setShowModal] = useState(false);

  const campaign = campaigns.find((c) => c.id === params.id);

  async function handleAction(action: "start" | "pause") {
    if (!campaign) return;
    await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}/${action}`, {
      method: "POST",
    });
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-12">
        <div className="w-5 h-5 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
        <p className="text-[#5f6368] text-[14px]">Carregando...</p>
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="py-12 text-center">
        <p className="text-[14px] text-[#5f6368] mb-4">Campanha nao encontrada.</p>
        <Link href="/campanhas" className="text-[13px] font-medium text-[#1f1f1f] hover:underline">
          &larr; Voltar para campanhas
        </Link>
      </div>
    );
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "leads", label: "Leads em Cadencia" },
    { key: "steps", label: "Steps de Cadencia" },
    { key: "atividade", label: "Atividade" },
  ];

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <Link href="/campanhas" className="text-[13px] text-[#5f6368] hover:text-[#1f1f1f] transition-colors mb-3 inline-block">
          &larr; Campanhas
        </Link>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-[28px] font-bold text-[#1f1f1f]">{campaign.name}</h1>
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium ${
                CAMPAIGN_STATUS_COLORS[campaign.status] || ""
              }`}
            >
              {campaign.status}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowModal(true)}
              className="btn-secondary px-4 py-2 rounded-xl text-[13px] font-medium"
            >
              Configurar Cadencia
            </button>
            {(campaign.status === "draft" || campaign.status === "paused") && (
              <button
                onClick={() => handleAction("start")}
                className="btn-primary px-4 py-2 rounded-xl text-[13px] font-medium"
              >
                Iniciar
              </button>
            )}
            {campaign.status === "running" && (
              <button
                onClick={() => handleAction("pause")}
                className="btn-secondary px-4 py-2 rounded-xl text-[13px] font-medium"
              >
                Pausar
              </button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-4 mt-2 text-[12px] text-[#5f6368]">
          <span>Template: <strong className="text-[#1f1f1f]">{campaign.template_name}</strong></span>
          <span>Criada em: {new Date(campaign.created_at).toLocaleDateString("pt-BR")}</span>
          <span>Total: <strong className="text-[#1f1f1f]">{campaign.total_leads}</strong> leads</span>
        </div>
      </div>

      {/* KPIs */}
      <div className="mb-6">
        <CampaignKpis campaign={campaign} />
      </div>

      {/* Config Summary Bar */}
      <div className="card p-4 mb-6">
        <div className="flex items-center gap-6 text-[12px] text-[#5f6368]">
          <span>Intervalo: <strong className="text-[#1f1f1f]">{campaign.cadence_interval_hours || 24}h</strong></span>
          <span>Janela: <strong className="text-[#1f1f1f]">{campaign.cadence_send_start_hour || 7}h–{campaign.cadence_send_end_hour || 18}h</strong></span>
          <span>Cooldown: <strong className="text-[#1f1f1f]">{campaign.cadence_cooldown_hours || 48}h</strong></span>
          <span>Max msgs: <strong className="text-[#1f1f1f]">{campaign.cadence_max_messages || 8}</strong></span>
          <span>Follow-ups enviados: <strong className="text-[#1f1f1f]">{campaign.cadence_sent || 0}</strong></span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 border-b border-[#ededea]">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2.5 text-[13px] font-medium transition-colors relative ${
              tab === t.key
                ? "text-[#1f1f1f]"
                : "text-[#9ca3af] hover:text-[#5f6368]"
            }`}
          >
            {t.label}
            {tab === t.key && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#1f1f1f] rounded-full" />
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === "leads" && <CadenceLeadsTable campaignId={campaign.id} />}
      {tab === "steps" && (
        <div>
          <div className="card p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[14px] font-semibold text-[#1f1f1f]">Steps de Cadencia por Stage</h3>
              <button
                onClick={() => setShowModal(true)}
                className="btn-secondary px-4 py-1.5 rounded-lg text-[12px] font-medium"
              >
                Editar Steps
              </button>
            </div>
            <p className="text-[13px] text-[#5f6368]">
              Clique em &ldquo;Editar Steps&rdquo; ou &ldquo;Configurar Cadencia&rdquo; para gerenciar as mensagens de follow-up.
            </p>
          </div>
        </div>
      )}
      {tab === "atividade" && <CadenceActivity campaignId={campaign.id} />}

      {/* Modal */}
      <CadenceStepsModal
        campaign={campaign}
        open={showModal}
        onClose={() => setShowModal(false)}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify build compiles**

Run: `cd crm && npx next build --no-lint 2>&1 | tail -15`
Expected: Build succeeds with the new route `/campanhas/[id]`.

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/(authenticated)/campanhas/[id]/page.tsx
git commit -m "feat(crm): create campaign detail page with KPIs, tabs, leads table, and activity"
```

---

### Task 10: Final Integration Verification

**Files:**
- None (verification only)

- [ ] **Step 1: Full build check**

Run: `cd crm && npx next build --no-lint 2>&1 | tail -20`
Expected: Build succeeds with all routes including `/campanhas/[id]`.

- [ ] **Step 2: Verify route structure**

Run: `ls -la crm/src/app/\(authenticated\)/campanhas/`
Expected: Shows `page.tsx` and `[id]/` directory with `page.tsx` inside.

- [ ] **Step 3: Final commit with all changes if any leftover**

Only if there are uncommitted changes:
```bash
git add -A crm/src/
git commit -m "chore(crm): final cleanup for campaign detail page feature"
```

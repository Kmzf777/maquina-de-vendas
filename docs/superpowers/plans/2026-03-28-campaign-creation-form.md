# Campaign Creation Form — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inline campaign creation form with a modal wizard that supports lead selection from CRM (with filters) and CSV import, plus campaign type and instance selection.

**Architecture:** Modal wizard component with 2 steps. Backend gets a new migration, assign-leads endpoint, and updated CampaignCreate model. Frontend uses Supabase client for lead/tag queries (same pattern as QualificacaoPage).

**Tech Stack:** Next.js 16.2.1 (App Router, "use client"), React 19, Tailwind CSS 4, FastAPI, Supabase, design system from globals.css.

**IMPORTANT — Next.js 16:** `useRouter` and `useParams` from `next/navigation`. All pages are `"use client"`.

---

### Task 1: SQL Migration + Backend Endpoint

**Files:**
- Create: `backend-evolution/migrations/004_campaign_type.sql`
- Modify: `backend-evolution/app/campaign/router.py`

- [ ] **Step 1: Create migration file**

Create `backend-evolution/migrations/004_campaign_type.sql`:

```sql
-- Add campaign type and instance fields
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS type text NOT NULL DEFAULT 'bot';
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS instance_name text;
```

- [ ] **Step 2: Add assign-leads endpoint and update CampaignCreate**

In `backend-evolution/app/campaign/router.py`, add `type` and `instance_name` to `CampaignCreate`:

```python
class CampaignCreate(BaseModel):
    name: str
    template_name: str
    template_params: dict | None = None
    type: str = "bot"
    instance_name: str | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8
    cadence_interval_hours: int = 24
    cadence_send_start_hour: int = 7
    cadence_send_end_hour: int = 18
    cadence_cooldown_hours: int = 48
    cadence_max_messages: int = 8
```

Add the assign-leads endpoint at the bottom of the file (before any `if __name__`):

```python
class AssignLeadsRequest(BaseModel):
    lead_ids: list[str]


@router.post("/{campaign_id}/assign-leads")
async def assign_leads(campaign_id: str, req: AssignLeadsRequest):
    sb = get_supabase()

    # Verify campaign exists
    campaign = sb.table("campaigns").select("id").eq("id", campaign_id).single().execute().data
    if not campaign:
        raise HTTPException(404, "Campanha nao encontrada")

    assigned = 0
    skipped = 0

    for lead_id in req.lead_ids:
        # Check if lead is already in a running campaign
        lead = sb.table("leads").select("id, campaign_id").eq("id", lead_id).single().execute().data
        if not lead:
            skipped += 1
            continue

        if lead.get("campaign_id"):
            # Check if that campaign is running
            existing = (
                sb.table("campaigns")
                .select("status")
                .eq("id", lead["campaign_id"])
                .single()
                .execute()
                .data
            )
            if existing and existing["status"] == "running":
                skipped += 1
                continue

        # Assign lead to this campaign
        sb.table("leads").update({
            "campaign_id": campaign_id,
            "status": "imported",
        }).eq("id", lead_id).execute()
        assigned += 1

    # Update total_leads
    total = sb.table("leads").select("id", count="exact").eq("campaign_id", campaign_id).execute().count
    sb.table("campaigns").update({"total_leads": total or 0}).eq("id", campaign_id).execute()

    return {"assigned": assigned, "skipped": skipped}
```

- [ ] **Step 3: Commit**

```bash
git add backend-evolution/migrations/004_campaign_type.sql backend-evolution/app/campaign/router.py
git commit -m "feat(backend): add campaign type/instance fields and assign-leads endpoint"
```

---

### Task 2: Update TypeScript Types

**Files:**
- Modify: `crm/src/lib/types.ts`

- [ ] **Step 1: Add type and instance_name to Campaign interface**

In `crm/src/lib/types.ts`, add two fields to the Campaign interface after `cadence_cooled`:

```typescript
  // Campaign type
  type: "bot" | "seller";
  instance_name: string | null;
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/lib/types.ts
git commit -m "feat(crm): add type and instance_name to Campaign type"
```

---

### Task 3: Create LeadSelector Component

**Files:**
- Create: `crm/src/components/lead-selector.tsx`

- [ ] **Step 1: Create the lead selector with filters and checkboxes**

Create `crm/src/components/lead-selector.tsx`:

```typescript
"use client";

import { useState, useEffect, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import { AGENT_STAGES, SELLER_STAGES } from "@/lib/constants";
import type { Lead, Tag } from "@/lib/types";

interface LeadSelectorProps {
  selectedIds: Set<string>;
  onSelectionChange: (ids: Set<string>) => void;
}

export function LeadSelector({ selectedIds, onSelectionChange }: LeadSelectorProps) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, Tag[]>>({});
  const [loading, setLoading] = useState(true);

  // Filters
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState<string[]>([]);
  const [sellerStageFilter, setSellerStageFilter] = useState<string[]>([]);
  const [tagFilter, setTagFilter] = useState<string[]>([]);

  const supabase = createClient();

  useEffect(() => {
    async function load() {
      const [leadsRes, tagsRes, ltRes] = await Promise.all([
        supabase.from("leads").select("*").order("created_at", { ascending: false }),
        supabase.from("tags").select("*"),
        supabase.from("lead_tags").select("lead_id, tag_id"),
      ]);

      if (leadsRes.data) setLeads(leadsRes.data);
      if (tagsRes.data) setTags(tagsRes.data);

      if (tagsRes.data && ltRes.data) {
        const map: Record<string, Tag[]> = {};
        ltRes.data.forEach((row: { lead_id: string; tag_id: string }) => {
          const tag = tagsRes.data!.find((t: Tag) => t.id === row.tag_id);
          if (tag) {
            if (!map[row.lead_id]) map[row.lead_id] = [];
            map[row.lead_id].push(tag);
          }
        });
        setLeadTagsMap(map);
      }

      setLoading(false);
    }
    load();
  }, []);

  const filtered = useMemo(() => {
    return leads.filter((l) => {
      if (stageFilter.length > 0 && !stageFilter.includes(l.stage)) return false;
      if (sellerStageFilter.length > 0 && !sellerStageFilter.includes(l.seller_stage)) return false;
      if (tagFilter.length > 0) {
        const lt = leadTagsMap[l.id] || [];
        if (!tagFilter.some((tid) => lt.some((t) => t.id === tid))) return false;
      }
      if (search) {
        const q = search.toLowerCase();
        return (
          (l.name || "").toLowerCase().includes(q) ||
          (l.company || "").toLowerCase().includes(q) ||
          (l.nome_fantasia || "").toLowerCase().includes(q) ||
          l.phone.includes(q)
        );
      }
      return true;
    });
  }, [leads, stageFilter, sellerStageFilter, tagFilter, search, leadTagsMap]);

  function toggleAll() {
    if (filtered.every((l) => selectedIds.has(l.id))) {
      const next = new Set(selectedIds);
      filtered.forEach((l) => next.delete(l.id));
      onSelectionChange(next);
    } else {
      const next = new Set(selectedIds);
      filtered.forEach((l) => next.add(l.id));
      onSelectionChange(next);
    }
  }

  function toggleOne(id: string) {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectionChange(next);
  }

  const allSelected = filtered.length > 0 && filtered.every((l) => selectedIds.has(l.id));

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-8 justify-center">
        <div className="w-4 h-4 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
        <span className="text-[13px] text-[#5f6368]">Carregando leads...</span>
      </div>
    );
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <MultiSelect
          label="Stage"
          options={AGENT_STAGES.map((s) => ({ value: s.key, label: s.label }))}
          selected={stageFilter}
          onChange={setStageFilter}
        />
        <MultiSelect
          label="Funil Vendedor"
          options={SELLER_STAGES.map((s) => ({ value: s.key, label: s.label }))}
          selected={sellerStageFilter}
          onChange={setSellerStageFilter}
        />
        <MultiSelect
          label="Tags"
          options={tags.map((t) => ({ value: t.id, label: t.name }))}
          selected={tagFilter}
          onChange={setTagFilter}
        />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar nome, telefone, empresa..."
          className="input-field text-[13px] w-52 ml-auto"
        />
      </div>

      {/* Table */}
      <div className="border border-[#ededea] rounded-xl overflow-hidden max-h-[340px] overflow-y-auto">
        <table className="w-full text-[13px]">
          <thead className="sticky top-0 bg-white z-10">
            <tr className="text-left border-b border-[#e5e5dc]">
              <th className="px-4 py-3 w-10">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  className="accent-[#1f1f1f]"
                />
              </th>
              <th className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Nome</th>
              <th className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Telefone</th>
              <th className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Stage</th>
              <th className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Vendedor</th>
              <th className="px-4 py-3 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">Tags</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((l) => {
              const stageInfo = AGENT_STAGES.find((s) => s.key === l.stage);
              const sellerInfo = SELLER_STAGES.find((s) => s.key === l.seller_stage);
              const lt = leadTagsMap[l.id] || [];

              return (
                <tr
                  key={l.id}
                  className="border-b border-[#ededea] last:border-0 hover:bg-[#f6f7ed]/50 transition-colors cursor-pointer"
                  onClick={() => toggleOne(l.id)}
                >
                  <td className="px-4 py-2.5">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(l.id)}
                      onChange={() => toggleOne(l.id)}
                      className="accent-[#1f1f1f]"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td className="px-4 py-2.5 text-[#1f1f1f] font-medium">{l.name || l.phone}</td>
                  <td className="px-4 py-2.5 text-[#5f6368]">{l.phone}</td>
                  <td className="px-4 py-2.5">
                    {stageInfo && (
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${stageInfo.color}`}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: stageInfo.dotColor }} />
                        {stageInfo.label}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    {sellerInfo && (
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${sellerInfo.color}`}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: sellerInfo.dotColor }} />
                        {sellerInfo.label}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex gap-1 flex-wrap">
                      {lt.slice(0, 3).map((tag) => (
                        <span
                          key={tag.id}
                          className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                          style={{ backgroundColor: tag.color + "20", color: tag.color }}
                        >
                          {tag.name}
                        </span>
                      ))}
                      {lt.length > 3 && (
                        <span className="text-[10px] text-[#9ca3af]">+{lt.length - 3}</span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-[13px] text-[#9ca3af]">
                  Nenhum lead encontrado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Counter */}
      <div className="mt-3 text-[12px] text-[#5f6368]">
        {selectedIds.size} lead{selectedIds.size !== 1 ? "s" : ""} selecionado{selectedIds.size !== 1 ? "s" : ""}
        {filtered.length > 0 && ` de ${filtered.length} filtrados`}
      </div>
    </div>
  );
}

/* Simple multi-select dropdown */
function MultiSelect({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);

  function toggle(value: string) {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors flex items-center gap-1.5 ${
          selected.length > 0
            ? "bg-[#1f1f1f] text-white"
            : "bg-[#f4f4f0] text-[#5f6368] hover:bg-[#e5e5dc]"
        }`}
      >
        {label}
        {selected.length > 0 && (
          <span className="bg-white/20 text-[10px] px-1.5 py-0.5 rounded-full">{selected.length}</span>
        )}
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <polyline points="3 5 6 8 9 5" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 mt-1 bg-white border border-[#ededea] rounded-xl shadow-lg z-50 min-w-[180px] py-1 max-h-[200px] overflow-y-auto">
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => toggle(opt.value)}
                className="w-full text-left px-3 py-2 text-[12px] hover:bg-[#f6f7ed] flex items-center gap-2 transition-colors"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  readOnly
                  className="accent-[#1f1f1f]"
                />
                {opt.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/lead-selector.tsx
git commit -m "feat(crm): create LeadSelector component with multi-filters and checkboxes"
```

---

### Task 4: Create Campaign Modal Component

**Files:**
- Create: `crm/src/components/create-campaign-modal.tsx`

- [ ] **Step 1: Create the wizard modal**

Create `crm/src/components/create-campaign-modal.tsx`:

```typescript
"use client";

import { useState, useRef } from "react";
import { LeadSelector } from "@/components/lead-selector";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

interface CreateCampaignModalProps {
  open: boolean;
  onClose: () => void;
}

interface InstanceInfo {
  connected: boolean;
  number?: string;
}

export function CreateCampaignModal({ open, onClose }: CreateCampaignModalProps) {
  const [step, setStep] = useState(1);

  // Step 1 fields
  const [type, setType] = useState<"bot" | "seller">("bot");
  const [name, setName] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [intervalMin, setIntervalMin] = useState(3);
  const [intervalMax, setIntervalMax] = useState(8);
  const [instance, setInstance] = useState<InstanceInfo | null>(null);
  const [instanceLoading, setInstanceLoading] = useState(false);

  // Step 2 fields
  const [leadTab, setLeadTab] = useState<"crm" | "csv">("crm");
  const [selectedLeadIds, setSelectedLeadIds] = useState<Set<string>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<{ valid: number; invalid: number; invalidNumbers: string[] } | null>(null);

  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch instance status when modal opens
  useState(() => {
    if (open) {
      setInstanceLoading(true);
      fetch("/api/evolution/status")
        .then((r) => r.json())
        .then((data) => {
          setInstance(data);
          setInstanceLoading(false);
        })
        .catch(() => {
          setInstance({ connected: false });
          setInstanceLoading(false);
        });
    }
  });

  function resetForm() {
    setStep(1);
    setType("bot");
    setName("");
    setTemplateName("");
    setIntervalMin(3);
    setIntervalMax(8);
    setSelectedLeadIds(new Set());
    setCsvFile(null);
    setCsvPreview(null);
    setError(null);
    setLeadTab("crm");
  }

  function handleClose() {
    resetForm();
    onClose();
  }

  const canProceed = name.trim() && templateName.trim() && instance?.connected;
  const canCreate = leadTab === "crm" ? selectedLeadIds.size > 0 : csvFile !== null;

  async function handleCreate() {
    setCreating(true);
    setError(null);

    try {
      // 1. Create campaign
      const res = await fetch(`${FASTAPI_URL}/api/campaigns`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          template_name: templateName,
          type,
          instance_name: instance?.number || null,
          send_interval_min: intervalMin,
          send_interval_max: intervalMax,
        }),
      });

      if (!res.ok) {
        setError("Erro ao criar campanha");
        setCreating(false);
        return;
      }

      const campaign = await res.json();

      // 2. Assign leads or import CSV
      if (leadTab === "crm" && selectedLeadIds.size > 0) {
        const assignRes = await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}/assign-leads`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lead_ids: Array.from(selectedLeadIds) }),
        });

        if (!assignRes.ok) {
          setError("Campanha criada, mas erro ao vincular leads");
        }
      } else if (leadTab === "csv" && csvFile) {
        const formData = new FormData();
        formData.append("file", csvFile);
        const importRes = await fetch(`${FASTAPI_URL}/api/campaigns/${campaign.id}/import`, {
          method: "POST",
          body: formData,
        });

        if (!importRes.ok) {
          setError("Campanha criada, mas erro ao importar CSV");
        }
      }

      handleClose();
    } catch {
      setError("Erro de conexao");
    }

    setCreating(false);
  }

  function handleCsvSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvFile(file);

    // Preview: parse client-side for quick feedback
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      const lines = text.split("\n").filter((l) => l.trim());
      // Rough count: skip header, count lines with digits
      const dataLines = lines.slice(1);
      const phoneRegex = /\d{10,}/;
      let valid = 0;
      let invalid = 0;
      const invalidNumbers: string[] = [];
      dataLines.forEach((line) => {
        const firstCol = line.split(",")[0]?.trim().replace(/["\s]/g, "");
        if (firstCol && phoneRegex.test(firstCol)) {
          valid++;
        } else if (firstCol) {
          invalid++;
          if (invalidNumbers.length < 20) invalidNumbers.push(firstCol);
        }
      });
      setCsvPreview({ valid, invalid, invalidNumbers });
    };
    reader.readAsText(file);
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={handleClose} />

      <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#ededea] flex items-center justify-between">
          <h2 className="text-[18px] font-bold text-[#1f1f1f]">Nova Campanha</h2>
          <button onClick={handleClose} className="text-[#9ca3af] hover:text-[#1f1f1f] transition-colors">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="5" y1="5" x2="15" y2="15" />
              <line x1="15" y1="5" x2="5" y2="15" />
            </svg>
          </button>
        </div>

        {/* Step indicator */}
        <div className="px-6 py-3 border-b border-[#ededea] flex items-center gap-3">
          <StepDot active={step === 1} done={step > 1} label="1. Configuracao" />
          <div className="w-8 h-px bg-[#ededea]" />
          <StepDot active={step === 2} done={false} label="2. Leads" />
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {step === 1 && (
            <div className="space-y-5">
              {/* Type selection */}
              <div>
                <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
                  Tipo de campanha
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <TypeCard
                    selected={type === "bot"}
                    onClick={() => setType("bot")}
                    icon={<BotIcon />}
                    title="Bot (ValerIA)"
                    desc="Agente IA envia e responde"
                  />
                  <TypeCard
                    selected={type === "seller"}
                    onClick={() => setType("seller")}
                    icon={<PersonIcon />}
                    title="Vendedor"
                    desc="Cadencia automatica de vendas"
                  />
                </div>
              </div>

              {/* Instance */}
              <div>
                <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
                  Instancia WhatsApp
                </label>
                {instanceLoading ? (
                  <div className="flex items-center gap-2 py-2">
                    <div className="w-3 h-3 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
                    <span className="text-[13px] text-[#5f6368]">Verificando...</span>
                  </div>
                ) : instance?.connected ? (
                  <div className="flex items-center gap-2 px-4 py-3 rounded-xl border-2 border-[#c8cc8e] bg-[#f2f3eb]">
                    <span className="w-2 h-2 bg-green-500 rounded-full" />
                    <span className="text-[13px] font-medium text-[#1f1f1f]">
                      Conectado {instance.number ? `(${instance.number})` : ""}
                    </span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 px-4 py-3 rounded-xl border border-[#e5e5dc] bg-[#f4f4f0]">
                    <span className="w-2 h-2 bg-[#9ca3af] rounded-full" />
                    <span className="text-[13px] text-[#9ca3af]">Nenhuma instancia conectada</span>
                  </div>
                )}
              </div>

              {/* Name + Template */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
                    Nome da campanha
                  </label>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="input-field w-full"
                    placeholder="Ex: Campanha Atacado Março"
                    required
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
                    Template
                  </label>
                  <input
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                    className="input-field w-full"
                    placeholder="Nome do template"
                    required
                  />
                </div>
              </div>

              {/* Intervals */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
                    Intervalo min (s)
                  </label>
                  <input
                    type="number"
                    value={intervalMin}
                    onChange={(e) => setIntervalMin(Number(e.target.value))}
                    className="input-field w-full"
                    min={1}
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5f6368] mb-2">
                    Intervalo max (s)
                  </label>
                  <input
                    type="number"
                    value={intervalMax}
                    onChange={(e) => setIntervalMax(Number(e.target.value))}
                    className="input-field w-full"
                    min={1}
                  />
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div>
              {/* Tabs */}
              <div className="flex items-center gap-1 mb-5 border-b border-[#ededea]">
                <button
                  onClick={() => setLeadTab("crm")}
                  className={`px-4 py-2.5 text-[13px] font-medium transition-colors relative ${
                    leadTab === "crm" ? "text-[#1f1f1f]" : "text-[#9ca3af] hover:text-[#5f6368]"
                  }`}
                >
                  Selecionar do CRM
                  {leadTab === "crm" && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#1f1f1f] rounded-full" />}
                </button>
                <button
                  onClick={() => setLeadTab("csv")}
                  className={`px-4 py-2.5 text-[13px] font-medium transition-colors relative ${
                    leadTab === "csv" ? "text-[#1f1f1f]" : "text-[#9ca3af] hover:text-[#5f6368]"
                  }`}
                >
                  Importar CSV
                  {leadTab === "csv" && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#1f1f1f] rounded-full" />}
                </button>
              </div>

              {leadTab === "crm" && (
                <LeadSelector
                  selectedIds={selectedLeadIds}
                  onSelectionChange={setSelectedLeadIds}
                />
              )}

              {leadTab === "csv" && (
                <div>
                  <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-[#e5e5dc] rounded-xl cursor-pointer hover:border-[#c8cc8e] hover:bg-[#f6f7ed]/50 transition-colors">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                    <span className="text-[13px] text-[#9ca3af] mt-2">
                      {csvFile ? csvFile.name : "Clique para selecionar um arquivo CSV"}
                    </span>
                    <input
                      ref={fileRef}
                      type="file"
                      accept=".csv"
                      className="hidden"
                      onChange={handleCsvSelect}
                    />
                  </label>

                  {csvPreview && (
                    <div className="mt-4 p-4 rounded-xl bg-[#f4f4f0]">
                      <p className="text-[13px] text-[#1f1f1f]">
                        <strong className="text-green-600">{csvPreview.valid}</strong> numeros validos
                        {csvPreview.invalid > 0 && (
                          <>, <strong className="text-red-500">{csvPreview.invalid}</strong> invalidos</>
                        )}
                      </p>
                      {csvPreview.invalidNumbers.length > 0 && (
                        <div className="mt-2">
                          <p className="text-[11px] text-[#9ca3af] mb-1">Numeros invalidos:</p>
                          <div className="flex flex-wrap gap-1">
                            {csvPreview.invalidNumbers.map((n, i) => (
                              <span key={i} className="px-2 py-0.5 bg-red-50 text-red-600 rounded text-[11px]">{n}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {error && (
            <p className="text-red-500 text-[13px] mt-4">{error}</p>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#ededea] flex items-center justify-between">
          <div>
            {step === 2 && (
              <button
                onClick={() => setStep(1)}
                className="btn-secondary px-4 py-2 rounded-xl text-[13px] font-medium"
              >
                &larr; Voltar
              </button>
            )}
          </div>
          <div className="flex gap-3">
            <button onClick={handleClose} className="btn-secondary px-5 py-2.5 rounded-xl text-[13px] font-medium">
              Cancelar
            </button>
            {step === 1 && (
              <button
                onClick={() => setStep(2)}
                disabled={!canProceed}
                className="btn-primary px-5 py-2.5 rounded-xl text-[13px] font-medium disabled:opacity-50"
              >
                Proximo &rarr;
              </button>
            )}
            {step === 2 && (
              <button
                onClick={handleCreate}
                disabled={creating || !canCreate}
                className="btn-primary px-5 py-2.5 rounded-xl text-[13px] font-medium disabled:opacity-50"
              >
                {creating ? "Criando..." : "Criar Campanha"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StepDot({ active, done, label }: { active: boolean; done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold ${
          active
            ? "bg-[#1f1f1f] text-white"
            : done
              ? "bg-[#c8cc8e] text-[#1f1f1f]"
              : "bg-[#ededea] text-[#9ca3af]"
        }`}
      >
        {done ? "\u2713" : label.charAt(0)}
      </div>
      <span className={`text-[12px] font-medium ${active ? "text-[#1f1f1f]" : "text-[#9ca3af]"}`}>
        {label}
      </span>
    </div>
  );
}

function TypeCard({
  selected,
  onClick,
  icon,
  title,
  desc,
}: {
  selected: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`p-4 rounded-xl border-2 text-left transition-all ${
        selected
          ? "border-[#c8cc8e] bg-[#f2f3eb]"
          : "border-[#ededea] bg-white hover:border-[#e5e5dc]"
      }`}
    >
      <div className="mb-2">{icon}</div>
      <p className="text-[14px] font-semibold text-[#1f1f1f]">{title}</p>
      <p className="text-[12px] text-[#5f6368]">{desc}</p>
    </button>
  );
}

function BotIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1f1f1f" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <line x1="12" y1="7" x2="12" y2="11" />
      <circle cx="8" cy="16" r="1" fill="#1f1f1f" />
      <circle cx="16" cy="16" r="1" fill="#1f1f1f" />
    </svg>
  );
}

function PersonIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1f1f1f" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4" />
      <path d="M20 21a8 8 0 0 0-16 0" />
    </svg>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/create-campaign-modal.tsx
git commit -m "feat(crm): create CreateCampaignModal wizard with type, instance, and lead selection"
```

---

### Task 5: Update Campaign List Page

**Files:**
- Modify: `crm/src/app/(authenticated)/campanhas/page.tsx`

- [ ] **Step 1: Replace inline form with modal**

Replace the entire contents of `crm/src/app/(authenticated)/campanhas/page.tsx`:

```typescript
"use client";

import { useState } from "react";
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
import { CampaignCard } from "@/components/campaign-card";
import { CreateCampaignModal } from "@/components/create-campaign-modal";

export default function CampanhasPage() {
  const { campaigns, loading } = useRealtimeCampaigns();
  const [showModal, setShowModal] = useState(false);

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
          onClick={() => setShowModal(true)}
          className="btn-primary flex items-center gap-2 px-5 py-2.5 rounded-xl text-[13px] font-medium"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="8" y1="3" x2="8" y2="13" />
            <line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          Nova Campanha
        </button>
      </div>

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

      <CreateCampaignModal
        open={showModal}
        onClose={() => setShowModal(false)}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd crm && NEXT_LINT_DURING_BUILD=false npx next build 2>&1 | tail -20`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/(authenticated)/campanhas/page.tsx
git commit -m "feat(crm): replace inline form with CreateCampaignModal wizard"
```

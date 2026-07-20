# Leads Search & Sale Registration Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Any task touching the frontend MUST use shadcn/ui components and invoke the `frontend-design` skill before writing UI code.

**Goal:** Fix three seller-facing gaps: (1) Leads-tab search missing leads by name/company/phone, (2) no way to register a sale from the lead detail modal, (3) no searchable lead selector when registering a new sale.

**Architecture:** All frontend-only. Introduce one shared, pure search helper (`lib/search.ts`) reused by the Leads tab and the sale lead-selector. Paginate the leads fetch to defeat the PostgREST 1000-row cap. Add a shadcn `Popover` primitive (over the already-installed `radix-ui` metapackage) to build a lightweight searchable Combobox — no new npm dependency. Reuse the existing `SaleCreateModal` to add sale registration to the lead detail modal.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, Supabase JS, shadcn/ui over `radix-ui`, Vitest.

---

## File Structure

- **Create** `frontend/src/lib/search.ts` — `foldText()` + `leadMatchesSearch()`. Pure, unit-tested.
- **Create** `frontend/src/lib/search.test.ts` — Vitest unit tests for the helper.
- **Create** `frontend/src/components/ui/popover.tsx` — shadcn Popover over `radix-ui`.
- **Modify** `frontend/src/hooks/use-realtime-leads.ts` — paginate fetch (load all rows).
- **Modify** `frontend/src/app/(authenticated)/leads/page.tsx` — use `leadMatchesSearch` in the filter.
- **Modify** `frontend/src/components/sales/sale-create-modal.tsx` — replace lead `<Select>` with searchable Combobox.
- **Modify** `frontend/src/components/leads/lead-detail-modal.tsx` — add "Registrar Venda" button + wire `SaleCreateModal`.

**Dependency order:** Task 1 (helper) → then Tasks 2/3/4 in parallel (no shared files). Task 3 and Task 4 both live in the sales area but modify *different* files (`sale-create-modal.tsx` vs `lead-detail-modal.tsx`); Task 4 relies only on `SaleCreateModal`'s existing public props, which Task 3 does not change.

---

### Task 1: Shared lead-search helper (TDD)

**Files:**
- Create: `frontend/src/lib/search.ts`
- Test: `frontend/src/lib/search.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/search.test.ts
import { describe, it, expect } from "vitest";
import { foldText, leadMatchesSearch } from "./search";

describe("foldText", () => {
  it("strips diacritics and lowercases", () => {
    expect(foldText("José Açaí")).toBe("jose acai");
    expect(foldText("CAÇAPAVA")).toBe("cacapava");
  });
});

describe("leadMatchesSearch", () => {
  const lead = {
    name: "José da Silva",
    phone: "5534999998888",
    company: "Café Canastra",
    razao_social: "Canastra Comércio LTDA",
    nome_fantasia: "Canastra Grãos",
  };

  it("returns true for empty query", () => {
    expect(leadMatchesSearch("", lead)).toBe(true);
    expect(leadMatchesSearch("   ", lead)).toBe(true);
  });

  it("matches name without accents", () => {
    expect(leadMatchesSearch("jose", lead)).toBe(true);
    expect(leadMatchesSearch("SILVA", lead)).toBe(true);
  });

  it("matches company and razao_social and nome_fantasia accent-insensitively", () => {
    expect(leadMatchesSearch("cafe", lead)).toBe(true);
    expect(leadMatchesSearch("comercio", lead)).toBe(true);
    expect(leadMatchesSearch("graos", lead)).toBe(true);
  });

  it("matches phone typed with formatting", () => {
    expect(leadMatchesSearch("(34) 99999-8888", lead)).toBe(true);
    expect(leadMatchesSearch("3499999", lead)).toBe(true);
  });

  it("returns false when nothing matches", () => {
    expect(leadMatchesSearch("zzz", lead)).toBe(false);
  });

  it("tolerates null fields", () => {
    expect(leadMatchesSearch("x", { name: null, phone: null })).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/search.test.ts`
Expected: FAIL — `foldText`/`leadMatchesSearch` not exported.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/lib/search.ts

/** Lowercases and strips diacritics (á→a, ç→c, ã→a) for accent-insensitive matching. */
export function foldText(value: string): string {
  return value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export interface LeadSearchFields {
  name?: string | null;
  phone?: string | null;
  company?: string | null;
  razao_social?: string | null;
  nome_fantasia?: string | null;
}

/**
 * True when `query` matches the lead by name/company/razao_social/nome_fantasia
 * (accent-insensitive substring) OR by phone (digit-substring, so formatted input
 * like "(34) 99999-8888" matches the stored 13-digit "5534999998888").
 * Empty/whitespace query matches everything.
 */
export function leadMatchesSearch(query: string, lead: LeadSearchFields): boolean {
  const raw = query.trim();
  if (!raw) return true;

  const q = foldText(raw);
  const textMatch = [lead.name, lead.company, lead.razao_social, lead.nome_fantasia].some(
    (field) => field != null && foldText(field).includes(q)
  );
  if (textMatch) return true;

  const qDigits = raw.replace(/\D/g, "");
  if (qDigits && lead.phone && lead.phone.replace(/\D/g, "").includes(qDigits)) return true;

  return false;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/search.test.ts`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/search.ts frontend/src/lib/search.test.ts
git commit -m "feat(leads): shared accent/phone-aware lead search helper"
```

---

### Task 2: Demand 1 — load all leads + accent/phone-aware Leads-tab search

**Files:**
- Modify: `frontend/src/hooks/use-realtime-leads.ts:12-22`
- Modify: `frontend/src/app/(authenticated)/leads/page.tsx:53-60`

- [ ] **Step 1: Paginate the leads fetch (defeat the 1000-row cap)**

Replace the body of `fetchLeads` in `use-realtime-leads.ts` (lines 12-22) with a ranged loop:

```ts
  const fetchLeads = useCallback(async () => {
    const pageSize = 1000;
    const all: Lead[] = [];
    for (let from = 0; ; from += pageSize) {
      let query = supabase
        .from("leads")
        .select("*")
        .order("last_msg_at", { ascending: false, nullsFirst: false })
        .range(from, from + pageSize - 1);

      if (filter?.human_control !== undefined) {
        query = query.eq("human_control", filter.human_control);
      }

      const { data, error } = await query;
      if (error || !data) break;
      all.push(...data);
      if (data.length < pageSize) break;
    }
    setLeads(all);
    setLoading(false);
  }, [filter?.human_control]);
```

- [ ] **Step 2: Use the shared helper in the Leads filter**

In `leads/page.tsx`, add the import near the other `@/lib` imports:

```ts
import { leadMatchesSearch } from "@/lib/search";
```

Replace the `if (filters.search) { ... }` block (lines 53-60) with:

```ts
      if (filters.search && !leadMatchesSearch(filters.search, lead)) return false;
```

- [ ] **Step 3: Verify build/lint/types**

Run: `cd frontend && npm run lint && npm run type-check`
Expected: no new errors. (`Lead` type includes `nome_fantasia`/`razao_social`; `leadMatchesSearch` accepts the lead directly.)

- [ ] **Step 4: Manual smoke (document, don't block)**

Note in the commit body: search by unaccented name, by nome_fantasia, and by formatted phone now match; leads beyond the first 1000 load.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/use-realtime-leads.ts "frontend/src/app/(authenticated)/leads/page.tsx"
git commit -m "fix(leads): load all leads and search accent/phone-insensitively"
```

---

### Task 3: Demand 3 — searchable lead Combobox in the new-sale form

**Files:**
- Create: `frontend/src/components/ui/popover.tsx`
- Modify: `frontend/src/components/sales/sale-create-modal.tsx:259-284`

> Invoke the `frontend-design` skill before writing the Combobox UI. Match the existing `SelectTrigger` styling at line 272 for visual parity.

- [ ] **Step 1: Add the shadcn Popover primitive (over `radix-ui`)**

```tsx
// frontend/src/components/ui/popover.tsx
"use client"

import * as React from "react"
import { Popover as PopoverPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

function Popover({ ...props }: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({ ...props }: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverContent({
  className,
  align = "start",
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "z-50 w-(--radix-popover-trigger-width) rounded-lg bg-popover p-0 text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}

export { Popover, PopoverTrigger, PopoverContent }
```

- [ ] **Step 2: Replace the lead `<Select>` block with a searchable Combobox**

In `sale-create-modal.tsx`, add imports (near the existing `@/components/ui/*` imports):

```ts
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { leadMatchesSearch } from "@/lib/search";
import { ChevronDownIcon, CheckIcon } from "lucide-react";
```

Add combobox state near the other `useState` hooks in the component:

```ts
const [leadPickerOpen, setLeadPickerOpen] = useState(false);
const [leadQuery, setLeadQuery] = useState("");
```

Replace the whole lead-selector block (lines 259-284, the `{pickLead && !isEditing && ( ... )}`) with:

```tsx
          {/* Lead selector — searchable combobox, only in pickLead mode and not editing */}
          {pickLead && !isEditing && (
            <div>
              <label className={fieldLabel}>Lead *</label>
              <Popover open={leadPickerOpen} onOpenChange={setLeadPickerOpen}>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    className="flex w-full h-[37px] items-center justify-between bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                  >
                    <span className={resolvedLeadId ? "" : "text-[#8a8a8a]"}>
                      {resolvedLeadId
                        ? (leads.find((l) => l.id === resolvedLeadId)?.name ??
                           leads.find((l) => l.id === resolvedLeadId)?.phone ??
                           "Lead selecionado")
                        : "Selecione o lead"}
                    </span>
                    <ChevronDownIcon className="size-4 text-[#8a8a8a]" />
                  </button>
                </PopoverTrigger>
                <PopoverContent className="p-0">
                  <div className="p-2 border-b border-[#eee]">
                    <Input
                      autoFocus
                      value={leadQuery}
                      onChange={(e) => setLeadQuery(e.target.value)}
                      placeholder="Buscar lead por nome ou telefone..."
                      className="h-8 text-[14px]"
                    />
                  </div>
                  <div className="max-h-64 overflow-y-auto p-1">
                    {leads.filter((l) => leadMatchesSearch(leadQuery, l)).length === 0 && (
                      <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">Nenhum lead encontrado.</div>
                    )}
                    {leads
                      .filter((l) => leadMatchesSearch(leadQuery, l))
                      .slice(0, 100)
                      .map((l) => (
                        <button
                          key={l.id}
                          type="button"
                          onClick={() => {
                            setSelectedLeadId(l.id);
                            setDealId("");
                            setCreatingDeal(false);
                            setNewDealTitle("");
                            setNewDealPipeline("");
                            setLeadPickerOpen(false);
                            setLeadQuery("");
                          }}
                          className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[14px] hover:bg-[#f4f2ee]"
                        >
                          <span className="truncate">{l.name ?? l.phone}</span>
                          {resolvedLeadId === l.id && <CheckIcon className="size-4 shrink-0" />}
                        </button>
                      ))}
                  </div>
                </PopoverContent>
              </Popover>
            </div>
          )}
```

Note: `leads` here is `LeadOption[]` (`{ id, name, phone }`); `leadMatchesSearch` tolerates the missing `company`/`razao_social`/`nome_fantasia` fields (they're optional). The `.slice(0, 100)` caps render cost while typing narrows results.

- [ ] **Step 3: Verify build/lint/types**

Run: `cd frontend && npm run lint && npm run type-check`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/popover.tsx frontend/src/components/sales/sale-create-modal.tsx
git commit -m "feat(sales): searchable lead combobox in new-sale form"
```

---

### Task 4: Demand 2 — "Registrar Venda" from the lead detail modal

**Files:**
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx` (imports, deals-fetch refactor, header/Oportunidades button, nested modal)

> Invoke the `frontend-design` skill. Match the modal's existing green sale styling (`bg-[#1f9d57] hover:bg-[#1b8a4c]`, used at line ~469).

- [ ] **Step 1: Import `SaleCreateModal` and add state**

Add near the top imports:

```ts
import { SaleCreateModal } from "@/components/sales/sale-create-modal";
```

Add near the component's `useState` hooks:

```ts
const [showCreateSale, setShowCreateSale] = useState(false);
```

- [ ] **Step 2: Make the deals fetch reusable**

The deals fetch currently lives in a `useEffect` (lines ~95-107). Extract its body into a `useCallback` named `fetchLeadDeals` and call it from the effect, so `onSaved` can refresh the list. Example shape (adapt to the actual query already present):

```ts
const fetchLeadDeals = useCallback(async () => {
  if (!lead?.id) return;
  const supabase = createClient();
  const { data } = await supabase
    .from("deals")
    .select("*")            // keep the exact select currently used
    .eq("lead_id", lead.id);
  if (data) setLeadDeals(data);
}, [lead?.id]);

useEffect(() => { fetchLeadDeals(); }, [fetchLeadDeals]);
```

- [ ] **Step 3: Add the "Registrar Venda" button**

Place a green button in the "Oportunidades" section header (Dados tab, lines ~370-373) — where deal context already lives:

```tsx
<button
  type="button"
  onClick={() => setShowCreateSale(true)}
  className="inline-flex items-center gap-1.5 rounded-md bg-[#1f9d57] px-3 py-1.5 text-[13px] font-medium text-white hover:bg-[#1b8a4c]"
>
  Registrar Venda
</button>
```

- [ ] **Step 4: Render the nested `SaleCreateModal`**

Before the component's outer closing tag (near line ~618), add:

```tsx
{showCreateSale && (
  <SaleCreateModal
    leadId={lead.id}
    onClose={() => setShowCreateSale(false)}
    onSaved={() => {
      setShowCreateSale(false);
      fetchLeadDeals();
    }}
  />
)}
```

- [ ] **Step 5: Guard against outside-click bubbling**

`LeadDetailModal`'s root has `onClick={onClose}` (line ~186). `SaleCreateModal` renders its own Radix `Dialog` (portaled), so clicks inside it should not bubble to the lead modal root. Verify by adding `e.stopPropagation()` to the lead modal's inner content container if the sale dialog interaction accidentally closes the lead modal. (Precedent that this composition works: `contact-detail.tsx:277-286`.)

- [ ] **Step 6: Verify build/lint/types**

Run: `cd frontend && npm run lint && npm run type-check`
Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/leads/lead-detail-modal.tsx
git commit -m "feat(leads): register sale from lead detail modal"
```

---

### Task 5: Full verification

- [ ] **Step 1: Run the full frontend test/lint/type suite**

Run: `cd frontend && npm run test && npm run lint && npm run type-check`
Expected: all green.

- [ ] **Step 2: Report results**

Summarize pass/fail per command with actual output. Do NOT claim success without the output.

---

## Self-Review (spec coverage)

- **Demand 1** → Task 1 (helper) + Task 2 (pagination + filter). Covers name/company/razao_social/nome_fantasia accent-insensitive + phone digit match + >1000 leads. ✅
- **Demand 2** → Task 4 (button + `SaleCreateModal`, deals refresh). No backend change. ✅
- **Demand 3** → Task 1 (helper reuse) + Task 3 (Popover + Combobox). No new dependency, no backend change. ✅
- **Acceptance criteria 4** (tests/lint/types green) → Task 5. ✅
- Type consistency: helper exports `foldText`/`leadMatchesSearch`/`LeadSearchFields`, used identically in Tasks 2 and 3. `SaleCreateModal` props (`leadId`, `onClose`, `onSaved`) used in Task 4 match its existing interface. ✅
- No backend/migration/env changes — pure frontend. ✅

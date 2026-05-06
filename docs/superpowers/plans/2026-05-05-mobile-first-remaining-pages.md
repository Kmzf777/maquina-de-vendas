# Mobile-First: Dashboard, Leads, Qualificação Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **MANDATORY:** Every agent touching frontend MUST invoke the `frontend-design` skill before writing any JSX, CSS, or Tailwind classes.

**Goal:** Optimize Dashboard, Leads, and Qualificação pages for mobile at the `md:` (768px) breakpoint, consistent with the already-shipped Conversas/Vendas mobile patterns.

**Architecture:** Progressive enhancement — each page gets responsive grids, responsive page header padding, and where needed new mobile-only UI (Leads bottom-sheet modal). No new shared abstractions.

**Tech Stack:** Next.js 14 App Router, Tailwind v4, React — working directory `/home/rafael/maquinadevendas/frontend`

**Design system:** `DESIGN.md` at project root — warm canvas `#faf9f6`, borders `#dedbd6`, accent `#ff5600`, `rounded-[4px]` buttons, no shadows.

---

## Task 1: Dashboard — responsive header, KPI grid, chart grid, LeadSourcesChart

**Files:**
- Modify: `frontend/src/app/(authenticated)/dashboard/page.tsx`
- Modify: `frontend/src/components/dashboard/lead-sources-chart.tsx`

- [ ] **Step 1: Invoke frontend-design skill**
  Run `frontend-design` skill before touching any code.

- [ ] **Step 2: Fix page header padding**
  In `dashboard/page.tsx`, find the page header div:
  ```tsx
  // Before
  className="border-b border-[#dedbd6] bg-white px-8 py-5 flex items-center justify-between flex-shrink-0"
  // After
  className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-3 md:py-5 flex items-center justify-between flex-shrink-0"
  ```

- [ ] **Step 3: Fix KPI grid (3-col → 2-col on mobile)**
  In `dashboard/page.tsx`, find the KPI cards grid:
  ```tsx
  // Before
  className="grid grid-cols-3 gap-5"
  // After
  className="grid grid-cols-2 md:grid-cols-3 gap-4 md:gap-5"
  ```

- [ ] **Step 4: Fix charts grid (2-col → 1-col on mobile)**
  In `dashboard/page.tsx`, find the charts grid:
  ```tsx
  // Before
  className="grid grid-cols-2 gap-5"
  // After
  className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-5"
  ```

- [ ] **Step 5: Fix LeadSourcesChart responsive layout**
  In `lead-sources-chart.tsx`, find the inner flex container that holds the SVG pie chart and the legend. Change it to stack vertically on mobile:
  ```tsx
  // Before
  className="flex items-center gap-6"
  // After
  className="flex flex-col md:flex-row items-center gap-4 md:gap-6"
  ```

- [ ] **Step 6: Commit**
  ```bash
  git add frontend/src/app/\(authenticated\)/dashboard/page.tsx \
          frontend/src/components/dashboard/lead-sources-chart.tsx
  git commit -m "feat(mobile): responsive dashboard — header, KPI grid, chart grid"
  ```

---

## Task 2: Leads — responsive grids + mobile bottom-sheet modal

**Files:**
- Modify: `frontend/src/app/(authenticated)/leads/page.tsx`

- [ ] **Step 1: Invoke frontend-design skill**
  Run `frontend-design` skill before touching any code.

- [ ] **Step 2: Read the full leads/page.tsx**
  Read `frontend/src/app/(authenticated)/leads/page.tsx` in full to understand the current lead card structure, KPI bar, and any existing state before making changes.

- [ ] **Step 3: Fix page header padding**
  In `leads/page.tsx`, find the page header div (contains title "Leads"):
  ```tsx
  // Before
  className="border-b border-[#dedbd6] bg-white px-8 py-5 flex items-center justify-between flex-shrink-0"
  // After
  className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-3 md:py-5 flex items-center justify-between flex-shrink-0"
  ```

- [ ] **Step 4: Fix KPI bar grid (4-col → 2-col on mobile)**
  In `leads/page.tsx`, find the KPI bar grid:
  ```tsx
  // Before
  className="grid grid-cols-4 gap-4"
  // After
  className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4"
  ```

- [ ] **Step 5: Fix lead cards grid (3-col → 1-col on mobile)**
  In `leads/page.tsx`, find the lead cards grid:
  ```tsx
  // Before
  className="grid grid-cols-3 gap-4"
  // After
  className="grid grid-cols-1 md:grid-cols-3 gap-3 md:gap-4"
  ```

- [ ] **Step 6: Add mobile bottom-sheet modal state**
  At the top of the `LeadsPage` component, add state for the selected lead:
  ```tsx
  const [mobileSelectedLead, setMobileSelectedLead] = useState<Lead | null>(null);
  ```

- [ ] **Step 7: Make lead cards tappable on mobile**
  Wrap each lead card (or add onClick to it) so that on mobile it opens the bottom sheet. Add an `onClick` to the card element:
  ```tsx
  onClick={() => setMobileSelectedLead(lead)}
  className="... cursor-pointer"
  ```
  The onClick should only trigger the modal; on desktop the card already has its own behaviour — keep existing desktop click handlers intact.

- [ ] **Step 8: Add bottom-sheet modal JSX**
  At the end of the return statement (before the closing `</div>`), add the mobile bottom-sheet:
  ```tsx
  {/* Mobile lead detail bottom sheet */}
  {mobileSelectedLead && (
    <div
      className="md:hidden fixed inset-0 z-50 flex flex-col justify-end"
      onClick={() => setMobileSelectedLead(null)}
    >
      <div className="absolute inset-0 bg-black/40" />
      <div
        className="relative bg-white rounded-t-[12px] border-t border-[#dedbd6] max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 rounded-full bg-[#dedbd6]" />
        </div>
        {/* Header */}
        <div className="px-5 pt-2 pb-4 flex items-center justify-between border-b border-[#dedbd6]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-[#8a8a80] flex items-center justify-center text-white font-medium">
              {(mobileSelectedLead.name || mobileSelectedLead.phone || "?").charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-[15px] font-medium text-[#111111]">
                {mobileSelectedLead.name || mobileSelectedLead.phone}
              </p>
              <p className="text-[12px] text-[#7b7b78]">{mobileSelectedLead.phone}</p>
            </div>
          </div>
          <button
            onClick={() => setMobileSelectedLead(null)}
            className="w-8 h-8 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        {/* Details */}
        <div className="px-5 py-4 space-y-3">
          {mobileSelectedLead.stage && (
            <div className="flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Stage</span>
              <span className="text-[13px] text-[#111111]">{mobileSelectedLead.stage}</span>
            </div>
          )}
          {mobileSelectedLead.company && (
            <div className="flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Empresa</span>
              <span className="text-[13px] text-[#111111]">{mobileSelectedLead.company}</span>
            </div>
          )}
          {mobileSelectedLead.email && (
            <div className="flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Email</span>
              <span className="text-[13px] text-[#111111]">{mobileSelectedLead.email}</span>
            </div>
          )}
          {mobileSelectedLead.channel && (
            <div className="flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Canal</span>
              <span className="text-[13px] text-[#111111]">{mobileSelectedLead.channel}</span>
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">AI</span>
            <span className={`text-[12px] px-2 py-0.5 rounded-[4px] ${mobileSelectedLead.ai_enabled ? "bg-[#ff5600]/10 text-[#ff5600]" : "bg-[#dedbd6]/60 text-[#7b7b78]"}`}>
              {mobileSelectedLead.ai_enabled ? "Ativa" : "Pausada"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Criado em</span>
            <span className="text-[13px] text-[#111111]">
              {new Date(mobileSelectedLead.created_at).toLocaleDateString("pt-BR")}
            </span>
          </div>
        </div>
      </div>
    </div>
  )}
  ```

- [ ] **Step 9: Commit**
  ```bash
  git add frontend/src/app/\(authenticated\)/leads/page.tsx
  git commit -m "feat(mobile): responsive leads page — grids + bottom-sheet lead modal"
  ```

---

## Task 3: Qualificação — responsive header + touch-scroll kanban

**Files:**
- Modify: `frontend/src/app/(authenticated)/qualificacao/page.tsx`

- [ ] **Step 1: Invoke frontend-design skill**
  Run `frontend-design` skill before touching any code.

- [ ] **Step 2: Read qualificacao/page.tsx**
  Read the full file to understand the kanban container structure and locate the exact div that wraps the columns.

- [ ] **Step 3: Fix page header padding**
  In `qualificacao/page.tsx`, find the page header div (contains title "Visão Agent AI"):
  ```tsx
  // Before
  className="border-b border-[#dedbd6] bg-white px-8 py-5 ..."
  // After
  className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-3 md:py-5 ..."
  ```

- [ ] **Step 4: Add touch-scroll to kanban container**
  Find the flex container that holds the kanban columns (the one with `flex gap-3` or similar wrapping the column components). Add `overflow-x-auto touch-pan-x`:
  ```tsx
  // Before
  className="flex gap-3 p-4 md:p-6 ..."
  // After
  className="flex gap-3 overflow-x-auto touch-pan-x p-4 md:p-6 ..."
  ```
  If the container already has `overflow-auto` or `overflow-x-auto`, ensure `touch-pan-x` is added.

- [ ] **Step 5: Commit**
  ```bash
  git add frontend/src/app/\(authenticated\)/qualificacao/page.tsx
  git commit -m "feat(mobile): responsive qualificacao — header padding + touch-scroll kanban"
  ```

---

## Task 4: Push to master and deploy

- [ ] **Step 1: Push all commits**
  ```bash
  git push origin master
  ```

- [ ] **Step 2: Verify GitHub Actions**
  Confirm the frontend deploy job runs successfully at https://github.com/Kmzf777/maquina-de-vendas/actions

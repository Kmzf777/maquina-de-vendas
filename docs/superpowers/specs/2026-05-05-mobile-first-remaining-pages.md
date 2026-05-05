# Spec: Mobile-First — Dashboard, Leads, Qualificação

**Date:** 2026-05-05
**Scope:** Three pages — Dashboard, Leads, Qualificação
**Breakpoint:** `md:` (768px) — below is mobile, above is desktop
**Design system:** Intercom-inspired (DESIGN.md) — warm canvas `#faf9f6`, borders `#dedbd6`, accent `#ff5600`

---

## 1. Dashboard

### Current issues
- Page header: `px-8 py-5` — no mobile padding
- KPI grid: `grid-cols-3` — 3 cards per row too narrow on mobile
- Chart grid: `grid-cols-2` — two charts side-by-side too small on mobile
- `lead-sources-chart.tsx`: fixed SVG `width={180} height={180}` + `flex items-center gap-6` breaks on narrow screens

### Mobile behaviour
- **Header:** `px-4 md:px-8 py-3 md:py-5`
- **KPI cards:** `grid-cols-2 md:grid-cols-3` — 2 per row on mobile
- **Charts:** `grid-cols-1 md:grid-cols-2` — stacked vertically on mobile
- **LeadSourcesChart:** wrap SVG + legend in `flex-col md:flex-row`; SVG keeps `180×180` (fits mobile width)

### Desktop: unchanged

---

## 2. Leads

### Current issues
- Page header: `px-8 py-5` — no mobile padding
- KPI bar: `grid-cols-4` — 4 KPIs too tight on mobile
- Lead cards: `grid-cols-3` — 3 cards per row too narrow on mobile
- No mobile detail view — user wants modal on card tap

### Mobile behaviour
- **Header:** `px-4 md:px-8 py-3 md:py-5`
- **KPI bar:** `grid-cols-2 md:grid-cols-4`
- **Lead cards:** `grid-cols-1 md:grid-cols-3` — full-width cards on mobile
- **Lead card tap:** opens a bottom-sheet modal (`fixed inset-x-0 bottom-0 z-50`) with lead details:
  - Name, phone, stage badge, company, channel, created date, AI status
  - Close button at top-right; backdrop tap closes
  - Max height `max-h-[80vh]` with `overflow-y-auto`
  - Follows design system: `bg-white rounded-t-[12px] border-t border-[#dedbd6]`
- **Desktop:** cards stay as-is, no modal (detail already visible or navigable)

### Lead card (mobile-optimised)
Each card on mobile: full-width, avatar + name + stage pill + phone + last activity. Tap opens modal.

---

## 3. Qualificação

### Current issues
- Page header: `px-8 py-5` — no mobile padding
- Kanban container: no `overflow-x-auto` or `touch-pan-x`
- Kanban columns: `w-72 flex-shrink-0` — correct for horizontal scroll but container doesn't allow it

### Mobile behaviour
- **Header:** `px-4 md:px-8 py-3 md:py-5`
- **Kanban container:** add `overflow-x-auto touch-pan-x` (identical pattern to `/vendas`)
- **Columns:** keep `w-72 flex-shrink-0` — horizontal touch-scroll handles navigation

### Desktop: unchanged

---

## 4. Cross-cutting

- All page headers currently use `px-8 py-5` with no mobile variant — fix all three
- No new components needed for Dashboard or Qualificação
- Only Leads requires a new UI element (bottom-sheet modal)
- All agents must invoke `frontend-design` skill before writing any UI code

---

## 5. Out of scope

- Campanhas — left as-is
- Config — already uses `max-w-3xl`, adapts naturally
- Conversas / Vendas — already done

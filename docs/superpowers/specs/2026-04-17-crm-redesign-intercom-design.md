# CRM Frontend Redesign — Intercom Design System

**Date:** 2026-04-17  
**Branch:** feat/crm-redesign-intercom  
**Status:** Approved

## Overview

Full frontend redesign of the ValerIA CRM applying the Intercom-inspired design system defined in `/DESIGN.md`. The current dark-themed, olive-accented UI is replaced with a warm, editorial, light interface — warm cream canvas, off-black typography, Fin Orange accent, sharp 4px button geometry, and Geist font replacing DM Sans.

## Design System

### Tokens

| Token | Value | Use |
|-------|-------|-----|
| `--color-off-black` | `#111111` | Primary text, button bg |
| `--color-fin` | `#ff5600` | AI/brand accent only |
| `--color-warm-cream` | `#faf9f6` | Canvas, cards, sidebar |
| `--color-oat-border` | `#dedbd6` | All borders |
| `--color-muted` | `#7b7b78` | Secondary text, labels |
| `--color-black-80` | `#313130` | Dark neutral |
| `--color-black-60` | `#626260` | Mid neutral |
| `--color-white` | `#ffffff` | Surface (modal backgrounds) |

### Typography

- **Font**: Geist (Next.js native, replaces DM Sans)
- **Headings**: `font-weight: 400`, `line-height: 1.00`, negative `letter-spacing`
  - 80px → `-2.4px` | 54px → `-1.6px` | 40px → `-1.2px` | 32px → `-0.96px` | 24px → `-0.48px`
- **Body**: 16px, `line-height: 1.5`, normal spacing
- **Labels**: 12px uppercase, `letter-spacing: 0.6px–1.2px`, color `#7b7b78`

### Components

**Buttons**
- Primary: `bg-[#111111] text-white rounded-[4px] px-[14px]`, hover `scale(1.1)` + white bg, active `scale(0.85)` + `#2c6415`
- Outlined: transparent, `border border-[#111111]`, same hover/active
- No `rounded-xl`, no `rounded-2xl`, no olive/yellow backgrounds

**Cards**
- `bg-[#faf9f6] border border-[#dedbd6] rounded-[8px]`
- No box-shadows — depth through warm borders only

**Navigation / Sidebar**
- Background: `#faf9f6` (warm cream, NOT dark)
- Active item: `bg-[#111111] text-white rounded-[6px]`
- Inactive: `text-[#111111]`, hover `bg-[#dedbd6]/40`
- Logo accent: Fin Orange dot `#ff5600`

### Layout
- Spacing scale: 8, 10, 12, 14, 16, 20, 24, 32, 40, 48, 60, 64, 80, 96px
- Border radius: 4px buttons · 6px nav items · 8px cards/containers
- No shadows anywhere

## Execution Plan

### Phase 1 — Foundation (sequential, blocks Phase 2)

**Agent: Foundation**
- Replace font from DM Sans → Geist in `layout.tsx`
- Rewrite `globals.css`: new CSS variables, remove dark theme vars, remove olive/yellow, update card/button base classes
- Rewrite `sidebar.tsx`: warm cream background, off-black text, 6px radius nav items, Fin Orange accent

### Phase 2 — Pages (5 agents in parallel after Phase 1)

All agents MUST invoke the `frontend-design` skill before writing any code.

| Agent | Files |
|-------|-------|
| Dashboard | `dashboard/page.tsx`, `kpi-card.tsx`, `funnel-chart.tsx`, `dashboard/lead-sources-chart.tsx`, `dashboard/funnel-movement.tsx` |
| Leads | `leads/page.tsx`, `lead-card.tsx`, `leads/lead-grid-card.tsx`, `leads/lead-detail-modal.tsx`, `leads/lead-create-modal.tsx`, `leads/lead-import-modal.tsx`, `leads/leads-filter-bar.tsx`, `lead-detail-sidebar.tsx`, `quick-add-lead.tsx`, `lead-selector.tsx` |
| Conversas | `conversas/page.tsx`, `conversas/chat-list.tsx`, `conversas/chat-view.tsx`, `conversas/contact-detail.tsx`, `conversas/editable-field.tsx`, `chat-panel.tsx`, `chat-active.tsx` |
| Funis (Kanban) | `vendas/page.tsx`, `kanban-column.tsx`, `kanban-filters.tsx`, `kanban-metrics-bar.tsx`, `deals/deal-card.tsx`, `deals/deal-kanban-filters.tsx`, `deals/deal-create-modal.tsx`, `deals/deal-detail-sidebar.tsx`, `deals/deal-kanban-metrics.tsx`, `deals/lost-reason-modal.tsx` |
| Resto | `campanhas/page.tsx`, `campanhas/[id]/page.tsx`, todos os `campaigns/` components, `estatisticas/page.tsx`, `canais/page.tsx`, `qualificacao/page.tsx`, `config/page.tsx`, todos os `config/` components, `login/page.tsx` |

## Constraints

- Fin Orange (`#ff5600`) ONLY for AI/brand accent — never decorative
- No cool-gray borders (`#e5e7eb`, `#d1d5db`) — always warm oat `#dedbd6`
- No `rounded-xl`/`rounded-2xl` on buttons — always `rounded-[4px]`
- No box-shadows
- Geist font throughout
- All agents use `frontend-design` skill

## Success Criteria

- All pages render on warm cream canvas `#faf9f6`
- Sidebar is light (warm cream), not dark
- All buttons have 4px radius with scale hover
- No olive/yellow/dark variables remain in use
- Typography uses Geist with negative tracking on headings
- No TypeScript errors

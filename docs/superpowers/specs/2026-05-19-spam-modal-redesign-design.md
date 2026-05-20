# Spam Modal Redesign — Design Spec

**Date:** 2026-05-19  
**Status:** Approved

---

## Context

When a user clicks "Iniciar" or "Retomar" on a broadcast, the system runs a spam-check that detects leads who received a dispatch within the last 48 hours. Currently the modal has only one action: "Remover e Disparar" (removes all conflicting leads and starts the broadcast). The redesign adds granular selection and three distinct actions.

---

## Requirements

1. The user can select individual leads (one by one) or multiple leads via checkboxes.
2. The user can **remove selected leads** from the broadcast (permanently deleted from `broadcast_leads`). Action only executes after clicking the "Remover selecionados" button.
3. The user can **create a new draft broadcast with selected leads** (same settings as original, selected leads moved out of current broadcast into the new draft, then current broadcast starts).
4. The user can **dispatch anyway** (ignore spam warning, start broadcast with all leads including conflicting ones).
5. All selection-based actions require ≥1 lead selected to be enabled.

---

## Modal Layout

```
┌─────────────────────────────────────────────────────────┐
│ Leads disparados recentemente                           │
│ N lead(s) receberam disparo nas últimas 48h.            │
├─────────────────────────────────────────────────────────┤
│ [Contextual toolbar — visible only when ≥1 selected]    │
│ X selecionado(s)  [Remover selecionados] [Criar novo disparo] │
├─────────────────────────────────────────────────────────┤
│ ☑ │ NOME        │ TELEFONE      │ ÚLTIMO DISPARO │ EM  │
│───┼─────────────┼───────────────┼────────────────┼─────│
│ ☑ │ Rafael      │ 5534988861441 │ teste-warning  │ ... │
│ ☑ │ Maria       │ 5511999990000 │ outro-disparo  │ ... │
├─────────────────────────────────────────────────────────┤
│                    [Cancelar] [Disparar mesmo assim]    │
└─────────────────────────────────────────────────────────┘
```

### Header
- Title: "Leads disparados recentemente"
- Subtitle: "{N} lead(s) abaixo receberam um disparo nas últimas 48h."

### Contextual Toolbar (between header and table)
- Visible only when ≥1 lead is selected
- Shows count: "{X} selecionado(s)"
- Button: **"Remover selecionados"** — outlined/destructive style (border red or neutral)
- Button: **"Criar novo disparo com selecionados"** — primary dark style
- Both buttons show loading state during their action

### Table
- Header row: master checkbox (selects/deselects all) + "NOME" + "TELEFONE" + "ÚLTIMO DISPARO" + "ENVIADO EM"
- All rows pre-checked when modal opens
- Row: checkbox + name (or "—") + phone + last broadcast name (truncated) + sent_at formatted as "DD/MM, HH:mm"
- Row hover: subtle background highlight

### Footer
- Left: nothing
- Right: **"Cancelar"** (outlined, closes modal, no action) | **"Disparar mesmo assim"** (outlined dark, starts broadcast ignoring conflicts)

---

## Actions

### 1. Remover selecionados
- Calls `POST /api/broadcasts/[id]/remove-leads` with `{ lead_ids: string[] }` (selected IDs)
- API deletes those `broadcast_leads` rows and recalculates `total_leads` on the broadcast
- After success: calls `POST /api/broadcasts/[id]/start`
- Closes modal, updates broadcast status to "running" in local state
- Shows no alert (inline feedback via status change is sufficient)

### 2. Criar novo disparo com selecionados
- Calls existing `POST /api/broadcasts/[id]/resolve-spam` with `{ conflict_lead_ids: string[] }` (selected IDs)
- API creates new draft broadcast with same settings, moves selected leads to it, recalculates `total_leads`
- After success: calls `POST /api/broadcasts/[id]/start`
- Closes modal, updates broadcast status to "running"
- Shows `alert()` with: "{N} lead(s) movidos para o rascunho "{name}""

### 3. Disparar mesmo assim
- Calls `POST /api/broadcasts/[id]/start` directly
- Closes modal, updates broadcast status to "running"
- No confirmation needed (user explicitly chose to ignore the warning)

### 4. Cancelar
- Closes modal, resets selection, does not start broadcast

---

## New API Route

### `POST /api/broadcasts/[id]/remove-leads`

**Body:** `{ lead_ids: string[] }`

**Logic:**
1. Validate `lead_ids` non-empty
2. `DELETE FROM broadcast_leads WHERE broadcast_id = id AND lead_id IN (lead_ids)`
3. `SELECT count(*) FROM broadcast_leads WHERE broadcast_id = id` → recount
4. `UPDATE broadcasts SET total_leads = count WHERE id = id`
5. Return `{ removed_count: number, new_total: number }`

**Error handling:**
- 400 if `lead_ids` is empty
- 404 if broadcast not found
- 500 with message on DB error

---

## State Changes in `broadcast-detail.tsx`

New state:
```typescript
const [selectedConflictIds, setSelectedConflictIds] = useState<Set<string>>(new Set());
const [modalActionLoading, setModalActionLoading] = useState(false);
```

Remove: `confirmLoading` (replaced by `modalActionLoading`)

Selection logic:
- On modal open: pre-select all — `new Set(spamConflicts.map(c => c.lead_id))`
- "Select all" checkbox: checked when `selectedConflictIds.size === spamConflicts.length`; indeterminate when partial
- Row checkbox toggle: adds/removes from set
- On modal close: reset `selectedConflictIds` to empty set

---

## Files Affected

| File | Action |
|------|--------|
| `frontend/src/components/campaigns/broadcast-detail.tsx` | Modify — modal redesign + new state |
| `frontend/src/app/api/broadcasts/[id]/remove-leads/route.ts` | Create — new API route |

---

## Out of Scope

- Modifying `resolve-spam` route (already correct)
- Changing spam-check logic (already fixed)
- Any changes to the broadcast list page (`broadcast-list.tsx`)

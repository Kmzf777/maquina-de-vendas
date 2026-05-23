# Templates Sync — Design Spec
**Date:** 2026-05-23  
**Status:** Approved (v2 — revised after review)

## Problem

Three bugs in the `/campanhas` → Templates tab:

1. **Language filter:** Only `pt_BR` templates appear. Root cause: the local `message_templates` table only holds templates created via this app (all defaulting to `pt_BR`). Templates from Meta Business Manager in other languages are never imported.

2. **Stale status:** Status stays `"pending"` forever. The 30s polling in `TemplatesTab` queries the local Supabase table, which is never updated when Meta approves/rejects a template.

3. **Stale category:** Same root cause as status — set at creation time, never synced back from Meta.

**Common root cause:** No mechanism exists to sync the Meta API's template list back into the local `message_templates` table.

---

## Architecture

```
TemplatesTab (mount) ──→ POST /api/templates/sync?channel_id={id}  ─┐
                         (per channel, sequential)                   │
Sync button ─────────→ POST /api/templates/sync?channel_id={id}  ─┘
                                │
                         GET Meta Graph API (paginated)
                                │
                         Upsert → message_templates (channel_id, name, language)
                         Mark missing → status: 'cancelled'
                                │
               GET /api/templates ──→ Supabase (read, no changes)
```

---

## Solution

### 1. Database Migration

Add a unique constraint on `(channel_id, name, language)` in `message_templates`.

```sql
ALTER TABLE message_templates
  ADD CONSTRAINT message_templates_channel_name_lang_key
  UNIQUE (channel_id, name, language);
```

This replaces any prior `(channel_id, name)` unique constraint if one exists.  
**Rationale:** Meta uniquely identifies templates by `(waba_id, name, language)`. A template named `order_update` in `pt_BR` and `en_US` are two distinct resources in Meta — they must be two distinct rows in our DB.

---

### 2. New API route: `POST /api/templates/sync`

**File:** `frontend/src/app/api/templates/sync/route.ts`

**Request:** `POST /api/templates/sync?channel_id={uuid}`

`channel_id` is **required**. The UI calls this endpoint once per active `meta_cloud` channel, sequentially.

**Logic per channel:**
1. Load the channel from Supabase (verify it is `meta_cloud` and `is_active`)
2. Extract `waba_id`, `access_token`, `api_version` from `provider_config`
3. **Paginated fetch loop** from Meta Graph API:
   ```
   GET https://graph.facebook.com/{version}/{waba_id}/message_templates
     ?fields=name,status,language,category,components
     &limit=200
   ```
   Follow `paging.next` until no next page. Accumulate all templates.  
   If any page fails: throw — do not proceed to upsert or deletion for this channel.
4. **Upsert** all fetched templates into `message_templates` with `onConflict: 'channel_id,name,language'`, updating:
   - `status` (Meta's APPROVED/REJECTED/PENDING → lowercased)
   - `category` (lowercased)
   - `language`
   - `components` (keeps broadcast rendering up to date)
   - `meta_template_id`
5. **Ghost cleanup:** Collect the `id` (Meta's template ID) of every fetched template. Query `message_templates` for this channel where `meta_template_id NOT IN (fetched ids)` and update their `status` to `'cancelled'`. Only runs if all pages were fetched successfully.
6. Return `{ synced: number }` for this channel.

**Error handling:**
- If the channel is not found or not `meta_cloud`: return `400`
- If any Meta API page fails: return `502`, abort upsert and ghost cleanup for this channel
- The UI handles per-channel errors gracefully (shows which channels failed)

---

### 3. Modified component: `TemplatesTab`

**File:** `frontend/src/components/campaigns/templates-tab.tsx`

**State changes:**
- Remove the 30s polling interval (was querying local DB which never updates status)
- Add `syncing: boolean` state
- Add `syncToast: { type: 'success' | 'error'; message: string } | null` state

**Auto-sync on mount:**
- On component mount, fetch the list of active `meta_cloud` channels from `/api/channels`, then call `POST /api/templates/sync?channel_id={id}` for each, sequentially
- After all channels synced (success or not), call `loadTemplates()` to refresh the table
- This replaces the broken 30s polling

**Manual sync button:**
- "↻ Sincronizar" button, disabled while `syncing === true`
- SVG icon with `animate-spin` class during loading
- Calls the same sequential sync logic as mount
- Shows success toast ("Templates sincronizados") or error toast on completion

**Toast:**
- Same inline HTML pattern as `quickSendToast` in `page.tsx`
- `bg-[#111111] text-white` for success, `bg-[#c41c1c] text-white` for error
- Auto-dismisses after 5 seconds

**Badge upgrades:**
- Replace inline `<span>` with shadcn `<Badge>` using custom `className` for colors
- Status: green (approved), red (rejected), yellow (pending / pending_category_review), grey (cancelled)
- Category: orange (marketing), blue (utility), purple (authentication)
- Language: neutral grey badge added as a new cell

---

## Files Changed

| File | Action |
|---|---|
| Supabase migration | CREATE — add unique constraint `(channel_id, name, language)` |
| `frontend/src/app/api/templates/sync/route.ts` | CREATE |
| `frontend/src/components/campaigns/templates-tab.tsx` | MODIFY |

## Files NOT Changed

- `backend/app/templates/` — no Python backend changes needed
- `frontend/src/app/api/templates/route.ts` — already correct, no language filter
- `frontend/src/app/api/channels/[id]/templates/route.ts` — unrelated (broadcast template selection)

---

## Design Decisions

| Decision | Rationale |
|---|---|
| `channel_id` required in sync endpoint | Prevents hammering all channels at once; avoids Meta rate-limit risk |
| Sequential per-channel calls from UI | Simple, observable; failure in one channel doesn't block others |
| Unique key = `(channel_id, name, language)` | Matches Meta's own uniqueness model for templates |
| Ghost cleanup gated on full-page success | Prevents false `cancelled` if a Meta page request fails mid-sync |
| Auto-sync on tab mount | Replaces broken 30s polling; user sees fresh data immediately |
| Keep manual sync button | Allows user to re-sync without leaving the tab |

---

## Success Criteria

- Templates in other languages (en_US, es, etc.) appear after sync
- Status shows "Aprovado" / "Rejeitado" / "Pendente" matching current Meta state
- Category reflects Meta's actual classification
- Sync auto-runs on tab open; manual button re-syncs on demand
- Template deleted in Meta appears as "Cancelado" after next sync
- Sync handles >200 templates per channel (pagination)
- Failure in one channel's sync does not affect others

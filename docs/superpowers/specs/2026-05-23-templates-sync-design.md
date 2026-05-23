# Templates Sync — Design Spec
**Date:** 2026-05-23  
**Status:** Approved

## Problem

Three bugs in the `/campanhas` → Templates tab:

1. **Language filter:** Only `pt_BR` templates appear. Root cause: the local `message_templates` table only holds templates created via this app (all defaulting to `pt_BR`). Templates from Meta Business Manager in other languages are never imported.

2. **Stale status:** Status stays `"pending"` forever. The 30s polling in `TemplatesTab` queries the local Supabase table, which is never updated when Meta approves/rejects a template.

3. **Stale category:** Same root cause as status — set at creation time, never synced back from Meta.

**Common root cause:** No mechanism exists to sync the Meta API's template list back into the local `message_templates` table.

## Architecture

```
TemplatesTab
  → GET /api/templates          (Next.js route → Supabase, read-only)
  → POST /api/templates/sync    (NEW: Next.js route → Meta API + Supabase upsert)
```

## Solution

### 1. New API route: `POST /api/templates/sync`

**File:** `frontend/src/app/api/templates/sync/route.ts`

**Logic:**
1. Query Supabase for all channels where `provider = 'meta_cloud'` AND `is_active = true`
2. For each channel, extract `waba_id`, `access_token`, `api_version` from `provider_config`
3. Call Meta Graph API:  
   `GET https://graph.facebook.com/{version}/{waba_id}/message_templates?fields=name,status,language,category,components&limit=200`  
   (No status filter — fetch ALL templates including PENDING, REJECTED, APPROVED)
4. For each template returned, upsert into `message_templates` with `onConflict: 'channel_id,name'`, updating:
   - `status` (lowercased from Meta's APPROVED/REJECTED/PENDING)
   - `category` (lowercased)
   - `language`
   - `components` (to keep local rendering up to date)
5. Return `{ synced: number, channels: number }`

**Assumption:** `message_templates` table has a unique constraint on `(channel_id, name)`. If missing, a Supabase migration must be added before this endpoint works correctly.

**Error handling:**
- If a channel's Meta API call fails, skip that channel, log the error, continue with others
- Return partial success count

### 2. Modified component: `TemplatesTab`

**File:** `frontend/src/components/campaigns/templates-tab.tsx`

**Changes:**
- Remove the 30s polling interval (was querying local DB which never updates status)
- Add `syncStatus: 'idle' | 'loading' | 'success' | 'error'` state
- Add `syncMessage: string` state for toast text
- Add "Sincronizar" button with a rotating SVG icon (`animate-spin` during loading)
  - Disabled while `syncStatus === 'loading'`
  - Calls `POST /api/templates/sync`, then `loadTemplates()`
- Show toast (same inline HTML pattern as `quickSendToast` in `page.tsx`) on completion
- Replace existing inline `<span>` badges with shadcn `<Badge>` using custom `className`
  - Status: colors from `STATUS_CONFIG` (approved=green, rejected=red, pending=yellow)
  - Category: colors from `CATEGORY_CONFIG` (marketing=orange, utility=blue, authentication=purple)
  - Language: neutral grey badge

## Files Changed

| File | Action |
|---|---|
| `frontend/src/app/api/templates/sync/route.ts` | CREATE |
| `frontend/src/components/campaigns/templates-tab.tsx` | MODIFY |

## Files NOT Changed

- `backend/app/templates/` — no Python backend changes needed
- `frontend/src/app/api/templates/route.ts` — already correct, no language filter
- `frontend/src/app/api/channels/[id]/templates/route.ts` — unrelated (used for broadcast creation)
- `frontend/src/components/canais/create-template-modal.tsx` — out of scope (creation UX)

## No Migration Required (conditional)

If `(channel_id, name)` already has a unique constraint: no migration needed.  
If not: add migration `ALTER TABLE message_templates ADD UNIQUE (channel_id, name);`  
The implementation plan will verify this before coding the upsert.

## Success Criteria

- Templates in other languages (en_US, es, etc.) appear after clicking "Sincronizar"
- Status shows "Aprovado" / "Rejeitado" / "Pendente" matching the current state in Meta
- Category reflects Meta's actual classification
- Sync button shows spinner during operation and toast on completion
- No regressions in broadcast creation flow (which uses a separate endpoint)

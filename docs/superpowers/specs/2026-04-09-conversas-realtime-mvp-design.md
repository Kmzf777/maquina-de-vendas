# /conversas Realtime MVP — Design Spec

**Date:** 2026-04-09
**Branch:** `feat/conversas-realtime-mvp`
**Scope:** Wire Supabase realtime into the existing `/conversas` page so messages appear instantly without refresh.

---

## Problem

The `/conversas` page already has full infrastructure (ChatList, ChatView, ContactDetail, send via Meta API, messages saved to Supabase). The only missing piece is real-time updates:

- `ChatView` uses `setTimeout(fetchMessages, 500)` after sending — not reactive
- Incoming messages from webhook (`POST /webhook/meta` → `process_buffered_messages` → `save_message`) land in Supabase but don't appear in the UI without a page refresh
- The `useRealtimeMessages` hook already exists at `crm/src/hooks/use-realtime-messages.ts` with a working Supabase `postgres_changes` subscription — it just isn't used in `ChatView`

---

## Architecture

```
ConversasPage (page.tsx)
├── ChatList        ← no change
├── ChatView        ← replace manual fetch with useRealtimeMessages(lead_id)
└── ContactDetail   ← no change
```

### Incoming message flow (after fix)
```
Lead replies → POST /webhook/meta → push_to_buffer → process_buffered_messages
  → save_message("user") → run_agent → save_message("assistant")
  → Supabase INSERT on messages table
  → postgres_changes fires → useRealtimeMessages updates ChatView ✅
```

### Outgoing message flow (after fix)
```
CRM user types → handleSend → POST /api/conversations/[id]/send
  → sendViaMeta + INSERT on messages table
  → postgres_changes fires → useRealtimeMessages updates ChatView ✅
  (setTimeout removed)
```

---

## Changes

### 1. `crm/src/components/conversas/chat-view.tsx`

**Remove:**
- `fetchMessages()` function and all calls to it
- `setTimeout(fetchMessages, 500)` inside `handleSend`
- `loading` state and `setLoading` (moved to hook)
- Manual `useEffect` that calls `fetchMessages` on `conversation.id` change

**Add:**
- Import `useRealtimeMessages` from `@/hooks/use-realtime-messages`
- Replace with: `const { messages, loading } = useRealtimeMessages(lead?.id ?? null)`
- The hook already handles: initial fetch, real-time subscription by `lead_id`, cleanup on unmount, scroll to bottom on new messages (via the existing `bottomRef` useEffect)

**Keep:**
- `handleSend` unchanged (except removing `setTimeout` call)
- All JSX — header, message bubbles, input area
- `bottomRef` scroll effect (already in the component)

### 2. `crm/src/app/(authenticated)/conversas/page.tsx`

**Add:**
- A `useEffect` that subscribes to Supabase `postgres_changes` on the `conversations` table for `UPDATE` and `INSERT` events
- On trigger: call `fetchConversations()` to refresh and reorder the list
- Return cleanup: `supabase.removeChannel(channel)`

**Scope:** Subscribe to all conversations (no channel filter in the realtime subscription — `fetchConversations` already applies the `selectedChannelId` filter when re-fetching).

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Realtime subscription fails | Messages shown from initial load; no new real-time updates. No crash. |
| Send fails | `handleSend` already has `try/finally`; button re-enables, message not added to UI |
| `lead_id` is null | `useRealtimeMessages(null)` returns `{ messages: [], loading: false }` immediately, no subscription created |
| No messages in conversation | Existing "Nenhuma mensagem." empty state — no change |

---

## What Does NOT Change

- `ChatList`, `ContactDetail` components
- All API routes (`/api/conversations`, `/api/conversations/[id]/messages`, `/api/conversations/[id]/send`)
- Backend webhook and buffer processor
- `useRealtimeMessages` hook itself
- Supabase schema

---

## Validation

Manual test after implementation:
1. Open `/conversas`, select a Meta Cloud conversation
2. Send a message from the CRM — verify it appears instantly (no setTimeout delay)
3. From the lead's phone, reply to the bot — verify the message appears in CRM without refresh
4. Verify the bot's auto-reply also appears in real-time
5. Verify the conversation moves to top of list when a new message arrives

# Conversas UX Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the `/conversas` chat UI to WhatsApp/Intercom quality by adding a 24h countdown timer in the header, day separators between messages, message grouping, sender badges (IA/Vendedor), scroll-to-bottom button, last-message preview in cards, and an empty state — while extracting focused components from the current monolithic `chat-view.tsx`.

**Architecture:** Extract four new components (`ChatHeader`, `DaySeparator`, `MessageBubble`, `MessageList`) from `chat-view.tsx`, slim `chat-view.tsx` down to ~120 lines of orchestration, add `last_message_text` to the API via a Postgres RPC, and add preview rendering in `chat-list.tsx`.

**Tech Stack:** Next.js App Router, React, TypeScript (strict), Tailwind CSS, Supabase (service key, RPC). No new npm dependencies.

---

## File Map

| File | Status | Responsibility |
|------|--------|---------------|
| `frontend/src/components/conversas/chat-header.tsx` | **New** | Avatar, name, phone, tags, channel badge, 24h countdown |
| `frontend/src/components/conversas/day-separator.tsx` | **New** | Centered date chip between messages |
| `frontend/src/components/conversas/message-bubble.tsx` | **New** | Single message bubble with timestamp + sender badge |
| `frontend/src/components/conversas/message-list.tsx` | **New** | Ordered message rendering with day separators, grouping, scroll-to-bottom button |
| `frontend/src/components/conversas/chat-view.tsx` | **Edit** | Slim orchestrator: delegates header → ChatHeader, messages → MessageList |
| `frontend/src/components/conversas/chat-list.tsx` | **Edit** | Add last-message preview row; add empty state for no-selection |
| `frontend/src/app/api/conversations/route.ts` | **Edit** | Fetch `last_message_text` via Supabase RPC for meta_cloud conversations |
| `frontend/src/lib/types.ts` | **Edit** | Add `last_message_text: string \| null` to `Conversation` |
| `backend/migrations/20260427_get_last_messages_rpc.sql` | **New** | Postgres function `get_last_messages(conv_ids uuid[])` |

---

## Task 1: Postgres RPC for last message text

**Files:**
- Create: `backend/migrations/20260427_get_last_messages_rpc.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- backend/migrations/20260427_get_last_messages_rpc.sql
CREATE OR REPLACE FUNCTION get_last_messages(conv_ids uuid[])
RETURNS TABLE(conversation_id uuid, content text, role text)
LANGUAGE sql STABLE AS $$
  SELECT DISTINCT ON (conversation_id) conversation_id, content, role
  FROM messages
  WHERE conversation_id = ANY(conv_ids)
  ORDER BY conversation_id, created_at DESC;
$$;
```

- [ ] **Step 2: Apply via Supabase MCP**

Use the `mcp__supabase__apply_migration` tool with:
- `project_id`: `tshmvxxxyxgctrdkqvam`
- `name`: `get_last_messages_rpc`
- `query`: (contents of the SQL file above)

Expected: migration applied successfully.

- [ ] **Step 3: Verify the function exists**

Use `mcp__supabase__execute_sql` with:
```sql
SELECT proname FROM pg_proc WHERE proname = 'get_last_messages';
```
Expected: one row with `proname = 'get_last_messages'`.

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/20260427_get_last_messages_rpc.sql
git commit -m "feat(conversas): add get_last_messages RPC for last message preview"
```

---

## Task 2: Add `last_message_text` to types + API

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/app/api/conversations/route.ts`

### Step 1 — Update the `Conversation` type

- [ ] In `frontend/src/lib/types.ts`, add `last_message_text: string | null;` to the `Conversation` interface after `ai_enabled`:

```typescript
export interface Conversation {
  id: string;
  lead_id: string;
  channel_id: string;
  stage: string;
  status: string;
  last_msg_at: string | null;
  created_at: string;
  agent_profile_id: string | null;
  ai_enabled: boolean;
  last_message_text: string | null;   // ← new
  leads?: Lead;
  channels?: { id: string; name: string; phone: string; provider: string; agent_profile_id: string | null } | null;
  agent_profiles?: { id: string; name: string } | null;
}
```

### Step 2 — Fetch `last_message_text` in the API route

- [ ] In `frontend/src/app/api/conversations/route.ts`, after the DB conversations are fetched (after the `dbQuery.order(...).limit(100)` call), add a batch RPC call to get the last message for each meta_cloud conversation, then merge the result:

Find the section after `const { data: dbConversations } = await dbQuery...` and add:

```typescript
  // Fetch last message text for meta_cloud conversations via RPC
  const metaConvIds = (dbConversations || [])
    .filter((c) => (c.channels as { provider?: string } | null)?.provider === "meta_cloud")
    .map((c) => c.id as string);

  const lastMsgMap = new Map<string, string>();
  if (metaConvIds.length > 0) {
    const { data: lastMsgs } = await supabase.rpc("get_last_messages", {
      conv_ids: metaConvIds,
    });
    for (const row of lastMsgs || []) {
      const prefix = row.role === "assistant" ? "IA: " : "";
      lastMsgMap.set(row.conversation_id, prefix + row.content);
    }
  }
```

Then update the `merged` array construction so each DB conversation gets `last_message_text`. Replace the line:

```typescript
  const merged = [...(dbConversations || [])];
```

with:

```typescript
  const dbWithLastMsg = (dbConversations || []).map((c) => ({
    ...c,
    last_message_text: lastMsgMap.get(c.id as string) ?? null,
  }));
  const merged = [...dbWithLastMsg];
```

Also update the evo conversation mapping to add `last_message_text`:

Find the `return {` inside the `.map((chat) => {` in `fetchEvolutionConversations` and add:

```typescript
        last_message_text: extractLastMessageContent(chat.lastMessage?.message) || null,
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/app/api/conversations/route.ts
git commit -m "feat(conversas): add last_message_text to Conversation type and API"
```

---

## Task 3: `DaySeparator` component

**Files:**
- Create: `frontend/src/components/conversas/day-separator.tsx`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/conversas/day-separator.tsx
interface DaySeparatorProps {
  date: Date;
}

function formatDayLabel(date: Date): string {
  const now = new Date();
  const isToday =
    date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear();
  if (isToday) return "Hoje";

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday =
    date.getDate() === yesterday.getDate() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getFullYear() === yesterday.getFullYear();
  if (isYesterday) return "Ontem";

  if (date.getFullYear() === now.getFullYear()) {
    return date.toLocaleDateString("pt-BR", { day: "numeric", month: "long" });
  }
  return date.toLocaleDateString("pt-BR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function DaySeparator({ date }: DaySeparatorProps) {
  return (
    <div className="flex items-center gap-3 my-4 px-2">
      <div className="flex-1 h-px bg-[#dedbd6]" />
      <span className="text-[11px] text-[#9b9b98] px-2 py-0.5 rounded-full bg-[#f0ede8] whitespace-nowrap">
        {formatDayLabel(date)}
      </span>
      <div className="flex-1 h-px bg-[#dedbd6]" />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/conversas/day-separator.tsx
git commit -m "feat(conversas): add DaySeparator component"
```

---

## Task 4: `MessageBubble` component

**Files:**
- Create: `frontend/src/components/conversas/message-bubble.tsx`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/conversas/message-bubble.tsx
import type { Message } from "@/lib/types";

interface MessageBubbleProps {
  message: Message;
  isGrouped: boolean;
}

function formatTime(ts: string): string {
  const date = new Date(ts);
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function getSenderBadge(message: Message): string | null {
  if (message.role === "user") return null;
  if (message.sent_by === "agent") return "IA";
  if (message.sent_by === "seller") return "Vendedor";
  return null;
}

export function MessageBubble({ message, isGrouped }: MessageBubbleProps) {
  const isFromMe = message.role === "assistant";
  const isTemp = message.id.startsWith("temp_");
  const senderBadge = getSenderBadge(message);

  return (
    <div
      className={`flex ${isFromMe ? "justify-end" : "justify-start"} ${isGrouped ? "mt-0.5" : "mt-2"}`}
    >
      <div
        className={`px-3 py-2 text-[14px] max-w-[75%] rounded-[8px] ${
          isFromMe
            ? "bg-[#111111] text-white ml-auto"
            : "bg-white border border-[#dedbd6] text-[#111111]"
        } ${isTemp ? "opacity-70" : ""}`}
      >
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
        <div className={`flex items-center gap-1 mt-1 ${isFromMe ? "justify-end" : "justify-start"}`}>
          <p
            className={`text-[11px] ${
              isFromMe ? "text-white/50" : "text-[#7b7b78]"
            }`}
          >
            {isTemp ? "Enviando..." : formatTime(message.created_at)}
          </p>
          {senderBadge && (
            <span
              className={`text-[10px] opacity-60 ${
                isFromMe ? "text-white" : "text-[#7b7b78]"
              }`}
            >
              · {senderBadge}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/conversas/message-bubble.tsx
git commit -m "feat(conversas): add MessageBubble component with sender badge"
```

---

## Task 5: `MessageList` component

**Files:**
- Create: `frontend/src/components/conversas/message-list.tsx`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/conversas/message-list.tsx
"use client";

import { useRef, useEffect, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import type { Message } from "@/lib/types";
import { DaySeparator } from "@/components/conversas/day-separator";
import { MessageBubble } from "@/components/conversas/message-bubble";
import { EventCard } from "@/components/conversas/event-card";

interface MessageListProps {
  messages: Message[];
  loading: boolean;
}

export interface MessageListHandle {
  scrollToBottom: () => void;
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getDate() === b.getDate() &&
    a.getMonth() === b.getMonth() &&
    a.getFullYear() === b.getFullYear()
  );
}

function isGrouped(current: Message, previous: Message | undefined): boolean {
  if (!previous) return false;
  if (current.role !== previous.role) return false;
  const diff =
    new Date(current.created_at).getTime() -
    new Date(previous.created_at).getTime();
  return diff < 2 * 60 * 1000; // < 2 minutes
}

export const MessageList = forwardRef<MessageListHandle, MessageListProps>(
  function MessageList({ messages, loading }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const bottomRef = useRef<HTMLDivElement>(null);
    const [showScrollButton, setShowScrollButton] = useState(false);
    const [unreadCount, setUnreadCount] = useState(0);
    const prevMessageCountRef = useRef(messages.length);
    const isAtBottomRef = useRef(true);

    useImperativeHandle(ref, () => ({
      scrollToBottom() {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      },
    }));

    const handleScroll = useCallback(() => {
      const el = containerRef.current;
      if (!el) return;
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      const atBottom = distanceFromBottom < 100;
      isAtBottomRef.current = atBottom;
      setShowScrollButton(!atBottom);
      if (atBottom) setUnreadCount(0);
    }, []);

    // Auto-scroll on new messages if already at bottom; increment badge if not
    useEffect(() => {
      const newCount = messages.length;
      const prevCount = prevMessageCountRef.current;
      if (newCount > prevCount) {
        if (isAtBottomRef.current) {
          bottomRef.current?.scrollIntoView({ behavior: "smooth" });
          setUnreadCount(0);
        } else {
          setUnreadCount((c) => c + (newCount - prevCount));
        }
      }
      prevMessageCountRef.current = newCount;
    }, [messages.length]);

    // Initial scroll to bottom on mount / conversation switch
    useEffect(() => {
      bottomRef.current?.scrollIntoView({ behavior: "instant" });
      setUnreadCount(0);
      prevMessageCountRef.current = messages.length;
    }, []);  // eslint-disable-line react-hooks/exhaustive-deps

    function scrollToBottom() {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      setUnreadCount(0);
    }

    return (
      <div className="relative flex-1 overflow-hidden">
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="h-full overflow-y-auto px-4 py-4 bg-[#faf9f6]"
        >
          {loading && (
            <div className="flex justify-center py-8">
              <div className="w-6 h-6 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin" />
            </div>
          )}
          {!loading && messages.length === 0 && (
            <p className="text-[#7b7b78] text-sm text-center py-8">
              Nenhuma mensagem.
            </p>
          )}

          {messages.map((msg, idx) => {
            const prev = messages[idx - 1];
            const currDate = new Date(msg.created_at);
            const prevDate = prev ? new Date(prev.created_at) : null;
            const showDaySep = !prevDate || !isSameDay(currDate, prevDate);
            const grouped = isGrouped(msg, prev);

            return (
              <div key={msg.id}>
                {showDaySep && <DaySeparator date={currDate} />}
                {msg.role === "system" ? (
                  <EventCard message={msg} />
                ) : (
                  <MessageBubble message={msg} isGrouped={grouped} />
                )}
              </div>
            );
          })}

          <div ref={bottomRef} />
        </div>

        {showScrollButton && (
          <button
            onClick={scrollToBottom}
            className="absolute bottom-4 right-4 w-9 h-9 bg-[#111111] text-white rounded-full shadow-lg flex items-center justify-center hover:opacity-90 transition-opacity"
          >
            {unreadCount > 0 && (
              <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] bg-red-500 text-white text-[10px] font-medium rounded-full flex items-center justify-center px-1">
                {unreadCount > 9 ? "9+" : unreadCount}
              </span>
            )}
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        )}
      </div>
    );
  }
);
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/conversas/message-list.tsx
git commit -m "feat(conversas): add MessageList with day separators, grouping, scroll-to-bottom"
```

---

## Task 6: `ChatHeader` component

**Files:**
- Create: `frontend/src/components/conversas/chat-header.tsx`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/conversas/chat-header.tsx
"use client";

import { useState, useEffect } from "react";
import type { Conversation, Tag } from "@/lib/types";
import {
  getWindowStatus,
  windowExpiresInMs,
  formatTimeRemaining,
} from "@/lib/window-status";

interface ChatHeaderProps {
  conversation: Conversation;
  tags: Tag[];
}

function getStageColor(stage: string | undefined): string {
  const map: Record<string, string> = {
    secretaria: "#8a8a80",
    atacado: "#5b8aad",
    private_label: "#8b6bab",
    exportacao: "#5aad65",
    consumo: "#ad9c4a",
  };
  return map[stage ?? ""] ?? "#8a8a80";
}

export function ChatHeader({ conversation, tags }: ChatHeaderProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;
  const [, setTick] = useState(0);

  const provider = channel?.provider ?? null;
  const lastCustomerMsgAt = lead?.last_customer_message_at ?? null;
  const windowStatus = getWindowStatus(lastCustomerMsgAt, provider);
  const timeRemainingMs =
    (windowStatus === "open" || windowStatus === "expiring") && lastCustomerMsgAt
      ? windowExpiresInMs(lastCustomerMsgAt)
      : 0;

  // Refresh countdown every 60s while window is open or expiring
  useEffect(() => {
    if (windowStatus === "closed" || windowStatus === "n/a") return;
    const interval = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(interval);
  }, [windowStatus]);

  const displayName = lead?.name || lead?.phone || "Desconhecido";
  const initial = displayName.charAt(0).toUpperCase();
  const avatarColor = getStageColor(lead?.stage);

  const tagIdsRaw = (lead as unknown as Record<string, unknown>)?.tag_ids;
  const tagIds = Array.isArray(tagIdsRaw) ? (tagIdsRaw as string[]) : [];
  const leadTags = tags.filter((t) => tagIds.includes(t.id));

  return (
    <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-3 flex items-center gap-3 flex-shrink-0">
      {/* Avatar */}
      <div
        className="w-9 h-9 rounded-full flex items-center justify-center text-white font-medium text-sm flex-shrink-0"
        style={{ backgroundColor: avatarColor }}
      >
        {initial}
      </div>

      {/* Name + phone */}
      <div className="flex-1 min-w-0">
        <h2 className="text-[#111111] font-medium text-[14px] truncate">
          {displayName}
        </h2>
        <p className="text-[#7b7b78] text-[12px]">{lead?.phone || ""}</p>
      </div>

      {/* Tags */}
      {leadTags.length > 0 && (
        <div className="flex gap-1 flex-shrink-0">
          {leadTags.map((tag) => (
            <span
              key={tag.id}
              className="px-2 py-0.5 rounded-[4px] text-[11px] text-white"
              style={{ backgroundColor: tag.color }}
            >
              {tag.name}
            </span>
          ))}
        </div>
      )}

      {/* Channel badge */}
      {channel && (
        <span className="text-[11px] px-2 py-0.5 rounded-[4px] bg-[#dedbd6]/60 text-[#7b7b78] flex-shrink-0">
          {channel.name}
        </span>
      )}

      {/* 24h window countdown — only for meta_cloud */}
      {windowStatus === "open" && (
        <span className="text-[12px] text-green-700 flex-shrink-0 flex items-center gap-1">
          ⏳ Janela · {formatTimeRemaining(timeRemainingMs)}
        </span>
      )}
      {windowStatus === "expiring" && (
        <span className="text-[12px] text-amber-700 flex-shrink-0 flex items-center gap-1 animate-pulse">
          ⏱ Expira em {formatTimeRemaining(timeRemainingMs)}
        </span>
      )}
      {windowStatus === "closed" && (
        <span className="text-[12px] text-red-700 flex-shrink-0">
          🔒 Janela fechada
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/conversas/chat-header.tsx
git commit -m "feat(conversas): add ChatHeader with 24h window countdown"
```

---

## Task 7: Slim `chat-view.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx`

- [ ] **Step 1: Replace the entire content of `chat-view.tsx`**

The new file delegates header and messages to the new components. The `formatTime` function is removed (now inside `MessageBubble`). The ticker logic moves to `ChatHeader`. Auto-scroll moves to `MessageList`.

```tsx
// frontend/src/components/conversas/chat-view.tsx
"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import type { Message, Conversation, Tag } from "@/lib/types";
import { useRealtimeMessages } from "@/hooks/use-realtime-messages";
import { getWindowStatus, formatTimeRemaining, windowExpiresInMs } from "@/lib/window-status";
import { WindowReactivatePanel } from "@/components/conversas/window-reactivate-panel";
import { ChatHeader } from "@/components/conversas/chat-header";
import { MessageList } from "@/components/conversas/message-list";

interface ChatViewProps {
  conversation: Conversation;
  tags: Tag[];
}

export function ChatView({ conversation, tags }: ChatViewProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;

  const { messages, loading } = useRealtimeMessages(lead?.id ?? null);
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [showReactivatePanel, setShowReactivatePanel] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const provider = channel?.provider ?? null;
  const lastCustomerMsgAt = lead?.last_customer_message_at ?? null;
  const windowStatus = getWindowStatus(lastCustomerMsgAt, provider);
  const isInputBlocked = windowStatus === "closed";
  const timeRemainingMs =
    windowStatus === "expiring" && lastCustomerMsgAt
      ? windowExpiresInMs(lastCustomerMsgAt)
      : 0;

  useEffect(() => {
    setOptimisticMessages([]);
    setShowReactivatePanel(false);
  }, [conversation.id]);

  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, [conversation.id]);

  const displayMessages = useMemo(
    () => [...messages, ...optimisticMessages],
    [messages, optimisticMessages]
  );

  async function handleSend() {
    if (!text.trim() || sendingRef.current || isInputBlocked) return;
    sendingRef.current = true;
    const content = text.trim();

    const tempMsg: Message = {
      id: `temp_${Date.now()}`,
      lead_id: lead?.id ?? "",
      role: "assistant",
      content,
      stage: null,
      sent_by: "seller",
      created_at: new Date().toISOString(),
    };

    setText("");
    setOptimisticMessages((prev) => [...prev, tempMsg]);
    setSending(true);

    try {
      const controller = new AbortController();
      abortRef.current = controller;
      const res = await fetch(`/api/conversations/${conversation.id}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: content }),
        signal: controller.signal,
      });
      if (!res.ok) setText(content);
      setOptimisticMessages((prev) => prev.filter((m) => m.id !== tempMsg.id));
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      setOptimisticMessages((prev) => prev.filter((m) => m.id !== tempMsg.id));
      setText(content);
    } finally {
      setSending(false);
      sendingRef.current = false;
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-[#faf9f6]">
      <ChatHeader conversation={conversation} tags={tags} />

      <MessageList key={conversation.id} messages={displayMessages} loading={loading} />

      {/* Window status banner */}
      {windowStatus === "expiring" && (
        <div className="bg-[#fef3c7] border-t border-[#f59e0b]/30 px-4 py-2 flex items-center gap-2 flex-shrink-0">
          <span className="text-[12px] text-[#92400e]">
            ⏱ Janela expira em {formatTimeRemaining(timeRemainingMs)} — responda logo ou envie um template.
          </span>
        </div>
      )}
      {windowStatus === "closed" && (
        <div className="bg-[#fff7ed] border-t border-[#f97316]/30 px-4 py-2 flex items-center justify-between gap-2 flex-shrink-0">
          <span className="text-[12px] text-[#7c2d12]">
            🔴 Janela de 24h encerrada. Não é possível enviar mensagens de texto livre.
          </span>
          <button
            onClick={() => setShowReactivatePanel((v) => !v)}
            className="flex-shrink-0 text-[12px] bg-[#111111] text-white px-3 py-1.5 rounded-[4px] hover:opacity-90 transition-opacity whitespace-nowrap"
          >
            Reativar conversa
          </button>
        </div>
      )}

      {showReactivatePanel && windowStatus === "closed" && (
        <WindowReactivatePanel
          conversation={conversation}
          onClose={() => setShowReactivatePanel(false)}
        />
      )}

      {/* Input */}
      <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex gap-2 flex-shrink-0">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isInputBlocked ? "Janela encerrada — use Reativar conversa" : "Digitar mensagem..."}
          rows={1}
          disabled={isInputBlocked}
          className={`flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none resize-none max-h-32 ${isInputBlocked ? "opacity-40 cursor-not-allowed" : ""}`}
        />
        <button
          onClick={handleSend}
          disabled={sending || !text.trim() || isInputBlocked}
          className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 flex-shrink-0 self-end"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -40
```

Expected: no errors (or only pre-existing errors unrelated to this feature).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "feat(conversas): slim ChatView — delegate to ChatHeader and MessageList"
```

---

## Task 8: Last-message preview + empty state in `chat-list.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/chat-list.tsx`

- [ ] **Step 1: Update the empty state in `frontend/src/app/(authenticated)/conversas/page.tsx`**

The page already has an empty state at lines 204–228. It shows "Selecione uma conversa" and a static subtitle. The spec requires the subtitle to show the count of open conversations. Replace the `<p>` subtitle (line 221–223) from:

```tsx
            <p className="text-[#7b7b78] text-[14px] mt-1">
              Escolha um contato para ver as mensagens
            </p>
```

with:

```tsx
            <p className="text-[#7b7b78] text-[14px] mt-1">
              {conversations.length} conversa{conversations.length !== 1 ? "s" : ""} aberta{conversations.length !== 1 ? "s" : ""}
            </p>
```

- [ ] **Step 2: Add last-message preview to each card in `chat-list.tsx`**

In `chat-list.tsx`, inside the card's info section, after the second row (channel + phone), add a third row for the last message preview. The `Conversation` type now has `last_message_text`.

Find the `{hasAgent && ...}` block and add the preview just before it:

```tsx
{conv.last_message_text && (
  <p className={`text-[12px] truncate mt-0.5 ${isActive ? "text-white/60" : "text-[#7b7b78]"}`}>
    {conv.last_message_text}
  </p>
)}
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -40
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/chat-list.tsx frontend/src/app/\(authenticated\)/conversas/page.tsx
git commit -m "feat(conversas): add last-message preview and empty state with conversation count"
```

---

## Task 9: Push branch and finish

- [ ] **Step 1: Final TypeScript check across all new files**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -60
```

Expected: zero errors.

- [ ] **Step 2: Review git log**

```bash
git log --oneline origin/master..HEAD
```

Expected: 8-9 commits for this feature.

- [ ] **Step 3: Push branch**

```bash
git push -u origin feat/conversas-ux-redesign
```

- [ ] **Step 4: Stop and notify the user**

Report: "Branch `feat/conversas-ux-redesign` pushed. All tasks complete. The user needs to test in the dev environment before merging to master."

# /conversas Realtime MVP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/conversas` show all messages in real-time (sent and received) without page refresh, using the existing Supabase realtime infrastructure.

**Architecture:** Wire `useRealtimeMessages(lead_id)` into `ChatView` to replace manual `fetchMessages` + `setTimeout`. Add optimistic UI so sent messages appear instantly (temp message in local state, replaced silently by real DB record via realtime). Add a Supabase subscription in `ConversasPage` to re-sort the conversations list when `last_msg_at` changes.

**Tech Stack:** Next.js App Router, React hooks, Supabase JS client (`@supabase/supabase-js`), TypeScript.

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `crm/src/components/conversas/chat-view.tsx` | Modify | Remove manual fetch; add `useRealtimeMessages` + `optimisticMessages` state + optimistic send |
| `crm/src/app/(authenticated)/conversas/page.tsx` | Modify | Add Supabase realtime subscription on `conversations` table |

No new files. No backend changes. No API route changes.

---

### Task 1: Create the feature branch

**Files:** none (git only)

- [ ] **Step 1: Create and switch to branch**

```bash
cd /home/Kelwin/Maquinadevendascanastra
git checkout -b feat/conversas-realtime-mvp
```

Expected output: `Switched to a new branch 'feat/conversas-realtime-mvp'`

---

### Task 2: Replace manual fetch with realtime hook + optimistic UI in ChatView

**Files:**
- Modify: `crm/src/components/conversas/chat-view.tsx`

- [ ] **Step 1: Replace the entire file with the new implementation**

Open `crm/src/components/conversas/chat-view.tsx` and replace its full contents with:

```tsx
"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import type { Message, Conversation, Tag, Lead } from "@/lib/types";
import { useRealtimeMessages } from "@/hooks/use-realtime-messages";

interface ChatViewProps {
  conversation: Conversation;
  tags: Tag[];
}

function formatTime(ts: string): string {
  const date = new Date(ts);
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export function ChatView({ conversation, tags }: ChatViewProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;

  // Real-time messages from Supabase (subscribed by lead_id)
  const { messages, loading } = useRealtimeMessages(lead?.id ?? null);

  // Optimistic messages: shown immediately on send, removed once real message arrives
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);

  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Clear optimistic messages when switching conversations
  useEffect(() => {
    setOptimisticMessages([]);
  }, [conversation.id]);

  // Merged display list: real messages + unconfirmed optimistic ones
  // A temp message is removed once a real message with same content+sender arrives
  const displayMessages = useMemo(() => {
    const confirmedKeys = new Set(messages.map((m) => `${m.content}|${m.sent_by}`));
    return [
      ...messages,
      ...optimisticMessages.filter(
        (o) => !confirmedKeys.has(`${o.content}|${o.sent_by}`)
      ),
    ];
  }, [messages, optimisticMessages]);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayMessages]);

  async function handleSend() {
    if (!text.trim() || sending) return;

    const content = text.trim();

    // Inject optimistic message immediately — user sees it at ~0ms
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
      const res = await fetch(`/api/conversations/${conversation.id}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: content }),
      });

      if (!res.ok) {
        // Send failed — remove temp message and restore input
        setOptimisticMessages((prev) => prev.filter((m) => m.id !== tempMsg.id));
        setText(content);
      }
      // On success: do nothing. Supabase realtime will bring the real message,
      // and displayMessages will filter out the temp automatically.
    } catch {
      setOptimisticMessages((prev) => prev.filter((m) => m.id !== tempMsg.id));
      setText(content);
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const displayName = lead?.name || lead?.phone || "Desconhecido";
  const isMetaCloud = channel?.provider === "meta_cloud";

  const leadTagIds = lead
    ? tags.filter((t) => (lead as Lead & { tag_ids?: string[] }).tag_ids?.includes(t.id))
    : [] as Tag[];

  return (
    <div className="flex-1 flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-white border-b border-[#e5e5dc]">
        <div className="w-10 h-10 rounded-full bg-[#c8cc8e] flex items-center justify-center text-white font-medium">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1">
          <h2 className="text-[#1f1f1f] font-medium text-sm">{displayName}</h2>
          <p className="text-[#9ca3af] text-xs">{lead?.phone || ""}</p>
        </div>
        {channel && (
          <span
            className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
              isMetaCloud
                ? "bg-[#c8cc8e] text-[#1f1f1f]"
                : "bg-[#93c5fd] text-[#1e3a5f]"
            }`}
          >
            {channel.name}
          </span>
        )}
        {leadTagIds.length > 0 && (
          <div className="flex gap-1">
            {leadTagIds.map((tag) => (
              <span
                key={tag.id}
                className="px-2 py-0.5 rounded-full text-xs text-white"
                style={{ backgroundColor: tag.color }}
              >
                {tag.name}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2 bg-[#f6f7ed]">
        {loading && (
          <div className="flex justify-center py-8">
            <div className="w-6 h-6 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {!loading && displayMessages.length === 0 && (
          <p className="text-[#9ca3af] text-sm text-center py-8">Nenhuma mensagem.</p>
        )}
        {displayMessages.map((msg) => {
          const isFromMe =
            msg.role === "assistant" ||
            msg.sent_by === "agent" ||
            msg.sent_by === "seller";
          const isTemp = msg.id.startsWith("temp_");
          return (
            <div
              key={msg.id}
              className={`flex ${isFromMe ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[70%] px-3 py-2 ${
                  isFromMe
                    ? "bg-[#1f1f1f] text-white rounded-2xl rounded-br-sm"
                    : "bg-white border border-[#e5e5dc] text-[#1f1f1f] rounded-2xl rounded-bl-sm"
                } ${isTemp ? "opacity-70" : ""}`}
              >
                <p className="text-sm whitespace-pre-wrap break-words">{msg.content}</p>
                <p
                  className={`text-[11px] mt-1 ${
                    isFromMe ? "text-white/50" : "text-[#9ca3af]"
                  }`}
                >
                  {isTemp ? "Enviando..." : formatTime(msg.created_at)}
                </p>
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 bg-white border-t border-[#e5e5dc]">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Digitar mensagem..."
            rows={1}
            className="flex-1 bg-[#f6f7ed] text-[#1f1f1f] text-sm rounded-2xl px-4 py-2.5 placeholder-[#9ca3af] outline-none focus:ring-1 focus:ring-[#c8cc8e] resize-none max-h-32 border border-[#e5e5dc]"
          />
          <button
            onClick={handleSend}
            disabled={sending || !text.trim()}
            className="bg-[#1f1f1f] text-white p-2.5 rounded-full hover:bg-[#333] disabled:opacity-50 flex-shrink-0 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles without errors**

```bash
cd /home/Kelwin/Maquinadevendascanastra/crm
npx tsc --noEmit 2>&1 | head -30
```

Expected: no output (no errors). If errors appear, fix them before continuing.

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/conversas/chat-view.tsx
git commit -m "feat(conversas): wire useRealtimeMessages + optimistic UI into ChatView"
```

---

### Task 3: Add realtime subscription on conversations list in ConversasPage

**Files:**
- Modify: `crm/src/app/(authenticated)/conversas/page.tsx`

- [ ] **Step 1: Add the realtime subscription useEffect**

In `crm/src/app/(authenticated)/conversas/page.tsx`, add the following `useEffect` **after** the existing `useEffect(() => { fetchConversations(); }, [selectedChannelId]);` block (around line 27):

```tsx
  // Realtime: re-sort list when any conversation's last_msg_at changes
  useEffect(() => {
    const channel = supabase
      .channel("conversations-updates")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "conversations" },
        () => {
          fetchConversations();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [selectedChannelId]);
```

> Note: the dependency on `selectedChannelId` ensures the subscription is recreated when the user switches channels, so `fetchConversations()` inside it always uses the current filter.

- [ ] **Step 2: Verify TypeScript compiles without errors**

```bash
cd /home/Kelwin/Maquinadevendascanastra/crm
npx tsc --noEmit 2>&1 | head -30
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/(authenticated)/conversas/page.tsx
git commit -m "feat(conversas): add supabase realtime subscription on conversations list"
```

---

### Task 4: Manual end-to-end validation

**Files:** none (validation only)

- [ ] **Step 1: Start the dev server**

```bash
cd /home/Kelwin/Maquinadevendascanastra/crm
npm run dev
```

Open `http://localhost:3000/conversas` in the browser.

- [ ] **Step 2: Validate send — optimistic UI**

1. Select any Meta Cloud conversation with an existing contact
2. Type a message and press Enter (or click send button)
3. The message must appear **immediately** with "Enviando..." timestamp and slightly dimmed opacity
4. Within ~1–2s, it transitions to a real timestamp (Supabase realtime confirmed)
5. No duplicate messages appear

- [ ] **Step 3: Validate receive — incoming messages appear without refresh**

1. From the lead's phone, send a WhatsApp message to the business number
2. Without touching the browser, within a few seconds the message must appear in the chat view
3. If the bot is configured (channel has `agent_profiles`), the bot's reply must also appear automatically

- [ ] **Step 4: Validate conversations list re-sorts**

1. Have a conversation open that is NOT at the top of the list
2. Send or receive a message in it
3. That conversation must move to the top of `ChatList` automatically

- [ ] **Step 5: Validate send failure handling**

Temporarily break the send route to test failure path (or simply disconnect the internet):
1. If send fails, the "Enviando..." temp message disappears and the text is restored in the input

---

### Task 5: Push branch

- [ ] **Step 1: Push branch to remote**

```bash
git push -u origin feat/conversas-realtime-mvp
```

Expected: branch pushed, ready for PR or direct validation on Vercel preview.

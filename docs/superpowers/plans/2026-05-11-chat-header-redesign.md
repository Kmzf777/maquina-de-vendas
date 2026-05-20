# Chat Header Redesign + Finalizar Conversa

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **IMPORTANT:** Any agent working on frontend files MUST invoke the `frontend-design` skill before making any UI changes.

**Goal:** Simplify the chat header to show only Lead name + Valéria IA button + `...` dropdown (containing Follow-up toggle and Finalizar conversa), removing the channel pill and WA indicator from the header; also clean up the redundant Follow-up button in the mobile contact-detail panel.

**Architecture:** Pure frontend change — no new API routes needed. The existing `POST /api/conversations/[id]/mark-read` endpoint already zeroes `unread_count`. We thread an `onMarkRead` callback from `conversas/page.tsx` → `ChatView` → `ChatHeader`. The `...` dropdown is a locally-controlled piece of state in `ChatHeader` with a click-outside listener.

**Tech Stack:** Next.js App Router, React, Tailwind CSS. No new dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `frontend/src/components/conversas/chat-header.tsx` | Modify | Remove channel pill, WA indicator, Follow-up button; add `...` dropdown with Follow-up toggle + Finalizar |
| `frontend/src/components/conversas/chat-view.tsx` | Modify | Add `onMarkRead` prop, pass to `ChatHeader` |
| `frontend/src/app/(authenticated)/conversas/page.tsx` | Modify | Pass `onMarkRead` callback to `ChatView` |
| `frontend/src/components/conversas/contact-detail.tsx` | Modify | Remove Follow-up toggle from mobile controls section |

---

## Task 1: Redesign `chat-header.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/chat-header.tsx`

- [ ] **Step 1: Invoke frontend-design skill**

Before touching any code, invoke the `frontend-design` skill.

- [ ] **Step 2: Replace the entire file with the new implementation**

Replace the full content of `frontend/src/components/conversas/chat-header.tsx` with:

```tsx
"use client";

import { useState, useRef, useEffect } from "react";
import type { Conversation, Tag } from "@/lib/types";

interface ChatHeaderProps {
  conversation: Conversation;
  tags: Tag[];
  aiEnabled: boolean;
  togglingAi?: boolean;
  onToggleAi: () => void | Promise<void>;
  followupEnabled: boolean;
  togglingFollowup?: boolean;
  onToggleFollowup: () => void | Promise<void>;
  onMarkRead?: () => void | Promise<void>;
  onBack?: () => void;
  onOpenContact?: () => void;
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

export function ChatHeader({
  conversation,
  tags,
  aiEnabled,
  togglingAi,
  onToggleAi,
  followupEnabled,
  togglingFollowup,
  onToggleFollowup,
  onMarkRead,
  onBack,
  onOpenContact,
}: ChatHeaderProps) {
  const lead = conversation.leads;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const displayName = lead?.name || lead?.phone || "Desconhecido";
  const initial = displayName.charAt(0).toUpperCase();
  const avatarColor = getStageColor(lead?.stage);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    if (menuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpen]);

  async function handleFinalize() {
    setMenuOpen(false);
    await onMarkRead?.();
  }

  return (
    <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-3 flex items-center gap-3 flex-shrink-0">
      {/* Mobile back button */}
      {onBack && (
        <button
          onClick={onBack}
          className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-[4px] text-[#313130] hover:bg-[#dedbd6]/60 transition-colors"
          aria-label="Voltar"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>
      )}

      {/* Avatar */}
      <div
        className={`w-9 h-9 rounded-full flex items-center justify-center text-white font-medium text-sm flex-shrink-0${onOpenContact ? " cursor-pointer" : ""}`}
        style={{ backgroundColor: avatarColor }}
        onClick={onOpenContact}
      >
        {initial}
      </div>

      {/* Name */}
      <div
        className={`flex-1 min-w-0${onOpenContact ? " cursor-pointer" : ""}`}
        onClick={onOpenContact}
      >
        <h2 className="text-[#111111] font-medium text-[14px] truncate">{displayName}</h2>
      </div>

      {/* Valéria IA button */}
      <button
        type="button"
        onClick={() => onToggleAi()}
        disabled={togglingAi}
        className={`inline-flex items-center gap-2 rounded-[4px] px-3 py-1 text-xs font-medium transition-colors flex-shrink-0 ${
          aiEnabled
            ? "bg-[#ff5600] text-white hover:bg-[#e64e00]"
            : "bg-[#dedbd6] text-[#111111] hover:bg-[#cbc7c0]"
        } ${togglingAi ? "opacity-60 cursor-not-allowed" : ""}`}
        aria-pressed={aiEnabled}
      >
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${aiEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"}`}
          aria-hidden
        />
        Valéria IA · {aiEnabled ? "Ativa" : "Pausada"}
      </button>

      {/* ... dropdown */}
      <div className="relative flex-shrink-0" ref={menuRef}>
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          className="w-8 h-8 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/60 transition-colors"
          aria-label="Mais opções"
        >
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <circle cx="5" cy="12" r="2" />
            <circle cx="12" cy="12" r="2" />
            <circle cx="19" cy="12" r="2" />
          </svg>
        </button>

        {menuOpen && (
          <div className="absolute right-0 top-full mt-1 w-52 bg-white border border-[#dedbd6] rounded-[8px] shadow-lg py-1 z-50">
            {/* Follow-up toggle */}
            <button
              type="button"
              onClick={() => { onToggleFollowup(); setMenuOpen(false); }}
              disabled={togglingFollowup}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-[13px] text-left transition-colors hover:bg-[#f5f3f0] ${
                togglingFollowup ? "opacity-60 cursor-not-allowed" : ""
              }`}
            >
              <span
                className={`inline-block h-2 w-2 rounded-full flex-shrink-0 ${
                  followupEnabled ? "bg-[#1e6ee8] animate-pulse" : "bg-[#7b7b78]"
                }`}
                aria-hidden
              />
              <span className="flex-1 text-[#111111]">Follow-up</span>
              <span className={`text-[11px] font-medium ${followupEnabled ? "text-[#1e6ee8]" : "text-[#7b7b78]"}`}>
                {followupEnabled ? "Ativo" : "Pausado"}
              </span>
            </button>

            <div className="border-t border-[#dedbd6] my-1" />

            {/* Finalizar conversa */}
            <button
              type="button"
              onClick={handleFinalize}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-[13px] text-left hover:bg-[#f5f3f0] transition-colors"
            >
              <svg
                className="w-4 h-4 text-[#7b7b78] flex-shrink-0"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="text-[#111111]">Finalizar conversa</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
```

Note: `tags` prop is kept in the interface for backwards compatibility but is no longer rendered (it was only used to display lead tags in the header, which we're removing per the design).

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors related to `chat-header.tsx`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/chat-header.tsx
git commit -m "feat(conversas): simplificar header — dropdown ... com follow-up e finalizar"
```

---

## Task 2: Thread `onMarkRead` through `ChatView`

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx` (lines 12-23 interface, line 25 destructure, line 291-302 ChatHeader call)

- [ ] **Step 1: Add `onMarkRead` to `ChatViewProps` interface**

In `chat-view.tsx`, find the `ChatViewProps` interface and add the new optional prop:

```tsx
interface ChatViewProps {
  conversation: Conversation;
  tags: Tag[];
  aiEnabled: boolean;
  togglingAi?: boolean;
  onToggleAi: () => void | Promise<void>;
  followupEnabled: boolean;
  togglingFollowup?: boolean;
  onToggleFollowup: () => void | Promise<void>;
  onMarkRead?: () => void | Promise<void>;   // ← add this line
  onBack?: () => void;
  onOpenContact?: () => void;
}
```

- [ ] **Step 2: Add `onMarkRead` to the destructured parameters**

Find the `export function ChatView({ ... })` signature (line 25) and add `onMarkRead` to the destructured props:

```tsx
export function ChatView({ conversation, tags, aiEnabled, togglingAi, onToggleAi, followupEnabled, togglingFollowup, onToggleFollowup, onMarkRead, onBack, onOpenContact }: ChatViewProps) {
```

- [ ] **Step 3: Pass `onMarkRead` to `ChatHeader`**

Find the `<ChatHeader` JSX block (around line 291) and add the prop:

```tsx
      <ChatHeader
        conversation={conversation}
        tags={tags}
        aiEnabled={aiEnabled}
        togglingAi={togglingAi}
        onToggleAi={onToggleAi}
        followupEnabled={followupEnabled}
        togglingFollowup={togglingFollowup}
        onToggleFollowup={onToggleFollowup}
        onMarkRead={onMarkRead}
        onBack={onBack}
        onOpenContact={onOpenContact}
      />
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "feat(conversas): passar onMarkRead para ChatHeader via ChatView"
```

---

## Task 3: Wire `onMarkRead` in `conversas/page.tsx`

**Files:**
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx`

There are two `<ChatView` usages — one inside the mobile block (~line 371) and one inside the desktop block (~line 421). Both need the new prop.

- [ ] **Step 1: Add `onMarkRead` to the mobile ChatView**

Find the mobile `<ChatView` (the one that has `onBack={() => setMobileView("list")}`) and add:

```tsx
              onMarkRead={() => handleMarkRead(selectedConversation.id)}
```

Full block after change:

```tsx
        {selectedConversation && (
          <ChatView
            conversation={selectedConversation}
            tags={tags}
            aiEnabled={(selectedConversation.leads as any)?.ai_enabled ?? true}
            togglingAi={togglingAi}
            onToggleAi={handleToggleAi}
            followupEnabled={selectedConversation.followup_enabled ?? true}
            togglingFollowup={togglingFollowup}
            onToggleFollowup={handleToggleFollowup}
            onMarkRead={() => handleMarkRead(selectedConversation.id)}
            onBack={() => setMobileView("list")}
            onOpenContact={() => setMobileView("contact")}
          />
        )}
```

- [ ] **Step 2: Add `onMarkRead` to the desktop ChatView**

Find the desktop `<ChatView` (inside the `hidden md:flex` block, the one without `onBack`) and add:

```tsx
              onMarkRead={() => handleMarkRead(selectedConversation.id)}
```

Full block after change:

```tsx
            <ChatView
              conversation={selectedConversation}
              tags={tags}
              aiEnabled={(selectedConversation.leads as any)?.ai_enabled ?? true}
              togglingAi={togglingAi}
              onToggleAi={handleToggleAi}
              followupEnabled={selectedConversation.followup_enabled ?? true}
              togglingFollowup={togglingFollowup}
              onToggleFollowup={handleToggleFollowup}
              onMarkRead={() => handleMarkRead(selectedConversation.id)}
            />
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/(authenticated)/conversas/page.tsx"
git commit -m "feat(conversas): conectar onMarkRead ao handleMarkRead na page"
```

---

## Task 4: Remove Follow-up from mobile contact-detail panel

**Files:**
- Modify: `frontend/src/components/conversas/contact-detail.tsx` (mobile controls section, ~lines 130-168)

The mobile back-panel in `contact-detail.tsx` currently shows AI toggle + Follow-up toggle + WA indicator. Since Follow-up is now in the `...` header dropdown (accessible from the chat view), remove only the Follow-up toggle. Keep the AI toggle and WA indicator so the user has access to them from the contact panel on mobile.

- [ ] **Step 1: Remove the Follow-up `<button>` block from the mobile section**

In `contact-detail.tsx`, find the mobile controls section (~line 130). It looks like:

```tsx
          <div className="flex items-center gap-2 flex-wrap">
            {onToggleAi && (
              <button
                type="button"
                onClick={() => onToggleAi()}
                disabled={togglingAi}
                className={`inline-flex items-center gap-2 rounded-[4px] px-3 py-1.5 text-xs font-medium transition-colors ${
                  aiEnabled
                    ? "bg-[#ff5600] text-white hover:bg-[#e64e00]"
                    : "bg-[#dedbd6] text-[#111111] hover:bg-[#cbc7c0]"
                } ${togglingAi ? "opacity-60 cursor-not-allowed" : ""}`}
                aria-pressed={aiEnabled}
              >
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${aiEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"}`} aria-hidden />
                Valéria IA · {aiEnabled ? "Ativa" : "Pausada"}
              </button>
            )}
            {onToggleFollowup && (
              <button
                type="button"
                onClick={() => onToggleFollowup()}
                disabled={togglingFollowup}
                className={`inline-flex items-center gap-2 rounded-[4px] px-3 py-1.5 text-xs font-medium transition-colors ${
                  followupEnabled
                    ? "bg-[#1e6ee8] text-white hover:bg-[#1a5ec8]"
                    : "bg-[#dedbd6] text-[#111111] hover:bg-[#cbc7c0]"
                } ${togglingFollowup ? "opacity-60 cursor-not-allowed" : ""}`}
                aria-pressed={followupEnabled}
              >
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${followupEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"}`} aria-hidden />
                Follow-up · {followupEnabled ? "Ativo" : "Pausado"}
              </button>
            )}
            <WhatsappWindowIndicator
              expiresAt={conversation.whatsapp_window_expires_at ?? null}
              variant="header"
            />
          </div>
```

Replace it with (removing the Follow-up `{onToggleFollowup && (...)}` block):

```tsx
          <div className="flex items-center gap-2 flex-wrap">
            {onToggleAi && (
              <button
                type="button"
                onClick={() => onToggleAi()}
                disabled={togglingAi}
                className={`inline-flex items-center gap-2 rounded-[4px] px-3 py-1.5 text-xs font-medium transition-colors ${
                  aiEnabled
                    ? "bg-[#ff5600] text-white hover:bg-[#e64e00]"
                    : "bg-[#dedbd6] text-[#111111] hover:bg-[#cbc7c0]"
                } ${togglingAi ? "opacity-60 cursor-not-allowed" : ""}`}
                aria-pressed={aiEnabled}
              >
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${aiEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"}`} aria-hidden />
                Valéria IA · {aiEnabled ? "Ativa" : "Pausada"}
              </button>
            )}
            <WhatsappWindowIndicator
              expiresAt={conversation.whatsapp_window_expires_at ?? null}
              variant="header"
            />
          </div>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors. The `followupEnabled`, `togglingFollowup`, `onToggleFollowup` props remain in the interface (they're still optional and used nowhere else in this file after the removal) — TypeScript won't complain about unused props.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversas/contact-detail.tsx
git commit -m "feat(conversas): remover follow-up duplicado do painel mobile de contato"
```

---

## Self-Review

**Spec coverage:**
- ✅ Header simplificado: apenas nome + Valéria IA + `...` — Task 1
- ✅ Dropdown `...` com Follow-up toggle e Finalizar conversa — Task 1
- ✅ Canal removido do header (já estava no contact-detail) — Task 1 (removido com a limpeza)
- ✅ `onMarkRead` propagado corretamente — Tasks 2 + 3
- ✅ Mobile adaptado: dropdown funciona no mobile via mesmo `ChatHeader` — Task 1
- ✅ Follow-up removido do painel mobile duplicado — Task 4

**Placeholder scan:** Nenhum TBD/TODO encontrado. Todos os steps têm código real.

**Type consistency:**
- `onMarkRead?: () => void | Promise<void>` definido em `ChatHeaderProps` (Task 1), `ChatViewProps` (Task 2), e chamado em `page.tsx` (Task 3) — consistente.
- `tags` prop mantida em `ChatHeaderProps` para não quebrar os call-sites existentes (não causa erro TypeScript).

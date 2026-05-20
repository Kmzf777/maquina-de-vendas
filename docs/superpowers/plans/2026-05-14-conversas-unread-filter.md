# Conversas — Filtro Não Lidas + Fix Carrossel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **IMPORTANT:** Any agent working on frontend files MUST invoke the `frontend-design` skill before making changes.

**Goal:** Adicionar aba "Não lidas · N" ao carrossel de tabs do ChatList e adicionar setas de navegação no desktop para o carrossel funcionar corretamente.

**Architecture:** Todas as mudanças ficam em `frontend/src/components/conversas/chat-list.tsx`. O filtro é client-side puro usando o campo `unread_count` já presente em cada `Conversation`. A aba "Não lidas" é renderizada como item especial antes das `CONVERSATION_TABS`. As setas usam `useRef` no container scrollável + eventos `scroll`/`resize` para mostrar/ocultar os controles.

**Tech Stack:** React 18, Next.js App Router, Tailwind CSS, TypeScript

---

## File Map

| Ação | Arquivo |
|------|---------|
| Modify | `frontend/src/components/conversas/chat-list.tsx` |

---

### Task 1: Criar branch de feature

**Files:**
- (nenhum arquivo alterado)

- [ ] **Step 1: Criar e entrar na branch**

```bash
git checkout -b feature/conversas-unread-filter
```

Expected: `Switched to a new branch 'feature/conversas-unread-filter'`

---

### Task 2: Adicionar lógica do filtro "nao_lidas" (sem tocar no JSX ainda)

**Files:**
- Modify: `frontend/src/components/conversas/chat-list.tsx`

> **REQUIRED:** Invoke `frontend-design` skill before making changes.

- [ ] **Step 1: Atualizar imports — adicionar `useRef`, `useCallback`, `useEffect`**

Linha 1 atual:
```tsx
import { useState } from "react";
```

Substituir por:
```tsx
import { useState, useRef, useCallback, useEffect } from "react";
```

- [ ] **Step 2: Adicionar `unreadTotal` e refs de scroll após `const [search, setSearch] = useState("")`**

Após `const [search, setSearch] = useState("");`, inserir:

```tsx
const unreadTotal = conversations.filter((c) => (c.unread_count ?? 0) > 0).length;

const tabsScrollRef = useRef<HTMLDivElement>(null);
const [canScrollLeft, setCanScrollLeft] = useState(false);
const [canScrollRight, setCanScrollRight] = useState(false);

const updateScrollButtons = useCallback(() => {
  const el = tabsScrollRef.current;
  if (!el) return;
  setCanScrollLeft(el.scrollLeft > 1);
  setCanScrollRight(el.scrollLeft < el.scrollWidth - el.clientWidth - 1);
}, []);

useEffect(() => {
  const el = tabsScrollRef.current;
  if (!el) return;
  updateScrollButtons();
  el.addEventListener("scroll", updateScrollButtons);
  window.addEventListener("resize", updateScrollButtons);
  return () => {
    el.removeEventListener("scroll", updateScrollButtons);
    window.removeEventListener("resize", updateScrollButtons);
  };
}, [updateScrollButtons]);
```

- [ ] **Step 3: Inserir `"nao_lidas"` no bloco de filtro `filteredConversations`**

Localizar o bloco (começa com `const filteredConversations = conversations`):

```tsx
const filteredConversations = conversations
  .filter((conv) => {
    if (activeTab === "todos") return true;
    if (activeTab === "pessoal") return !conv.leads;
    return conv.leads?.stage === activeTab;
  })
```

Substituir por:

```tsx
const filteredConversations = conversations
  .filter((conv) => {
    if (activeTab === "nao_lidas") return (conv.unread_count ?? 0) > 0;
    if (activeTab === "todos") return true;
    if (activeTab === "pessoal") return !conv.leads;
    return conv.leads?.stage === activeTab;
  })
```

- [ ] **Step 4: Verificar TypeScript sem erros**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sem erros de compilação

- [ ] **Step 5: Commit de lógica**

```bash
git add frontend/src/components/conversas/chat-list.tsx
git commit -m "feat(conversas): add nao_lidas filter logic and scroll state"
```

---

### Task 3: Renderizar aba especial + setas de navegação no carrossel

**Files:**
- Modify: `frontend/src/components/conversas/chat-list.tsx`

> **REQUIRED:** Invoke `frontend-design` skill before making changes.

- [ ] **Step 1: Substituir o bloco inteiro do carrossel de tabs**

Localizar o bloco atual (começa com `{/* Tabs — horizontal carousel */}`):

```tsx
{/* Tabs — horizontal carousel */}
<div className="pb-2 overflow-x-auto [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
  <div className="flex gap-1 px-3 w-max">
    {CONVERSATION_TABS.map((tab) => (
      <button
        key={tab.key}
        onClick={() => onTabChange(tab.key)}
        className={`px-3 py-1.5 rounded-[4px] text-[12px] transition-colors whitespace-nowrap flex-shrink-0 ${
          activeTab === tab.key
            ? "bg-[#111111] text-white"
            : "text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/30"
        }`}
      >
        {tab.label}
      </button>
    ))}
  </div>
</div>
```

Substituir por:

```tsx
{/* Tabs — horizontal carousel */}
<div className="relative pb-2">
  {/* Seta esquerda — desktop only */}
  <button
    onClick={() => tabsScrollRef.current?.scrollBy({ left: -120, behavior: "smooth" })}
    aria-label="Rolar tabs para esquerda"
    className={`hidden md:flex absolute left-0 top-1/2 -translate-y-1/2 z-10 w-6 h-6 items-center justify-center bg-[#f0ede8] text-[#7b7b78] hover:text-[#111111] transition-opacity ${
      canScrollLeft ? "opacity-100" : "opacity-0 pointer-events-none"
    }`}
  >
    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
    </svg>
  </button>

  <div
    ref={tabsScrollRef}
    className="overflow-x-auto [&::-webkit-scrollbar]:hidden [scrollbar-width:none]"
  >
    <div className="flex gap-1 px-3 w-max">
      {/* Aba especial: Não lidas */}
      <button
        onClick={() => onTabChange("nao_lidas")}
        className={`px-3 py-1.5 rounded-[4px] text-[12px] transition-colors whitespace-nowrap flex-shrink-0 flex items-center gap-1.5 ${
          activeTab === "nao_lidas"
            ? "bg-[#111111] text-white"
            : "text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/30"
        }`}
      >
        Não lidas
        {unreadTotal > 0 && (
          <span className="inline-flex min-w-[16px] items-center justify-center rounded-full bg-[#ff5600] px-1 text-[10px] font-semibold text-white leading-none">
            {unreadTotal > 9 ? "9+" : unreadTotal}
          </span>
        )}
      </button>
      {CONVERSATION_TABS.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onTabChange(tab.key)}
          className={`px-3 py-1.5 rounded-[4px] text-[12px] transition-colors whitespace-nowrap flex-shrink-0 ${
            activeTab === tab.key
              ? "bg-[#111111] text-white"
              : "text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/30"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  </div>

  {/* Seta direita — desktop only */}
  <button
    onClick={() => tabsScrollRef.current?.scrollBy({ left: 120, behavior: "smooth" })}
    aria-label="Rolar tabs para direita"
    className={`hidden md:flex absolute right-0 top-1/2 -translate-y-1/2 z-10 w-6 h-6 items-center justify-center bg-[#f0ede8] text-[#7b7b78] hover:text-[#111111] transition-opacity ${
      canScrollRight ? "opacity-100" : "opacity-0 pointer-events-none"
    }`}
  >
    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
    </svg>
  </button>
</div>
```

- [ ] **Step 2: Verificar que não há bloco duplicado de tabs**

```bash
grep -c "nao_lidas" frontend/src/components/conversas/chat-list.tsx
```

Expected: `2` (um no filtro, um no JSX da aba)

- [ ] **Step 3: Verificar TypeScript sem erros**

```bash
cd frontend && npx tsc --noEmit
```

Expected: sem erros de compilação

- [ ] **Step 4: Verificar manualmente no browser**

Confirmar:
- A aba "Não lidas" aparece antes de "Todos"
- Badge laranja mostra o número correto de conversas não lidas
- Clicar na aba filtra a lista para `unread_count > 0`
- Clicar em "Todos" ou outra aba volta ao comportamento normal
- Desktop: seta `›` aparece quando há tabs além da borda direita
- Desktop: clicar `›` rola o carrossel suavemente
- Desktop: seta `‹` aparece ao rolar para direita; clicar volta para esquerda
- Mobile: setas não são visíveis

- [ ] **Step 5: Commit final**

```bash
git add frontend/src/components/conversas/chat-list.tsx
git commit -m "feat(conversas): render Nao Lidas tab and desktop carousel arrows"
```

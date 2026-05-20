# Spec: Filtro de Não Lidas + Fix Carrossel de Tabs — /conversas

**Data:** 2026-05-14  
**Status:** Aprovado  
**Escopo:** `frontend/src/components/conversas/chat-list.tsx`

---

## Problema

A página `/conversas` não oferece forma de filtrar conversas com mensagens não lidas (badge laranja `unread_count > 0`). Adicionalmente, o carrossel de tabs no desktop não possui controles de navegação, impossibilitando acessar todas as tabs em telas menores.

---

## Solução

### 1. Aba "Não lidas" com contador dinâmico

- Renderizar uma tab especial **antes** das `CONVERSATION_TABS` no carrossel horizontal.
- Label: `Não lidas · N` onde N é calculado em runtime como `conversations.filter(c => c.unread_count > 0).length`.
- Quando N = 0, exibir apenas `Não lidas` (sem ` · 0`).
- Key: `"nao_lidas"` — tratado no `filteredConversations` com `conv.unread_count > 0`.
- Visual idêntico às outras tabs: fundo `#111111` + texto branco quando ativa; cinza quando inativa.
- Badge de contador: bolinha laranja `bg-[#ff5600]` com número em branco, inline após o texto, só visível quando N > 0.
- A constante `CONVERSATION_TABS` em `lib/constants.ts` **não é modificada**.

### 2. Fix do carrossel de tabs no desktop

- Container atual: `overflow-x-auto` com scrollbar oculta — funciona em mobile (touch), mas sem controles no desktop.
- Solução: adicionar botões `‹` e `›` nas extremidades do carrossel, visíveis **apenas no desktop** (`md:`), que executam `scrollBy({ left: ±120, behavior: 'smooth' })` no elemento scrollável via `useRef`.
- Botões ficam desabilitados (opacity-50, pointer-events-none) quando não há mais conteúdo para rolar (detectado via `scrollLeft` e `scrollWidth - clientWidth`).
- Estado de visibilidade dos botões atualizado em `scroll` + `resize` events.

---

## Arquitetura

Todas as mudanças ficam em **um único arquivo**: `frontend/src/components/conversas/chat-list.tsx`.

- Nenhuma mudança em `page.tsx`, `constants.ts`, `types.ts` ou API.
- O filtro é puramente client-side: `conversations` já contém `unread_count` em cada item.
- O `activeTab === "nao_lidas"` é tratado no bloco `filteredConversations` existente.

---

## Comportamento de atualização

Quando o usuário abre uma conversa na aba "Não lidas":
- O `unread_count` zera via `handleMarkRead` (lógica existente em `page.tsx`).
- O Supabase realtime já re-fetcha as conversas.
- A conversa some da lista "Não lidas" automaticamente no próximo render.

---

## Fora de escopo

- Mudança no comportamento de quando `unread_count` é zerado (resposta ou "Finalizar Conversa") — comportamento existente mantido.
- Persistência do filtro entre sessões.
- Filtros adicionais (IA ativa, follow-up, etc.).

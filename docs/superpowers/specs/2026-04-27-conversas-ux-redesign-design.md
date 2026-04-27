# Conversas UX Redesign — Design Spec

**Data:** 2026-04-27
**Branch:** feat/conversas-ux-redesign
**Status:** Aprovado

---

## Contexto

O sistema `/conversas` tem funcionalidade completa (24h window enforcement, realtime, event cards, IA vs vendedor, tags) mas o código está concentrado em dois arquivos grandes (`chat-view.tsx`, `chat-list.tsx`) e faltam elementos essenciais de UX: separador de dia nas mensagens, cronômetro visível da janela 24h, preview da última mensagem nos cards, scroll-to-bottom, agrupamento visual e indicador de remetente nas bolhas.

---

## Objetivo

Refinar a experiência de chat para proximidade com WhatsApp/Intercom, extraindo componentes reutilizáveis e adicionando os elementos de UX identificados, sem alterar lógica de negócio existente.

---

## Escopo

| Feature | Arquivo(s) |
|---------|-----------|
| Cronômetro 24h no header | `chat-header.tsx` (novo) |
| Separador de dia | `day-separator.tsx` (novo) |
| Bolha com badge remetente + agrupamento | `message-bubble.tsx` (novo) |
| Lista de mensagens com separadores + scroll button | `message-list.tsx` (novo) |
| Preview de última mensagem nos cards | `chat-list.tsx` (editar) + API |
| Empty state | `chat-view.tsx` (editar) |
| Orquestração slim | `chat-view.tsx` (editar) |

---

## Arquitetura de Componentes

```
ChatView (orquestrador, mantém estado)
├── ChatHeader              ← novo
├── WindowBanner (inline)   ← banner 24h permanece inline em ChatView
├── MessageList             ← novo
│   ├── DaySeparator        ← novo
│   ├── MessageBubble       ← novo
│   └── EventCard           ← existente (mantido)
├── ScrollToBottomButton    ← dentro de MessageList
├── WindowReactivatePanel   ← existente (mantido)
└── InputArea (inline)      ← simples demais para extrair
```

---

## Componentes Detalhados

### 1. `ChatHeader` — `frontend/src/components/conversas/chat-header.tsx`

**Responsabilidade:** Renderizar o header do chat com identidade do lead e status da janela 24h.

**Props:**
```typescript
interface ChatHeaderProps {
  conversation: Conversation;
  tags: Tag[];
}
```

**Layout (esquerda → direita):**
- Avatar circular com inicial do lead (cor por stage, igual ao atual)
- Nome do lead + telefone (2 linhas)
- Lead tags (badges coloridos)
- Channel badge (ex: "Canastra Meta")
- **Cronômetro 24h** (só para `provider = "meta_cloud"`):
  - `open`: texto verde "Janela · 18h 24min" com ícone ⏳
  - `expiring`: texto âmbar "Expira em 1h 12min" com ícone ⏱ (pisca suavemente)
  - `closed`: texto vermelho "🔒 Janela fechada"
  - `n/a`: não renderiza nada
- O cronômetro usa `windowExpiresInMs` + `formatTimeRemaining` do `window-status.ts`
- Atualiza a cada 60s via `setInterval` (igual ao chat-view atual)

---

### 2. `DaySeparator` — `frontend/src/components/conversas/day-separator.tsx`

**Responsabilidade:** Exibir um chip centralizado com a data quando a data muda entre mensagens.

**Props:**
```typescript
interface DaySeparatorProps {
  date: Date;
}
```

**Lógica de label (PT-BR, sem lib externa):**
- Mesmo dia → `"Hoje"`
- Dia anterior → `"Ontem"`
- Mesmo ano → `"27 de abril"` (`toLocaleDateString("pt-BR", { day: "numeric", month: "long" })`)
- Ano diferente → `"27 de abril de 2024"`

**Visual:** linha horizontal fina nas laterais + chip com texto cinza claro no centro (estilo WhatsApp).

---

### 3. `MessageBubble` — `frontend/src/components/conversas/message-bubble.tsx`

**Responsabilidade:** Renderizar uma bolha de mensagem com conteúdo, timestamp e badge de remetente.

**Props:**
```typescript
interface MessageBubbleProps {
  message: Message;
  isGrouped: boolean;   // true = mensagem consecutiva do mesmo remetente (< 2min)
}
```

**Comportamento:**
- `isFromMe = message.role === "assistant"` → bolha à direita, fundo `#111111`, texto branco
- `!isFromMe` → bolha à esquerda, fundo branco, borda sutil
- `isGrouped = true` → margem superior de `2px` em vez de `8px`
- **Badge de remetente** (abaixo do timestamp, texto 10px, opacidade 60%):
  - `sent_by === "agent"` → `"IA"`
  - `sent_by === "seller"` → `"Vendedor"`
  - `role === "user"` → sem badge
- Timestamp: `HH:MM` (função `formatTime` existente)
- Mensagens temporárias (id começa com `temp_`): timestamp substituído por `"Enviando..."`

---

### 4. `MessageList` — `frontend/src/components/conversas/message-list.tsx`

**Responsabilidade:** Orquestrar a renderização de mensagens com separadores de dia, agrupamento, scroll automático e botão scroll-to-bottom.

**Props:**
```typescript
interface MessageListProps {
  messages: Message[];
  loading: boolean;
}
```

**Lógica de separadores de dia:**
Antes de renderizar cada mensagem, compara a data da mensagem atual com a anterior. Se mudou o dia, injeta `<DaySeparator>`.

**Lógica de agrupamento:**
Uma mensagem é `isGrouped = true` se:
- A mensagem anterior tem o mesmo `role`
- O intervalo entre `created_at` é menor que 2 minutos

**Scroll-to-bottom button:**
- Detecta se o scroll está a mais de 100px do final via `onScroll` no container
- Se sim, exibe botão fixo no canto inferior direito da área de mensagens
- Badge numérico vermelho mostra quantas mensagens chegaram enquanto o usuário estava scrollado para cima (usando ref para contar mensagens novas vs posição de scroll)
- Clique: scroll suave até o final + limpa badge

**Refs expostos:** o componente aceita um `bottomRef` via `useImperativeHandle` para o auto-scroll do ChatView.

---

### 5. `chat-list.tsx` — Preview de última mensagem

**Mudança:** Adicionar uma terceira linha no card com o conteúdo da última mensagem truncado em 1 linha.

**Dado necessário:** `last_message_text: string | null` na `Conversation`.

**API (`/api/conversations/route.ts`):**
- Para conversas meta_cloud: adicionar ao select de Supabase a mensagem mais recente por `conversation_id`:
  ```
  messages(content, created_at, role)
  ```
  Com `.order("created_at", { ascending: false }).limit(1)` no join — ou via RPC/subquery se o client não suportar ordered joins inline.
- Para Evolution: usar o campo `lastMessage.content` que já vem das chats Evolution, se disponível, ou `null`.
- O tipo `Conversation` em `types.ts` ganha: `last_message_text: string | null`

**Rendering no card:**
```
[Nome]                    [14:32]
[Canal] [telefone]
[preview da última mensagem truncada...]   ← novo
```
Texto `text-[12px] text-[#7b7b78] truncate` (1 linha). Prefixo discreto se for da IA: `"IA: texto..."`.

---

### 6. Empty State — `chat-view.tsx`

Quando nenhuma conversa está selecionada, o painel central mostra:
- Ícone de balão de chat (SVG simples, cinza claro, ~48px)
- Título: `"Selecione uma conversa"`
- Subtexto: `"X conversas abertas"` (contagem dinâmica passada como prop do pai)

---

### 7. `chat-view.tsx` (slim)

Após a extração:
- Mantém: estado de texto, envio, otimismo, lógica de janela 24h (`windowStatus`, `isInputBlocked`, `showReactivatePanel`, ticker de 60s)
- Delega: header → `ChatHeader`, mensagens → `MessageList`, banner → `WindowBanner` existente
- Reduz de ~250 linhas para ~120 linhas

---

## API: `last_message_text`

**Arquivo:** `frontend/src/app/api/conversations/route.ts`

Para o select de meta_cloud, adicionar no join de leads/channels uma subquery que retorna o conteúdo da última mensagem. Abordagem: executar um segundo fetch de Supabase para o `last_message_text` por `conversation_id` em batch após buscar as conversas, ou usar uma view/RPC.

**Abordagem escolhida:** query com `DISTINCT ON` via Supabase `rpc` ou SQL direto no route handler (service key):
```sql
SELECT DISTINCT ON (conversation_id)
  conversation_id, content, role, created_at
FROM messages
WHERE conversation_id = ANY(ARRAY['id1','id2',...])
ORDER BY conversation_id, created_at DESC
```

Executado via `supabase.rpc("get_last_messages", { conv_ids: [...] })` com uma função Postgres simples, ou emulado com `.from("messages").select(...).in("conversation_id", ids)` + deduplicação client-side limitando a `ids.length * 1` rows por `.limit(ids.length)` após ordenação. A função RPC é preferida por eficiência.

A função RPC `get_last_messages` é criada via migration:
```sql
CREATE OR REPLACE FUNCTION get_last_messages(conv_ids uuid[])
RETURNS TABLE(conversation_id uuid, content text, role text)
LANGUAGE sql STABLE AS $$
  SELECT DISTINCT ON (conversation_id) conversation_id, content, role
  FROM messages
  WHERE conversation_id = ANY(conv_ids)
  ORDER BY conversation_id, created_at DESC;
$$;
```

Arquivo: `backend/migrations/20260427_get_last_messages_rpc.sql`

---

## Arquivos Afetados

| Arquivo | Tipo |
|---------|------|
| `frontend/src/components/conversas/chat-header.tsx` | Novo |
| `frontend/src/components/conversas/day-separator.tsx` | Novo |
| `frontend/src/components/conversas/message-bubble.tsx` | Novo |
| `frontend/src/components/conversas/message-list.tsx` | Novo |
| `frontend/src/components/conversas/chat-view.tsx` | Editar |
| `frontend/src/components/conversas/chat-list.tsx` | Editar |
| `frontend/src/app/api/conversations/route.ts` | Editar |
| `frontend/src/lib/types.ts` | Editar |

---

## O que NÃO muda

- Lógica de negócio do envio de mensagens
- Lógica do 24h window (banner, input block, WindowReactivatePanel)
- Realtime subscription (`useRealtimeMessages`)
- EventCard
- Cores, fontes e design tokens existentes
- Backend

---

## Notas de Execução

- Todos os agentes implementadores devem usar a skill `frontend-design`
- Sem abrir servidor de desenvolvimento para teste
- Sem adicionar dependências externas (zero libs novas)
- TypeScript estrito — sem `any`

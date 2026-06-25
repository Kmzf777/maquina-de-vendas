# Busca de mensagens em /conversas (estilo WhatsApp) — Design

**Data:** 2026-06-25
**Branch:** `feat/conversas-message-search`
**Status:** Aprovado (spec + plano pré-aprovados pelo usuário)

---

## 1. Problema

Hoje a caixa "Buscar conversa..." em `frontend/src/components/conversas/chat-list.tsx`
filtra **apenas** a lista de conversas já carregada, por **nome/telefone** do contato.
Não é possível buscar pelo **conteúdo das mensagens** trocadas, como no WhatsApp
("buscar por palavra-chave ou frase").

## 2. Objetivo

Permitir busca por palavra-chave ou frase dentro do conteúdo das mensagens,
apresentada em duas seções (igual ao WhatsApp): **Conversas** (contatos que casam)
e **Mensagens** (mensagens cujo texto casa, com trecho e contador). Ao clicar num
resultado de mensagem, abrir a conversa e **rolar até a mensagem exata, destacando-a**.

## 3. Decisões do usuário (brainstorming)

| Decisão | Escolha |
|---|---|
| O que a busca encontra | Conteúdo das mensagens **+** contato (nome/telefone) |
| Clique no resultado de mensagem | **Pular para a mensagem + destacar** |
| Quais mensagens entram na busca | **Só do cliente** (`role = 'user'`) |
| Apresentação | **Duas seções**: "Conversas" e "Mensagens" (snippet + contador) |

## 4. Contexto técnico relevante (já existe no código)

- **Lista de conversas é totalmente carregada no cliente.** `GET /api/conversations`
  (`frontend/src/app/api/conversations/route.ts`) não aplica `limit`/`range` — retorna
  todas as conversas dos canais permitidos. Logo, o filtro de **contato** pode continuar
  client-side e instantâneo.
- **A conversa inteira é carregada no chat.** `useRealtimeMessages` e a rota de mensagens
  buscam todas as mensagens da conversa (sem paginação). Portanto, qualquer mensagem-alvo
  já está no DOM quando a conversa abre.
- **Jump-to-message + highlight já existe.** `MessageListHandle.scrollToMessage(id)`
  (`frontend/src/components/conversas/message-list.tsx`) rola até a mensagem e aplica
  highlight amarelo por 1,5s. `ChatView` já mantém `messageListRef`.
- **Escopo de segurança por canal.** Toda rota de conversas resolve
  `getAllowedChannelIds()` (`frontend/src/lib/supabase/channel-access.ts`):
  `null` = admin (vê tudo), `string[]` = vendedor restrito aos seus canais,
  `[]` = nenhum canal. Falha de auth lança `ChannelAccessError` → responder **401**,
  nunca `[]` silencioso (apaga a UI).

## 5. Arquitetura

### 5.1 Seção "Conversas" (contatos) — client-side
Mantém a lógica atual de `chat-list.tsx`: filtra `conversations` (já carregadas) por
`leads.name` / `leads.phone`. Instantânea, sem rede. Inclui conversas Evolution
(que são client-side). Continua respeitando o filtro de canal e abas já aplicado à lista.

### 5.2 Seção "Mensagens" (conteúdo) — server-side

**Banco (migration nova em `supabase/migrations/20260625_search_customer_messages.sql`):**

1. `CREATE EXTENSION IF NOT EXISTS pg_trgm;` e `CREATE EXTENSION IF NOT EXISTS unaccent;`
2. Wrapper imutável (necessário para indexar `unaccent`, que não é imutável por padrão):
   ```sql
   CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
     LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
     AS $$ SELECT unaccent('unaccent', $1) $$;
   ```
3. Índice GIN trigram **parcial** (só mensagens do cliente — casa com o filtro da busca):
   ```sql
   CREATE INDEX IF NOT EXISTS idx_messages_content_trgm
     ON messages USING gin (f_unaccent(lower(content)) gin_trgm_ops)
     WHERE role = 'user';
   ```
4. RPC `search_customer_messages(search_query text, channel_ids uuid[], max_results int)`:
   - Filtra `m.role = 'user'` e `f_unaccent(lower(m.content)) LIKE '%' || f_unaccent(lower(search_query)) || '%'`.
   - `channel_ids IS NULL` ⇒ sem restrição (admin); senão `c.channel_id = ANY(channel_ids)`.
   - Agrega **uma linha por conversa**: id da conversa, id e conteúdo da mensagem
     **mais recente** que casou (para o snippet), `created_at` dessa mensagem,
     e `match_count` (total de mensagens do cliente que casaram naquela conversa).
   - Junta `leads` (nome/telefone) e `channels` (nome) para a UI.
   - Ordena por `created_at` da mensagem mais recente que casou, desc. `LIMIT max_results`.
   - `SECURITY INVOKER` não basta (RLS); usar `SECURITY DEFINER` mas **sempre** filtrar por
     `channel_ids` recebidos da rota (a rota é a fonte de verdade do escopo). Marcar
     `STABLE`. (Padrão dos RPCs existentes: `get_last_messages`, `get_lead_deals`.)

   Colunas retornadas: `conversation_id uuid, message_id uuid, snippet text,
   match_created_at timestamptz, match_count bigint, lead_name text, lead_phone text,
   channel_id uuid, channel_name text`.

**Rota (nova em `frontend/src/app/api/conversations/search/route.ts`):**
`GET /api/conversations/search?q=<query>&channel_id=<opcional>`
- Resolve `getAllowedChannelIds` (igual a `/api/conversations`); `ChannelAccessError` → 401.
- `q` com menos de 2 caracteres (após trim) ⇒ `200 []`.
- Se houver `channel_id`, intersecta com os canais permitidos (vendedor não pode burlar
  escopo passando channel_id alheio); admin restringe ao `channel_id` se fornecido.
- `allowedChannelIds === []` (vendedor sem canais) ⇒ `200 []`.
- Chama `supabase.rpc('search_customer_messages', { search_query, channel_ids, max_results: 50 })`.
- Erro do RPC ⇒ `500` (nunca `[]` silencioso).
- Retorna o array de resultados como JSON.

### 5.3 Fluxo de UI

```
chat-list.tsx
  query >= 2 chars  ──debounce 300ms / abort latest-wins──>  GET /api/conversations/search
  render:
    Seção "Conversas" (contatos filtrados client-side)
    Seção "Mensagens" (resultados do servidor: avatar, nome, snippet com termo destacado,
                        contador "N mensagens", horário)
  clique numa Mensagem ──> onSelectMessageResult(conversationId, messageId)

page.tsx (ConversasPage)
  onSelectMessageResult:
    - acha a Conversation na lista carregada (presente: lista vem completa)
    - setSelectedConversation(conv); setPendingScrollMessageId(messageId)

chat-view.tsx
  prop targetMessageId
  quando loading === false e targetMessageId definido:
    messageListRef.current?.scrollToMessage(targetMessageId)
    limpa o targetMessageId (dispara só uma vez)
```

**Destaque do termo no snippet e na bolha:** o snippet na seção "Mensagens" envolve o
termo casado em `<mark>`. Na bolha, mantém-se o highlight amarelo de bolha já existente
(`scrollToMessage`); destacar o termo dentro da bolha é incremento opcional (passar a
query para `MessageBubble` e envolver matches), sem bloquear a entrega.

## 6. Estados e bordas

- **Mínimo 2 caracteres** para acionar a busca server-side (evita varredura gigante).
- **Debounce 300ms** + `AbortController` latest-wins (mesmo padrão de `fetchConversations`).
- **Loading** sutil na seção "Mensagens" enquanto a busca corre.
- **Vazios:** cada seção tem seu próprio "nenhum resultado". Se ambas vazias e há query:
  "Nenhuma conversa ou mensagem encontrada."
- **Evolution:** a busca por **conteúdo** cobre só conversas no banco (meta_cloud);
  mensagens Evolution não estão no banco (coerente com CLAUDE.md §6). A seção
  **Conversas** continua cobrindo Evolution (é client-side).
- **Segurança:** a rota NUNCA confia em `channel_id` do cliente sem intersectar com os
  canais permitidos. Sem query ou sem canais ⇒ `[]`. Falha de auth ⇒ `401`.
- **Performance:** índice parcial trigram; `LIMIT 50` conversas; agregação no banco.

## 7. Não-objetivos (YAGNI)

- Sem busca em mensagens da IA/vendedor (decisão: só cliente).
- Sem busca full-text com stemming/ranking — substring acento-insensível é o que casa
  com o comportamento do WhatsApp.
- Sem paginação infinita de resultados de mensagem (LIMIT 50 cobre o uso real).
- Sem busca em mídia/anexos por OCR/transcrição.

## 8. Testes

- **Backend/RPC:** teste de integração (se houver harness de DB) ou validação manual via
  SQL: casa acento-insensível, respeita `channel_ids`, agrega `match_count`, ordena por
  recência, `LIMIT`. No mínimo, smoke manual documentado.
- **Rota:** testes do comportamento de escopo (401 em falha de auth, `[]` com q curto,
  interseção de channel_id, 500 em erro do RPC). Seguir padrão de testes existentes do
  frontend, se houver; senão, validação manual documentada.
- **UI:** validação manual — duas seções, debounce, clique pula+destaca, vazios, mobile.

## 9. Arquivos afetados

**Novos:**
- `supabase/migrations/20260625_search_customer_messages.sql`
- `frontend/src/app/api/conversations/search/route.ts`
- (talvez) `frontend/src/components/conversas/message-search-results.tsx` (seção "Mensagens")

**Alterados:**
- `frontend/src/components/conversas/chat-list.tsx` — duas seções, fetch debounced, callback.
- `frontend/src/app/(authenticated)/conversas/page.tsx` — estado `pendingScrollMessageId`,
  handler `onSelectMessageResult`, passar `targetMessageId` ao `ChatView` (desktop e mobile).
- `frontend/src/components/conversas/chat-view.tsx` — prop `targetMessageId` + efeito de scroll.
- (opcional) `frontend/src/components/conversas/message-bubble.tsx` — destaque do termo.

## 10. Pendências pós-implementação (convenção do projeto)

- Aplicar a migration `20260625_search_customer_messages.sql` no Supabase (manual).
- Smoke test em produção após push.

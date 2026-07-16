# Opt6 + Opt7 + P5 — Frontend: modularização, paginação do chat e React Query

**Data:** 2026-07-10
**Status:** aprovado para implementação (escopo estrito: frontend)

## Opt6 — Quebrar `cadence-flow-builder.tsx` (1834 linhas)

Único consumidor externo: `campanhas/cadencias/[id]/page.tsx` importa `CadenceFlowBuilder` — a quebra é invisível para o app se o arquivo atual virar barrel.

Corte em `components/campaigns/cadence-flow/` (ordem de dependência sem ciclos):

| Arquivo | Migra | Interface |
|---|---|---|
| `types.ts` | PaletteItem, Flow*/FlowBuilderData, Test*, InspectorProps | só tipos |
| `constants.ts` | FONT_STYLE, NODE_W, NODE_META, STATUS_*, TRIGGER_*/ACTION_* labels+icons, QUICK_ADD_ITEMS, PALETTE_* | consts nomeadas |
| `helpers.ts` | getDefaultConfig, resolveNodeIcon, nodeDetail, toRFNode, toRFEdges | funções puras |
| `graph-elements.tsx` | DeletableEdge, QuickAddButton, CampaignFlowNode, PaletteItemComp, NODE_TYPES/EDGE_TYPES **+ a ponte module-level** | ver abaixo |
| `inspector.tsx` | Inspector (666–1141) — já 100% via props | corte trivial |
| `index.tsx` | FlowBuilderInner + wrapper CadenceFlowBuilder | export público |

**Ponte module-level** (`_addNodeBelow`/`_deleteEdge`/`_selectNode`/`_dragPayload` — necessária porque nós custom do React Flow não recebem props do builder): encapsular num objeto `flowBridge` com `setFlowHandlers({...})` / `setDragPayload()/takeDragPayload()` exportados por `graph-elements.tsx`. Mantém o padrão atual (menor risco) sem `let` globais soltos; migrar para Context fica fora de escopo.

`cadence-flow-builder.tsx` reduz-se a `export { CadenceFlowBuilder } from "./cadence-flow"`. Nenhuma mudança de comportamento; nenhum consumidor tocado.

## Opt7 — Paginação e memoização do chat

**Payload de `/api/conversations` intacto** — mudanças restritas às mensagens.

### `use-realtime-messages.ts`
- Fetch inicial ganha `.limit(100)` (a query já é `desc` + reverse — as 100 MAIS RECENTES).
- Novo `loadOlder()`: busca `created_at < oldest` (desc, limit 100) e faz prepend via `normalizeOrder`; expõe `hasMore` (última página cheia) e `loadingOlder`.
- Realtime INSERT inalterado.
- Degradação aceita: busca de mensagem antiga (fora da janela) não rola até ela — `scrollToMessage` já é no-op quando o elemento não existe.

### `message-list.tsx`
- Botão "Carregar anteriores" no topo quando `hasMore`.
- **Prepend seguro:** (a) o badge de não-lidas passa a ancorar no id da ÚLTIMA mensagem (prepend não é mensagem nova); (b) restaurar posição de scroll após prepend (`scrollTop += scrollHeight_novo − scrollHeight_antigo`).
- `MessageBubble` (e `EventCard`) embrulhados em `React.memo`; callbacks passados a eles estabilizados com `useCallback` (senão o memo é inócuo). Com a lista limitada a ~100+páginas e bubbles memoizados, o push realtime re-renderiza O(1) bubbles em vez da thread inteira.

## P5 — React Query em `conversas/page.tsx` (estrito à página)

Dependência nova: `@tanstack/react-query` v5. **Provider local da página** (módulo `conversas/query-provider.tsx`) — não montar no shell; adoção pelo resto do app é iteração futura.

- **Lista:** `useQuery({ queryKey: ["conversations", channelId], queryFn })` com `placeholderData: keepPreviousData` — substitui o trio artesanal AbortController + `fetchSeqRef` latest-wins + `isRefreshing` (o React Query descarta respostas obsoletas por chave e mantém a lista anterior durante troca de filtro e em erro → `listError` vira `isError`).
- **Realtime:** os handlers atuais deixam de chamar `setConversations` e passam a operar no cache: patch local via `queryClient.setQueryData(["conversations", channelId], updater)` (UPDATE conhecido, preview de INSERT de messages) e `invalidateQueries` debounced para o que o patch não cobre (conversa nova/desconhecida) — preservando o corte de egress de 07/07.
- **Seleção derivada:** `selectedConversation` (objeto duplicado, sincronizado à mão em 8 handlers) vira `selectedId: string` + derivação `conversations.find(...)` — elimina TODOS os pares `setConversations`/`setSelectedConversation` espelhados.
- **Mutações otimistas** (mark-read, toggle IA, toggle follow-up, lead update, tags): helper único `patchConversation(id, patch)` sobre `setQueryData` + rollback em erro; os refs de override (`recentlyMarked/Toggled*`) permanecem (continuam necessários contra o realtime).
- **Auxiliares:** channels/tags/leadTags viram `useQuery` simples (mesma página).
- Props/comportamento de `ChatList`/`ChatView`/`ContactDetail` inalterados.

## Verificação

- `npm run test` (135+ casos; consertar qualquer teste afetado de forma adequada), `tsc --noEmit`, `next build` (prova de estabilidade).
- Teste unitário novo para a lógica pura extraível (ex.: helpers do flow em `helpers.ts` são funções puras testáveis; paginação `hasMore`).
- Smoke manual no dev server: conversas carrega, seleção funciona, badge não estoura no prepend.

## Fora de escopo (YAGNI)

Virtualização com lib (react-window) — a paginação + memo resolve o sintoma com risco muito menor; monstros do backend; React Query fora de conversas; Context para a ponte do flow; @sentry/nextjs.

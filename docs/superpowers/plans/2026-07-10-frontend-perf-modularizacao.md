# Frontend: modularização + paginação + React Query — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Executar a spec `2026-07-10-frontend-perf-modularizacao-design.md` (Opt6 + Opt7 + P5) com `npm run test`, `tsc --noEmit` e `next build` verdes.

**Architecture:** Três frentes independentes por arquivos: (A) split do flow-builder guiado pelo mapa de fratura (barrel preserva o import externo único); (B) paginação/memoização do chat; (C) React Query estrito à página conversas.

**Tech Stack:** React 19, Next 16, @xyflow/react, @tanstack/react-query v5 (nova dep), vitest.

## Global Constraints

- Payload de `/api/conversations` intacto; React Query só em conversas; sem react-window; sem tocar backend.
- Ponte do React Flow encapsulada (`flowBridge`), não Context.
- Testes quebrados = consertar de verdade, nunca deletar/skipar.

---

### Task A (Opt6): split do cadence-flow-builder

- [ ] Criar `components/campaigns/cadence-flow/{types.ts,constants.ts,helpers.ts,graph-elements.tsx,inspector.tsx,index.tsx}` migrando os blocos por faixa de linha do mapa de fratura (inventário na spec)
- [ ] `graph-elements.tsx`: substituir as 4 globais por `flowBridge` + `setFlowHandlers()/setDragPayload()/takeDragPayload()`; os 3 useEffect do builder registram via setFlowHandlers
- [ ] `cadence-flow-builder.tsx` vira barrel (1 linha)
- [ ] Teste unitário para helpers puros (`toRFEdges` gera edges next/yes/no; `nodeDetail`/`getDefaultConfig`)
- [ ] `tsc --noEmit` + `npx vitest run` verdes
- [ ] Commit: `refactor(cadence-flow): quebra o builder de 1834 linhas em 6 modulos coesos (barrel preserva import)`

### Task B (Opt7): paginação + memo do chat

- [ ] `use-realtime-messages.ts`: `.limit(100)` no fetch, `loadOlder()` (created_at < oldest, desc, 100, prepend), `hasMore`, `loadingOlder`
- [ ] `message-list.tsx`: botão "Carregar anteriores" (topo, quando hasMore); badge de não-lidas ancorado no id da última mensagem (prepend ≠ novo); restauração de scrollTop pós-prepend; callbacks estabilizados
- [ ] `message-bubble.tsx`/`event-card.tsx`: export com `React.memo`
- [ ] `chat-view.tsx`: repassar hasMore/loadOlder/loadingOlder ao MessageList
- [ ] Teste unitário da lógica de paginação (hasMore por página cheia; merge/dedup do prepend)
- [ ] Vitest + type-check verdes
- [ ] Commit: `perf(chat): janela de 100 mensagens + carregar anteriores + React.memo nos bubbles`

### Task C (P5): React Query em conversas

- [ ] `npm i @tanstack/react-query`
- [ ] `conversas/query-provider.tsx` (QueryClient local da página)
- [ ] `conversas/page.tsx`: lista via useQuery (keepPreviousData); realtime → setQueryData/invalidate debounced; `selectedId` derivado; `patchConversation(id, patch)` único p/ otimistas+rollback; channels/tags/leadTags via useQuery; refs de override mantidos
- [ ] Vitest + type-check verdes (consertar testes afetados)
- [ ] Commit: `refactor(conversas): React Query substitui coordenacao artesanal de estado (P5)`

### Task D: prova de estabilidade + fechamento

- [ ] `npm run test` + `tsc --noEmit` + `next build` (working tree final)
- [ ] Smoke no dev server: /conversas carrega, seleção/patch otimista ok, prepend sem salto
- [ ] Commit specs+plano; relatório final do ciclo; push só com autorização

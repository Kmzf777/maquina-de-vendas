# Kanban Scroll UX — Design Spec

**Data:** 2026-05-24  
**Status:** Aprovado

## Problema

O scroll horizontal do Kanban em `/vendas` apresenta três falhas de UX:

1. O texto da tela é selecionado acidentalmente ao arrastar (comportamento nativo do browser)
2. Sem feedback visual de cursor (`cursor-grab` / `cursor-grabbing`)
3. O hook `useDragScroll` usa `useRef` para `isDragging`, que não causa re-render — a classe `cursor-grabbing` nunca é refletida na UI

## Decisões

- **Manter** a `div` nativa com `overflow-x-auto` (não usar `ScrollArea` do shadcn/ui — combinação com drag-scroll é não-trivial)
- **Não** alterar lógica de DnD dos cards (dnd-kit) nem os componentes de coluna/card

## Escopo

Dois arquivos alterados:

### 1. `frontend/src/hooks/use-drag-scroll.ts`

- Trocar `isDragging: useRef<boolean>` por `isDraggingScroll: useState<boolean>`
- Expor `isDraggingScroll` no retorno do hook para o componente aplicar classe CSS
- `onMouseDown`: `setIsDraggingScroll(true)` + gravar `startX` e `startScrollLeft`
- `onMouseMove`: scroll apenas se `isDraggingScroll` for `true`; manter `e.preventDefault()`
- `onMouseUp` / `onMouseLeave`: `setIsDraggingScroll(false)`
- Guarda `target.closest('[role="button"]')` permanece idêntica

### 2. `frontend/src/app/(authenticated)/vendas/page.tsx`

- Desestruturar `isDraggingScroll` do retorno de `useDragScroll()`
- No container do Kanban (linha ~309): adicionar classes `select-none`, `cursor-grab`, e `cursor-grabbing` condicional ao `isDraggingScroll`

## Critérios de Sucesso

- Texto não é selecionado ao arrastar o fundo do Kanban
- Cursor muda para `grab` em repouso e `grabbing` durante arraste
- Drag-and-drop dos cards de oportunidade continua funcionando sem regressões
- Zero dependências novas instaladas

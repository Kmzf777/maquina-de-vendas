# Spec: Flow Builder UX — Fluidez n8n/Zapier

**Data:** 2026-05-20  
**Status:** Aprovado  
**Branch:** `feat/flow-builder-ux`

---

## Contexto

O flow builder de cadências usa `@xyflow/react` v12 e tem três problemas de UX:

1. **Trackpad** — dois dedos arrastando vertical reconhece como zoom em vez de pan  
2. **Teclado** — `+`/`=`/`-` não funcionam para zoom  
3. **Quick-add** — não há botão `+` no hover dos nós para criar o próximo nó conectado (padrão n8n/Zapier)

Além disso, faltam pequenas camadas de polimento visual: animações de entrada dos nós, MiniMap, snap-to-grid, edge animada durante conexão.

---

## Decisões de Design

| Decisão | Escolha |
|---|---|
| Trackpad pan | `panOnScroll: true` + `panOnScrollMode: Free` |
| Zoom por teclado | `keydown` listener → `zoomIn()` / `zoomOut()` de `useReactFlow()` |
| Quick-add button | Botão `+` CSS-hover abaixo do output handle, abre picker inline |
| Animações | `framer-motion` para fade+scale na entrada de nós |
| Snap | `snapToGrid: true`, `snapGrid: [20, 20]` |
| MiniMap | Canto inferior direito, acima dos Controls |
| Drag acidental | `nodeDragThreshold: 8` |
| Edge em conexão | `connectionLineStyle` animada, tipo `smoothstep` |

---

## Comportamento Detalhado

### Canvas Navigation

- **Trackpad**: dois dedos = pan em qualquer direção. `Ctrl/Cmd + scroll` = zoom.
- **Mouse**: scroll = zoom (mantido). Drag em área vazia = pan (mantido).
- **Teclado**: `=` / `+` = zoom in; `-` = zoom out; `0` = fit view. Listener no `div` wrapper com `useEffect`.
- **Limites**: `minZoom: 0.2`, `maxZoom: 2.5`.

### Node Quick-Add Button

- Aparece **apenas em nós que têm output handle** (não em `end` nodes).
- Posicionado **abaixo do output handle** (center-bottom da card).
- CSS `:hover` sobre o node card anima a visibilidade do botão (`opacity 0→1`, `translateY 4px→0`).
- Clicar abre um **picker inline** (div absoluto) com os tipos de nós disponíveis: Send, Wait, Condition, Action, End.
- Selecionar um tipo → chama `addNodeBelow(sourceNodeId, type, subtype)`:
  - Cria nó 200px abaixo do nó atual (`position_y + 200`)
  - Conecta automaticamente via `onConnect` (cria edge + PATCH backend)
  - Fecha o picker

### Animações com Framer-Motion

- **Entrada de nó**: quando um nó é adicionado ao canvas, ele aparece com `initial={{ opacity: 0, scale: 0.85 }}` → `animate={{ opacity: 1, scale: 1 }}` com `duration: 0.18`, `ease: "easeOut"`.
- Implementado dentro de `CampaignFlowNode` usando `motion.div`.
- **Picker popup**: `AnimatePresence` + `initial={{ opacity: 0, y: -6 }}` → `animate={{ opacity: 1, y: 0 }}`.
- Sem animações de saída de nó (deletar é imediato).

### MiniMap

- Componente `<MiniMap>` do `@xyflow/react` no canto inferior direito.
- Cor de nó: baseada em `NODE_META[type].color`.
- Fundo: `#f5f2ed`.
- Máscara: `rgba(0,0,0,0.06)`.

### Snap to Grid

- `snapToGrid: true`, `snapGrid: [20, 20]`.
- Nodes se alinham ao grid de 20×20 ao soltar.

---

## Arquitetura Frontend

### Arquivo único modificado

`frontend/src/components/campaigns/cadence-flow-builder.tsx`

O arquivo (~770 linhas) será refatorado. Estrutura nova:

```
cadence-flow-builder.tsx
├── Constantes: NODE_META, PALETTE_*, TRIGGER_LABELS, ACTION_LABELS, TRIGGER_ICONS, ACTION_ICONS
├── Helpers: getDefaultConfig, nodeDetail, resolveNodeIcon, toRFNode, toRFEdges
├── CampaignFlowNode (memo) — agora com motion.div + QuickAddButton embutido
│   └── QuickAddButton — botão + picker inline
├── PaletteItemComp — sem mudanças
├── Inspector — sem mudanças
├── FlowBuilderInner — novos hooks e handlers
│   ├── useKeyboardZoom() — custom hook no-op ou inline effect
│   ├── addNodeBelow(sourceId, type, subtype) — novo
│   └── ReactFlow config atualizada
└── CadenceFlowBuilder (export) — sem mudanças
```

### Dependência nova

```
framer-motion
```

Instalação: `npm install framer-motion` no diretório `frontend/`.

### Props ReactFlow atualizadas

```tsx
<ReactFlow
  // ... props existentes mantidas ...
  panOnScroll={true}
  panOnScrollMode={PanOnScrollMode.Free}
  zoomOnScroll={true}
  snapToGrid={true}
  snapGrid={[20, 20]}
  nodeDragThreshold={8}
  minZoom={0.2}
  maxZoom={2.5}
  connectionLineStyle={{ stroke: "#E85D26", strokeWidth: 1.5, strokeDasharray: "5,4" }}
  connectionLineType={ConnectionLineType.SmoothStep}
/>
```

---

## O que NÃO é escopo

- Drag-and-drop da paleta (já funciona via click-to-add)
- Undo/Redo (Ctrl+Z)
- Auto-layout (dagre/elk)
- Múltiplos outputs no quick-add (apenas next_node_id, não yes/no para condition)
- Animação de remoção de nó

---

## Critérios de Sucesso

1. Dois dedos no trackpad deslocam o canvas (não zoomam)
2. `=`/`+` e `-` no teclado controlam zoom; `0` faz fit view
3. Hover em qualquer nó (exceto `end`) mostra botão `+` abaixo
4. Clicar `+` abre picker com tipos; selecionar cria nó conectado abaixo
5. Nós novos entram com animação fade+scale
6. MiniMap visível no canto inferior direito
7. Nodes snappam ao grid de 20px ao soltar

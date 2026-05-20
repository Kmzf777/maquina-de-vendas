# Flow Builder Bugs v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **FRONTEND AGENTS MUST USE:** `superpowers:frontend-design` skill before any implementation.

**Goal:** Corrigir três bugs de interação no flow builder de cadências: QuickAddButton que some, arestas não deletáveis, e clique esquerdo abrindo menu do browser.

**Architecture:** Arquivo único modificado — `cadence-flow-builder.tsx`. Bug 1 é um fix de CSS (1 linha). Bug 2 adiciona `DeletableEdge` (custom edge component) + `deleteEdge` callback + `EdgeContextMenu` inline. Bug 3 usa variável de módulo `_selectNode` (padrão `_dragPayload`) + `onClick` no `motion.div` + `onContextMenu` no wrapper.

**Tech Stack:** Next.js 14 App Router, `@xyflow/react` v12.10.2, `framer-motion`, TypeScript, inline styles.

**Branch:** `fix/flow-builder-interactions-v2`
**Push destino:** `git push origin fix/flow-builder-interactions-v2:master`

---

## Arquivo modificado

```
frontend/src/components/campaigns/cadence-flow-builder.tsx   ← único arquivo
```

---

## Task 1: Bug 1 — Fix gap do QuickAddButton

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx` (linha ~181)

### Contexto

O wrapper do `QuickAddButton` usa `position: absolute; bottom: -38`. Com botão de 26px de altura, a borda superior do wrapper fica 12px ABAIXO da borda inferior do card. Esse gap faz `onMouseLeave` disparar no `motion.div` antes do mouse alcançar o botão.

```
Card (motion.div) bottom = Y
Wrapper top = Y + 12   ← gap de 12px → mouseleave dispara aqui
Button top = Y + 12    ← nunca alcançado
```

**Fix:** `bottom: -38` → `top: "100%"` + `paddingTop: 8`.

---

- [ ] **Step 1: Localizar e corrigir o posicionamento do wrapper**

No arquivo `frontend/src/components/campaigns/cadence-flow-builder.tsx`, encontrar o componente `QuickAddButton` (em torno da linha 178). O `<div>` raiz do retorno tem:

```tsx
style={{
  position: "absolute",
  bottom: -38,
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 20,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 4,
}}
```

Substituir por:

```tsx
style={{
  position: "absolute",
  top: "100%",
  left: "50%",
  transform: "translateX(-50%)",
  paddingTop: 8,
  zIndex: 20,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 4,
}}
```

- [ ] **Step 2: TypeScript check**

```
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\frontend"
npx tsc --noEmit 2>&1
```

Esperado: zero erros.

- [ ] **Step 3: Commit**

```
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA"
git add frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "fix(flow-builder): corrigir gap do QuickAddButton com top:100%"
```

---

## Task 2: Bug 2 — DeletableEdge + deleteEdge + EdgeContextMenu

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx`

### Contexto

Atualmente todas as arestas usam `type: "smoothstep"` (built-in do React Flow). Precisamos trocar para um custom edge type `"deletable"` que renderiza um botão 🗑 no hover e responde a right-click com um mini-menu.

O arquivo já importa de `@xyflow/react`:
```
ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, addEdge,
Connection, Edge, Node, Handle, Position, BackgroundVariant, NodeProps, useReactFlow,
ReactFlowProvider, OnConnect, Panel, MarkerType, NodeMouseHandler, OnNodeDrag,
PanOnScrollMode, ConnectionLineType
```

Precisamos adicionar: `EdgeProps`, `BaseEdge`, `getSmoothStepPath`, `EdgeLabelRenderer`.

O `FlowBuilderInner` já tem:
- `rfEdges`, `setRFEdges`, `setDbNodes` — para o callback `deleteEdge`
- `campaignId` — para o fetch PATCH

---

- [ ] **Step 1: Adicionar imports necessários do @xyflow/react**

Encontrar o bloco de import de `@xyflow/react` (linhas 5-29) e adicionar `EdgeProps`, `BaseEdge`, `getSmoothStepPath`, `EdgeLabelRenderer` ao final da lista:

```typescript
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Edge,
  Node,
  Handle,
  Position,
  BackgroundVariant,
  NodeProps,
  useReactFlow,
  ReactFlowProvider,
  OnConnect,
  Panel,
  MarkerType,
  NodeMouseHandler,
  OnNodeDrag,
  PanOnScrollMode,
  ConnectionLineType,
  EdgeProps,
  BaseEdge,
  getSmoothStepPath,
  EdgeLabelRenderer,
} from "@xyflow/react";
```

- [ ] **Step 2: Adicionar CSS para o botão de delete no hover da aresta**

Na constante `FONT_STYLE` (no topo do arquivo, logo após as imports), adicionar ao final da string (antes do backtick de fechamento):

```css
.react-flow__edge:hover .edge-delete-btn { opacity: 1 !important; }
.react-flow__edge .edge-delete-btn { opacity: 0; transition: opacity .15s; }
```

A string FONT_STYLE deve ficar assim no final:
```
...
.react-flow__controls-button:hover { background: #f5f2ed; }
.react-flow__edge:hover .edge-delete-btn { opacity: 1 !important; }
.react-flow__edge .edge-delete-btn { opacity: 0; transition: opacity .15s; }
\`;
```

- [ ] **Step 3: Criar componente DeletableEdge**

Logo ANTES da linha `// ─── QuickAddButton`, adicionar o componente e a constante de edge types:

```typescript
// ─── DeletableEdge — custom edge com botão de delete no hover ────────────────
let _deleteEdge: ((edgeId: string) => void) | null = null;

function DeletableEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition,
  style, markerEnd, label, labelStyle,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
  });

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />
      <EdgeLabelRenderer>
        {label && (
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "none",
              fontSize: 9, fontWeight: 700,
              ...(labelStyle as React.CSSProperties ?? {}),
            }}
            className="nodrag nopan"
          >
            {label as string}
          </div>
        )}
        <div
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY + (label ? 14 : 0)}px)`,
            pointerEvents: "all",
          }}
          className="nodrag nopan edge-delete-btn"
        >
          <button
            onClick={(e) => { e.stopPropagation(); _deleteEdge?.(id); }}
            title="Deletar conexão"
            style={{
              width: 22, height: 22, borderRadius: "50%",
              background: "#fff",
              border: "1.5px solid #fca5a5",
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", fontSize: 11, color: "#ef4444",
              boxShadow: "0 1px 4px rgba(0,0,0,.15)",
              padding: 0, lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

const EDGE_TYPES = { deletable: DeletableEdge };
```

- [ ] **Step 4: Trocar type "smoothstep" → "deletable" em toRFEdges**

Na função `toRFEdges` (em torno da linha 128), substituir todas as ocorrências de `type: "smoothstep"` por `type: "deletable"`:

```typescript
// Em cada edges.push({ ... }), trocar:
type: "smoothstep",
// por:
type: "deletable",
```

São 3 ocorrências (next_node_id, yes_node_id, no_node_id).

- [ ] **Step 5: Trocar type "smoothstep" → "deletable" em onConnect e addNodeBelow**

Em `onConnect` (em torno da linha 710):
```typescript
// Trocar
type: "smoothstep",
// por
type: "deletable",
```

Em `addNodeBelow` (em torno da linha 660):
```typescript
// Trocar
type: "smoothstep",
// por
type: "deletable",
```

- [ ] **Step 6: Adicionar state e callbacks no FlowBuilderInner**

Em `FlowBuilderInner`, após a linha `const [saving, setSaving] = useState(false);` (em torno da linha 599), adicionar:

```typescript
const [edgeContextMenu, setEdgeContextMenu] = useState<{ x: number; y: number; edgeId: string } | null>(null);
```

Após o `useEffect` que sincroniza `_addNodeBelow` (em torno da linha 673-677), adicionar:

```typescript
// ── deleteEdge callback ───────────────────────────────────────────────────────
const deleteEdge = useCallback(async (edgeId: string) => {
  const edge = rfEdges.find(e => e.id === edgeId);
  if (!edge) return;
  const linkField = edge.sourceHandle === "yes" ? "yes_node_id"
    : edge.sourceHandle === "no" ? "no_node_id"
    : "next_node_id";
  await fetch(`/api/campaigns/${campaignId}/nodes/${edge.source}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [linkField]: null }),
  });
  setDbNodes(prev => prev.map(n => n.id === edge.source ? { ...n, [linkField]: null } : n));
  setRFEdges(prev => prev.filter(e => e.id !== edgeId));
  setEdgeContextMenu(null);
}, [campaignId, rfEdges, setRFEdges, setDbNodes]);

// Manter referência de módulo atualizada (para DeletableEdge acessar)
useEffect(() => {
  _deleteEdge = deleteEdge;
  return () => { _deleteEdge = null; };
}, [deleteEdge]);

// ── Edge right-click → context menu ──────────────────────────────────────────
const onEdgeContextMenu = useCallback((e: React.MouseEvent, edge: Edge) => {
  e.preventDefault();
  e.stopPropagation();
  setEdgeContextMenu({ x: e.clientX, y: e.clientY, edgeId: edge.id });
}, []);
```

- [ ] **Step 7: Registrar edgeTypes no ReactFlow e adicionar onEdgeContextMenu**

No JSX do `<ReactFlow>` (em torno da linha 892), adicionar as props:

```tsx
<ReactFlow
  ...props existentes...
  edgeTypes={EDGE_TYPES}
  onEdgeContextMenu={onEdgeContextMenu}
>
```

- [ ] **Step 8: Renderizar EdgeContextMenu no JSX**

Logo antes do fechamento do `</div>` que contém o `<ReactFlow>` (wrapper `ref={reactFlowWrapper}`), adicionar o EdgeContextMenu:

```tsx
{/* Edge context menu */}
{edgeContextMenu && (
  <div
    style={{
      position: "fixed",
      top: edgeContextMenu.y,
      left: edgeContextMenu.x,
      zIndex: 9999,
      background: "#fff",
      border: "1px solid #e8e4df",
      borderRadius: 8,
      boxShadow: "0 8px 24px rgba(0,0,0,.14), 0 2px 6px rgba(0,0,0,.08)",
      padding: "4px",
      minWidth: 160,
    }}
    onMouseLeave={() => setEdgeContextMenu(null)}
  >
    <button
      onClick={() => deleteEdge(edgeContextMenu.edgeId)}
      style={{
        display: "flex", alignItems: "center", gap: 8,
        width: "100%", padding: "8px 12px",
        border: "none", background: "transparent",
        cursor: "pointer", borderRadius: 6,
        fontFamily: "'Outfit', sans-serif",
        fontSize: 13, color: "#dc2626", textAlign: "left",
      }}
      onMouseEnter={e => { e.currentTarget.style.background = "#fff5f5"; }}
      onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
    >
      <span>✕</span>
      <span>Deletar conexão</span>
    </button>
  </div>
)}
```

- [ ] **Step 9: TypeScript check**

```
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\frontend"
npx tsc --noEmit 2>&1
```

Esperado: zero erros. Erros comuns:
- `EdgeProps` não encontrado — confirmar que está no import do @xyflow/react
- `getSmoothStepPath` retorna array de 3 — desestruturar como `[edgePath, labelX, labelY]`
- `label` no EdgeProps é `ReactNode` — fazer cast `label as string` onde necessário

- [ ] **Step 10: Commit**

```
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA"
git add frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "feat(flow-builder): DeletableEdge com hover trash e right-click context menu"
```

---

## Task 3: Bug 3 — Fix click no nó + prevenir context menu do browser

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx`

### Contexto

O `motion.div` do Framer Motion que envolve o card do nó interfere com o sistema de `onNodeClick` do React Flow. A solução usa o padrão de módulo já existente (`_dragPayload`, `_addNodeBelow`, `_deleteEdge`) para criar `_selectNode`, e adiciona `onClick` diretamente no `motion.div`.

Além disso, o wrapper do canvas recebe `onContextMenu` para bloquear o menu do browser.

A variável `_selectNode` deve ser declarada no bloco de variáveis de módulo (onde estão `_dragPayload` e `_addNodeBelow`).

---

- [ ] **Step 1: Declarar _selectNode no bloco de variáveis de módulo**

Encontrar o bloco (em torno da linha 373):
```typescript
let _dragPayload: PaletteItem | null = null;
let _addNodeBelow: ((sourceId: string, type: CampaignNodeType, subtype: string) => void) | null = null;
```

Adicionar após `_addNodeBelow`:
```typescript
let _selectNode: ((nodeId: string) => void) | null = null;
```

- [ ] **Step 2: Adicionar onClick no motion.div do CampaignFlowNode**

No `CampaignFlowNode`, o `<motion.div>` raiz tem `onMouseEnter` e `onMouseLeave`. Adicionar `onClick`:

```tsx
<motion.div
  initial={{ opacity: 0, scale: 0.86 }}
  animate={{ opacity: 1, scale: 1 }}
  transition={{ duration: 0.18, ease: "easeOut" }}
  onClick={(e) => { e.stopPropagation(); _selectNode?.(node.id); }}
  onMouseEnter={() => setShowAdd(true)}
  onMouseLeave={() => setShowAdd(false)}
  style={{
    width: NODE_W,
    background: "#ffffff",
    borderRadius: 10,
    boxShadow: "0 1px 3px rgba(0,0,0,.07), 0 4px 14px rgba(0,0,0,.08)",
    border: "1px solid rgba(0,0,0,.06)",
    fontFamily: "'Outfit', sans-serif",
    overflow: "visible",
    position: "relative",
  }}
>
```

- [ ] **Step 3: Adicionar useEffect para sincronizar _selectNode no FlowBuilderInner**

No `FlowBuilderInner`, após o `useEffect` que sincroniza `_deleteEdge` (adicionado na Task 2), adicionar:

```typescript
// Manter _selectNode atualizado para CampaignFlowNode acessar sem closure stale
useEffect(() => {
  _selectNode = (nodeId: string) => setSelectedNodeId(nodeId);
  return () => { _selectNode = null; };
}, []);
```

- [ ] **Step 4: Prevenir context menu do browser no wrapper do canvas**

O wrapper do canvas é o `<div ref={reactFlowWrapper} style={{ flex: 1, position: "relative" }} ...>`.

Adicionar `onContextMenu`:

```tsx
<div
  ref={reactFlowWrapper}
  style={{ flex: 1, position: "relative" }}
  onDrop={onDrop}
  onDragOver={onDragOver}
  onContextMenu={(e) => e.preventDefault()}
>
```

- [ ] **Step 5: Fechar EdgeContextMenu ao clicar no pane**

No `onPaneClick` existente (em torno da linha 684), adicionar fechamento do context menu:

```typescript
const onPaneClick = useCallback(() => {
  setSelectedNodeId(null);
  setEdgeContextMenu(null);
}, []);
```

- [ ] **Step 6: TypeScript check**

```
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\frontend"
npx tsc --noEmit 2>&1
```

Esperado: zero erros.

- [ ] **Step 7: Commit e push**

```
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA"
git add frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "fix(flow-builder): onclick no no via _selectNode + prevenir context menu browser"
git push origin fix/flow-builder-interactions-v2:master
```

---

## Self-Review

**Spec coverage:**
- ✅ Bug 1: QuickAddButton gap → `top: 100%` + `paddingTop: 8` (Task 1)
- ✅ Bug 2: hover trash icon → `DeletableEdge` + `_deleteEdge` (Task 2)
- ✅ Bug 2: right-click context menu na aresta → `onEdgeContextMenu` + `EdgeContextMenu` (Task 2)
- ✅ Bug 2: `deleteEdge` callback com PATCH backend (Task 2)
- ✅ Bug 3: prevenir menu do browser → `onContextMenu` no wrapper (Task 3)
- ✅ Bug 3: inspector abre via `_selectNode` + `onClick` no `motion.div` (Task 3)
- ✅ Bug 3: fechar `EdgeContextMenu` no `onPaneClick` (Task 3)

**Sem placeholders:** todas as steps têm código completo.

**Consistência de tipos:** `_deleteEdge` declarado com mesmo padrão de `_dragPayload`/`_addNodeBelow`. `EDGE_TYPES` usa `DeletableEdge`. `edgeContextMenu` state é `{ x, y, edgeId } | null`.

# Flow Builder UX — Fluidez n8n/Zapier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **FRONTEND AGENTS MUST USE:** `superpowers:frontend-design` skill before any implementation.

**Goal:** Adicionar fluidez n8n/Zapier ao flow builder: trackpad pan correto, zoom por teclado, botão `+` no hover dos nós para criar nó conectado abaixo, e animações Framer Motion na entrada dos nós e no picker.

**Architecture:** Um único arquivo é modificado — `cadence-flow-builder.tsx` (~770 linhas). O módulo-level `_addNodeBelow` (padrão igual ao `_dragPayload`) mantém a referência estável do callback para que `QuickAddButton` (definido fora do render) possa chamar a função de `FlowBuilderInner`. Framer Motion anima `motion.div` dentro de `CampaignFlowNode` e `AnimatePresence` no picker.

**Tech Stack:** Next.js 14 App Router, `@xyflow/react` v12.10.2, `framer-motion` (a instalar), TypeScript, Tailwind (não usado aqui — inline styles).

**Branch:** `feat/flow-builder-ux`  
**Push destino:** `git push origin feat/flow-builder-ux:master`

---

## Arquivo modificado

```
frontend/src/components/campaigns/cadence-flow-builder.tsx   ← único arquivo
frontend/package.json                                         ← framer-motion
frontend/package-lock.json                                    ← framer-motion
```

---

## Task 1: Instalar framer-motion e corrigir navegação do canvas

**Files:**
- Modify: `frontend/package.json` (via npm install)
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx` — imports + ReactFlow props + keyboard handler + MiniMap

### Contexto para o agente

O arquivo atual tem estes imports de `@xyflow/react` (linha 5-26):
```typescript
import {
  ReactFlow, Background, Controls,
  useNodesState, useEdgesState, addEdge,
  Connection, Edge, Node, Handle, Position,
  BackgroundVariant, NodeProps, useReactFlow,
  ReactFlowProvider, OnConnect, Panel, MarkerType,
  NodeMouseHandler, OnNodeDrag,
} from "@xyflow/react";
```

O `<ReactFlow>` nas linhas ~658-696 tem: `minZoom={0.3}`, `maxZoom={2}`, sem `panOnScroll`, sem `snapToGrid`.

`useReactFlow()` na linha 468 extrai apenas `screenToFlowPosition`. Precisa extrair também `zoomIn`, `zoomOut`, `fitView`.

O `<Controls position="bottom-right" />` na linha ~684.

---

- [ ] **Step 1: Instalar framer-motion**

```bash
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\frontend"
npm install framer-motion
```

Esperado: `added N packages` sem erros.

- [ ] **Step 2: Atualizar imports do @xyflow/react**

Localizar o bloco de imports de `@xyflow/react` e substituir por:

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
} from "@xyflow/react";
```

- [ ] **Step 3: Adicionar import de framer-motion**

Logo após `import "@xyflow/react/dist/style.css";`, adicionar:

```typescript
import { motion, AnimatePresence } from "framer-motion";
```

- [ ] **Step 4: Expandir useReactFlow() em FlowBuilderInner**

Localizar linha:
```typescript
const { screenToFlowPosition } = useReactFlow();
```

Substituir por:
```typescript
const { screenToFlowPosition, zoomIn, zoomOut, fitView } = useReactFlow();
```

- [ ] **Step 5: Adicionar keyboard zoom handler**

Logo após o `useEffect` de load da campanha (após linha `}, [campaignId, setRFNodes, setRFEdges]);`), adicionar:

```typescript
// ── Keyboard zoom: =|+ zoom in, - zoom out, 0 fit view ──────────────────────
useEffect(() => {
  const onKey = (e: KeyboardEvent) => {
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (e.key === "=" || e.key === "+") { e.preventDefault(); zoomIn({ duration: 200 }); }
    else if (e.key === "-")             { e.preventDefault(); zoomOut({ duration: 200 }); }
    else if (e.key === "0")             { e.preventDefault(); fitView({ padding: 0.3, duration: 400 }); }
  };
  window.addEventListener("keydown", onKey);
  return () => window.removeEventListener("keydown", onKey);
}, [zoomIn, zoomOut, fitView]);
```

- [ ] **Step 6: Atualizar props do ReactFlow**

Localizar o bloco `<ReactFlow` e substituir/adicionar as seguintes props. O bloco completo deve ficar:

```tsx
<ReactFlow
  nodes={rfNodes}
  edges={rfEdges}
  onNodesChange={onNodesChange}
  onEdgesChange={onEdgesChange}
  onConnect={onConnect}
  onNodeClick={onNodeClick}
  onPaneClick={onPaneClick}
  onNodeDragStop={onNodeDragStop}
  nodeTypes={NODE_TYPES}
  fitView={rfNodes.length > 0}
  fitViewOptions={{ padding: 0.3 }}
  deleteKeyCode={null}
  minZoom={0.2}
  maxZoom={2.5}
  panOnScroll={true}
  panOnScrollMode={PanOnScrollMode.Free}
  zoomOnScroll={true}
  snapToGrid={true}
  snapGrid={[20, 20]}
  nodeDragThreshold={8}
  connectionLineStyle={{ stroke: "#E85D26", strokeWidth: 1.5, strokeDasharray: "5,4" }}
  connectionLineType={ConnectionLineType.SmoothStep}
  style={{ background: "#f5f2ed" }}
  proOptions={{ hideAttribution: true }}
>
```

- [ ] **Step 7: Adicionar MiniMap e reposicionar Controls**

Dentro do `<ReactFlow>`, substituir `<Controls position="bottom-right" />` por:

```tsx
<MiniMap
  position="bottom-right"
  style={{
    bottom: 90,
    border: "1px solid #e8e4df",
    borderRadius: 8,
    overflow: "hidden",
    background: "#f5f2ed",
  }}
  nodeColor={(n) => {
    const t = ((n.data as Record<string,unknown>).type as CampaignNodeType);
    return NODE_META[t]?.color ?? "#888";
  }}
  maskColor="rgba(245,242,237,0.75)"
/>
<Controls position="bottom-right" showInteractive={false} />
```

- [ ] **Step 8: TypeScript check**

```bash
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\frontend"
npx tsc --noEmit 2>&1
```

Esperado: sem erros. Se houver `PanOnScrollMode` ou `ConnectionLineType` not found, verificar se foi adicionado aos imports do @xyflow/react no Step 2.

- [ ] **Step 9: Commit**

```bash
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA"
git add frontend/package.json frontend/package-lock.json frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "feat(flow-builder): trackpad pan, keyboard zoom, MiniMap, snapToGrid"
```

---

## Task 2: QuickAddButton — botão + no hover dos nós

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx`

### Contexto para o agente

Adicionar:
1. Variável de módulo `_addNodeBelow` (padrão igual a `_dragPayload` já existente)
2. Componente `QuickAddButton` (module-level, antes de `CampaignFlowNode`)
3. Callback `addNodeBelow` em `FlowBuilderInner` com `useEffect` para atualizar a variável de módulo
4. Hover state (`showAdd`) dentro de `CampaignFlowNode`
5. Renderização de `<QuickAddButton nodeId={node.id} />` no `CampaignFlowNode`

A variável de módulo `_dragPayload: PaletteItem | null = null` já existe e serve de referência para o padrão.

`CampaignFlowNode` atualmente começa na linha ~166 com `const CampaignFlowNode = memo(function CampaignFlowNode...`.

O bloco de output handles no `CampaignFlowNode` (perto da linha ~230):
```tsx
{!isEnd && (
  isCondition ? (
    <>
      <Handle type="source" position={Position.Bottom} id="yes" ... />
      ...
      <Handle type="source" position={Position.Bottom} id="no" ... />
      ...
    </>
  ) : (
    <Handle type="source" position={Position.Bottom} id="out" ... />
  )
)}
```

---

- [ ] **Step 1: Adicionar variável de módulo _addNodeBelow**

Logo após `let _dragPayload: PaletteItem | null = null;` (que está logo antes de `PALETTE_TRIGGERS`), adicionar:

```typescript
let _addNodeBelow: ((sourceId: string, type: CampaignNodeType, subtype: string) => void) | null = null;
```

- [ ] **Step 2: Criar lista de tipos disponíveis no quick-add**

Logo após a declaração de `_addNodeBelow`, adicionar:

```typescript
const QUICK_ADD_ITEMS: { type: CampaignNodeType; subtype: string; icon: string; label: string }[] = [
  { type: "send",      subtype: "",                 icon: "📨", label: "Enviar template" },
  { type: "wait",      subtype: "",                 icon: "⏱",  label: "Aguardar" },
  { type: "condition", subtype: "replied_recently", icon: "🔀", label: "Condição" },
  { type: "action",    subtype: "move_stage",       icon: "📋", label: "Ação CRM" },
  { type: "end",       subtype: "",                 icon: "🏁", label: "Encerrar" },
];
```

- [ ] **Step 3: Criar componente QuickAddButton**

Logo antes da definição de `const CampaignFlowNode = memo(...)`, adicionar o componente completo:

```typescript
function QuickAddButton({ nodeId }: { nodeId: string }) {
  const [open, setOpen] = useState(false);

  const handleAdd = (e: React.MouseEvent, type: CampaignNodeType, subtype: string) => {
    e.stopPropagation();
    _addNodeBelow?.(nodeId, type, subtype);
    setOpen(false);
  };

  return (
    <div
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
      onMouseLeave={() => setOpen(false)}
    >
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
        style={{
          width: 26, height: 26, borderRadius: "50%",
          background: "#fff",
          border: "1.5px solid #c8c2bb",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer", fontSize: 16, color: "#888",
          boxShadow: "0 1px 4px rgba(0,0,0,.12)",
          lineHeight: 1, padding: 0,
          transition: "border-color .12s, color .12s, box-shadow .12s",
        }}
        onMouseEnter={e => {
          e.currentTarget.style.borderColor = "#E85D26";
          e.currentTarget.style.color = "#E85D26";
          e.currentTarget.style.boxShadow = "0 2px 8px rgba(232,93,38,.25)";
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = "#c8c2bb";
          e.currentTarget.style.color = "#888";
          e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,.12)";
        }}
      >
        +
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: 32,
            left: "50%",
            transform: "translateX(-50%)",
            background: "#fff",
            border: "1px solid #e8e4df",
            borderRadius: 10,
            boxShadow: "0 8px 24px rgba(0,0,0,.12), 0 2px 6px rgba(0,0,0,.06)",
            padding: "5px 4px",
            minWidth: 152,
            zIndex: 30,
          }}
          onClick={e => e.stopPropagation()}
        >
          {QUICK_ADD_ITEMS.map(item => (
            <button
              key={`${item.type}-${item.subtype}`}
              onClick={e => handleAdd(e, item.type, item.subtype)}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                width: "100%", padding: "7px 10px",
                border: "none", background: "transparent",
                cursor: "pointer", borderRadius: 7,
                fontFamily: "'Outfit', sans-serif",
                fontSize: 12, color: "#222", textAlign: "left",
                transition: "background .1s",
              }}
              onMouseEnter={e => { e.currentTarget.style.background = "#f5f2ed"; }}
              onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
            >
              <span style={{ fontSize: 14 }}>{item.icon}</span>
              <span style={{ fontWeight: 500 }}>{item.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Adicionar hover state em CampaignFlowNode**

No início de `CampaignFlowNode`, logo após `const isTrigger = node.type === "trigger";`, adicionar:

```typescript
const [showAdd, setShowAdd] = useState(false);
```

- [ ] **Step 5: Adicionar onMouseEnter/Leave e QuickAddButton no node card**

No `CampaignFlowNode`, o `<div>` raiz da card (que tem `width: NODE_W, background: "#ffffff", ...`) deve receber:

```tsx
onMouseEnter={() => setShowAdd(true)}
onMouseLeave={() => setShowAdd(false)}
```

E logo antes do `</div>` de fechamento do card (após o bloco de output handles), adicionar:

```tsx
{/* Quick-add button — aparece no hover, não em nós end */}
{!isEnd && showAdd && (
  <QuickAddButton nodeId={node.id} />
)}
```

O card completo fica assim (estrutura):
```tsx
<div
  style={{ width: NODE_W, background: "#ffffff", borderRadius: 10, ... }}
  onMouseEnter={() => setShowAdd(true)}
  onMouseLeave={() => setShowAdd(false)}
>
  {/* Top stripe */}
  <div ... />

  {/* Input handle */}
  {!isTrigger && <Handle ... />}

  {/* Body */}
  <div style={{ padding: "12px 14px 16px", ... }}>...</div>

  {/* Output handles */}
  {!isEnd && (
    isCondition ? (
      <> <Handle id="yes" ... /> ... <Handle id="no" ... /> ... </>
    ) : (
      <Handle id="out" ... />
    )
  )}

  {/* Quick-add button */}
  {!isEnd && showAdd && <QuickAddButton nodeId={node.id} />}
</div>
```

- [ ] **Step 6: Adicionar addNodeBelow em FlowBuilderInner**

Logo após o `useEffect` do keyboard zoom (adicionado na Task 1), adicionar:

```typescript
// ── Add node below + connect (Quick-Add button) ───────────────────────────
const addNodeBelow = useCallback(async (sourceId: string, type: CampaignNodeType, subtype: string) => {
  const sourceRF = rfNodes.find(n => n.id === sourceId);
  if (!sourceRF) return;

  const res = await fetch(`/api/campaigns/${campaignId}/nodes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      type,
      config: getDefaultConfig(type, subtype),
      position_x: Math.round(sourceRF.position.x),
      position_y: Math.round(sourceRF.position.y + 200),
    }),
  });
  if (!res.ok) return;
  const newNode: CampaignNode = await res.json();

  // Persist edge: PATCH source node next_node_id
  await fetch(`/api/campaigns/${campaignId}/nodes/${sourceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ next_node_id: newNode.id }),
  });

  // Update local state
  setDbNodes(prev => [
    ...prev.map(n => n.id === sourceId ? { ...n, next_node_id: newNode.id } : n),
    newNode,
  ]);
  setRFNodes(prev => [...prev, toRFNode(newNode)]);
  setRFEdges(prev => [...prev, {
    id: `${sourceId}→${newNode.id}`,
    source: sourceId,
    sourceHandle: "out",
    target: newNode.id,
    targetHandle: "in",
    style: { stroke: "#c8c2bb", strokeWidth: 1.5 },
    markerEnd: { type: MarkerType.ArrowClosed, color: "#c8c2bb", width: 14, height: 14 },
    type: "smoothstep",
  }]);
}, [campaignId, rfNodes, setRFNodes, setRFEdges]);

// Manter referência de módulo atualizada (para QuickAddButton acessar)
useEffect(() => {
  _addNodeBelow = addNodeBelow;
  return () => { _addNodeBelow = null; };
}, [addNodeBelow]);
```

- [ ] **Step 7: TypeScript check**

```bash
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\frontend"
npx tsc --noEmit 2>&1
```

Esperado: zero erros. Erros comuns a corrigir:
- `useState` não importado em `QuickAddButton` → já importado no topo do arquivo
- `React.MouseEvent` → pode ser `MouseEvent` se React não estiver em scope; usar `import type React from 'react'` ou trocar por `(e: React.MouseEvent<HTMLButtonElement>)`

- [ ] **Step 8: Commit**

```bash
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA"
git add frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "feat(flow-builder): QuickAddButton no hover - criar no conectado abaixo"
```

---

## Task 3: Framer Motion — animações de entrada e picker

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx`

### Contexto para o agente

`framer-motion` já foi instalado na Task 1 e importado como `import { motion, AnimatePresence } from "framer-motion";`.

A Task 2 adicionou `QuickAddButton` com o picker como `{open && <div>...</div>}`.

`CampaignFlowNode` usa `memo`. O `<div>` raiz da card (com `width: NODE_W`) será substituído por `<motion.div>`.

**IMPORTANTE:** `motion.div` aceita todos os props de `div` + `initial`, `animate`, `exit`, `transition`. Não há conflito com `style`, `onMouseEnter`, etc.

---

- [ ] **Step 1: Animar entrada do node card com motion.div**

No `CampaignFlowNode`, substituir o `<div>` raiz do card (o que tem `width: NODE_W, background: "#ffffff"`) por `<motion.div>` com as mesmas props + animação:

```tsx
<motion.div
  initial={{ opacity: 0, scale: 0.86 }}
  animate={{ opacity: 1, scale: 1 }}
  transition={{ duration: 0.18, ease: "easeOut" }}
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
  onMouseEnter={() => setShowAdd(true)}
  onMouseLeave={() => setShowAdd(false)}
>
  {/* ... conteúdo interno igual ... */}
  {!isEnd && showAdd && <QuickAddButton nodeId={node.id} />}
</motion.div>
```

O `</div>` de fechamento correspondente deve ser trocado por `</motion.div>`.

- [ ] **Step 2: Animar picker do QuickAddButton com AnimatePresence**

No `QuickAddButton`, substituir o bloco `{open && <div ...>...</div>}` (o picker) por versão com `AnimatePresence` + `motion.div`:

```tsx
<AnimatePresence>
  {open && (
    <motion.div
      key="quick-add-picker"
      initial={{ opacity: 0, y: -8, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -6, scale: 0.95 }}
      transition={{ duration: 0.13, ease: "easeOut" }}
      style={{
        position: "absolute",
        top: 32,
        left: "50%",
        transform: "translateX(-50%)",
        background: "#fff",
        border: "1px solid #e8e4df",
        borderRadius: 10,
        boxShadow: "0 8px 24px rgba(0,0,0,.12), 0 2px 6px rgba(0,0,0,.06)",
        padding: "5px 4px",
        minWidth: 152,
        zIndex: 30,
      }}
      onClick={e => e.stopPropagation()}
    >
      {QUICK_ADD_ITEMS.map(item => (
        <button
          key={`${item.type}-${item.subtype}`}
          onClick={e => handleAdd(e, item.type, item.subtype)}
          style={{
            display: "flex", alignItems: "center", gap: 8,
            width: "100%", padding: "7px 10px",
            border: "none", background: "transparent",
            cursor: "pointer", borderRadius: 7,
            fontFamily: "'Outfit', sans-serif",
            fontSize: 12, color: "#222", textAlign: "left",
            transition: "background .1s",
          }}
          onMouseEnter={e => { e.currentTarget.style.background = "#f5f2ed"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
        >
          <span style={{ fontSize: 14 }}>{item.icon}</span>
          <span style={{ fontWeight: 500 }}>{item.label}</span>
        </button>
      ))}
    </motion.div>
  )}
</AnimatePresence>
```

- [ ] **Step 3: Adicionar CSS suave ao FONT_STYLE para o botão +**

No `FONT_STYLE` (string no topo do arquivo), adicionar ao final da string (antes do backtick de fechamento):

```css
.rfb-minimap { position: absolute !important; bottom: 90px !important; right: 16px !important; }
.react-flow__minimap { border-radius: 8px !important; overflow: hidden !important; }
```

- [ ] **Step 4: TypeScript check final**

```bash
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\frontend"
npx tsc --noEmit 2>&1
```

Esperado: zero erros.

Erros comuns:
- `motion.div` com prop `style` e `onMouseEnter` — esses props são aceitos por `motion.div`, sem problema
- `AnimatePresence` não reconhecido — confirmar que `import { motion, AnimatePresence } from "framer-motion"` está no topo

- [ ] **Step 5: Commit e push**

```bash
cd "C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA"
git add frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "feat(flow-builder): animacoes framer-motion na entrada dos nos e picker"
git push origin feat/flow-builder-ux:master
```

---

## Self-Review

**Spec coverage:**
- ✅ Trackpad pan → `panOnScroll: true` + `panOnScrollMode: Free` (Task 1)
- ✅ Keyboard `=`/`+`/`-`/`0` → keyboard handler (Task 1)
- ✅ `MiniMap` → adicionado (Task 1)
- ✅ `snapToGrid` + `snapGrid: [20,20]` → adicionado (Task 1)
- ✅ `nodeDragThreshold: 8` → adicionado (Task 1)
- ✅ `connectionLineStyle` animada → adicionado (Task 1)
- ✅ `QuickAddButton` hover + picker → Task 2
- ✅ `addNodeBelow` + edge automática → Task 2
- ✅ `motion.div` na entrada do nó → Task 3
- ✅ `AnimatePresence` no picker → Task 3

**Sem placeholders:** todas as tasks têm código completo.

**Consistência de tipos:** `CampaignNodeType`, `CampaignNode`, `PaletteItem` usados consistentemente. `_addNodeBelow` tipado com os mesmos parâmetros que `addNodeBelow`.

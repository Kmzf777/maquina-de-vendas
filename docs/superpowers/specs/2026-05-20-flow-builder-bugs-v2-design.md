# Spec: Flow Builder — Correção de Bugs de Interação (v2)

**Data:** 2026-05-20  
**Status:** Aprovado  
**Branch:** `fix/flow-builder-interactions-v2`

---

## Contexto

Três bugs de interação encontrados em produção no flow builder de cadências (`cadence-flow-builder.tsx`):

1. **QuickAddButton some** — O botão `+` aparece no hover do nó, mas some ao tentar mover o mouse até ele.
2. **Conexões não deletáveis** — Não existe forma de deletar uma aresta (conexão) criada no canvas.
3. **Clique esquerdo abre menu do browser / inspector não abre** — Clicar em nós ou no canvas não abre o inspector; em vez disso o menu de contexto do browser aparece.

---

## Bug 1 — QuickAddButton: gap invisível de 12px

### Causa raiz

O wrapper do `QuickAddButton` usa `position: absolute; bottom: -38`. Com o botão tendo 26px de altura:

- Borda inferior do wrapper = `card.bottom + 38`
- Borda superior do wrapper = `card.bottom + 38 - 26` = `card.bottom + 12`

Há um gap de **12px** entre a borda inferior do `motion.div` do card e a borda superior do wrapper. Ao mover o mouse do interior do card para o botão `+`, o cursor cruza essa zona, disparando `onMouseLeave → setShowAdd(false)` e desmontando o botão antes de ser alcançado.

### Solução

Trocar `bottom: -38` por `top: "100%"` (wrapper começa exatamente na borda inferior do card, gap zero) e usar `paddingTop: 8` para o espaço visual entre card e botão.

```tsx
// Antes
style={{ position: "absolute", bottom: -38, left: "50%", transform: "translateX(-50%)", ... }}

// Depois
style={{ position: "absolute", top: "100%", left: "50%", transform: "translateX(-50%)", paddingTop: 8, ... }}
```

---

## Bug 2 — Conexões não deletáveis

### Causa raiz

`deleteKeyCode={null}` no `<ReactFlow>` desabilita toda deleção via teclado. Não há UI affordance (ícone, menu) para deletar arestas. A função `deleteNode` existe para nós, mas não há `deleteEdge`.

### Solução

**Dupla:**

#### A) Custom edge com ícone de lixo no hover

Criar componente `DeletableEdge` registrado como tipo `"deletable"` em todas as arestas:

- Renderiza o path da aresta normalmente (`<BaseEdge>`)
- No ponto médio (`EdgeLabelRenderer` + `getBezierPath`/`getSmoothStepPath`), renderiza um botão `🗑` que fica visível ao hover da aresta (`opacity: 0 → 1` via CSS no `.react-flow__edge:hover`)
- Clicar no botão chama `deleteEdge(id)`

#### B) Right-click context menu na aresta

Handler `onEdgeContextMenu` no `<ReactFlow>`:

- Previne o menu nativo do browser (`e.preventDefault()`)
- Salva `{ x, y, edgeId }` no state
- Renderiza `<EdgeContextMenu>` — div absolutamente posicionado com a opção "Deletar conexão"
- Fecha ao clicar fora (listener no document) ou após ação

#### C) `deleteEdge` callback

```typescript
const deleteEdge = useCallback(async (edgeId: string) => {
  // Encontrar source/target na aresta
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
}, [campaignId, rfEdges, setRFEdges, setDbNodes]);
```

---

## Bug 3 — Clique esquerdo abre menu do browser / inspector não abre

### Causa raiz

O `motion.div` do Framer Motion captura eventos de pointer para detecção de gestos internos, interferindo com o sistema de `onNodeClick` do React Flow. Com isso, cliques nos nós não chegam ao handler do React Flow, o inspector não abre, e o OS/browser interpreta o evento residual como contextmenu.

### Solução

1. **Prevenir menu do browser no canvas:**
   ```tsx
   // No <div ref={reactFlowWrapper}>
   onContextMenu={(e) => e.preventDefault()}
   ```

2. **Bypass do click no nó — usar `onClick` no próprio `motion.div`:**
   O `motion.div` do card recebe `onClick` que chama diretamente `_selectNode(node.id)`, uma variável de módulo atualizada via `useEffect` (mesmo padrão de `_dragPayload` e `_addNodeBelow`).

   ```typescript
   // Módulo
   let _selectNode: ((id: string) => void) | null = null;

   // No motion.div do card:
   onClick={(e) => { e.stopPropagation(); _selectNode?.(node.id); }}

   // Em FlowBuilderInner:
   useEffect(() => {
     _selectNode = (id) => setSelectedNodeId(id);
     return () => { _selectNode = null; };
   }, []);
   ```

3. **Fechar inspector ao clicar no pane — manter `onPaneClick`** (já funciona, não toca).

---

## Arquitetura

### Único arquivo modificado

`frontend/src/components/campaigns/cadence-flow-builder.tsx`

### Mudanças por seção

```
cadence-flow-builder.tsx
├── FONT_STYLE: adicionar CSS .react-flow__edge:hover .edge-delete-btn { opacity: 1 }
├── Módulo: + _selectNode variable
├── DeletableEdge component (novo, antes de CampaignFlowNode)
├── EDGE_TYPES constant (novo, módulo-level)
├── CampaignFlowNode: fix bottom→top no QuickAddButton wrapper + onClick no motion.div
├── FlowBuilderInner:
│   ├── state: edgeContextMenu { x, y, edgeId } | null
│   ├── deleteEdge callback (novo)
│   ├── useEffect _selectNode sync (novo)
│   ├── onEdgeContextMenu handler (novo)
│   └── ReactFlow: + edgeTypes={EDGE_TYPES}, onEdgeContextMenu, wrapper onContextMenu
└── EdgeContextMenu component inline no JSX do FlowBuilderInner
```

---

## O que NÃO é escopo

- Undo/Redo
- Deletar nós via teclado (continua desabilitado — `deleteKeyCode={null}`)
- Animação de remoção de aresta
- Context menu no nó (só na aresta)

---

## Critérios de Sucesso

1. Passar o mouse sobre um nó → `+` aparece → mover mouse para o `+` → botão **não some**
2. Hover numa aresta → ícone 🗑 aparece → clicar → aresta deletada + PATCH backend
3. Botão direito numa aresta → mini-menu "Deletar conexão" → clicar → aresta deletada
4. Clicar com botão esquerdo num nó → inspector abre no painel direito
5. Botão direito no canvas (fora de aresta) → **sem** menu do browser

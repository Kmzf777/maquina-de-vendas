# Plano: Bulk Move Deals — Kanban /vendas

**Spec:** `docs/superpowers/specs/2026-05-07-bulk-move-deals-design.md`  
**Branch:** `feat/bulk-move-deals`  
**Status:** Aprovado

---

## Passo 1 — Criar o componente `BulkMoveDealsModal`

**Arquivo:** `frontend/src/components/deals/bulk-move-deals-modal.tsx`

Criar componente novo com as seguintes props:

```ts
interface BulkMoveDealsModalProps {
  deals: Deal[];           // deals da coluna de origem
  stages: PipelineStage[]; // todos os stages do pipeline ativo
  sourceStageId: string;   // stage atual (excluído do destino)
  sourceStageName: string; // nome para o título do modal
  onClose: () => void;
  onMove: (dealIds: string[], targetStageId: string) => Promise<void>;
}
```

**Estrutura interna:**

- `selected: Set<string>` — IDs dos deals marcados
- `targetStageId: string | null` — stage destino selecionado
- `loading: boolean` — durante o `Promise.all`

**Lógica:**

- `selectAll`: se `selected.size === deals.length` → desmarcar todos; senão → marcar todos
- Checkbox "todos" com `indeterminate` quando `selected.size > 0 && selected.size < deals.length`
- Stages disponíveis = `stages.filter(s => s.id !== sourceStageId && !s.is_protected)`
- Botão "Mover deals" disabled quando `selected.size === 0 || !targetStageId || loading`
- Ao confirmar: `await onMove([...selected], targetStageId)` → `onClose()`

**UI do item da lista:**
```
[ ] Deal Title      Nome do Lead    R$ 1.500
```

---

## Passo 2 — Adicionar kebab menu em `DroppableColumn`

**Arquivo:** `frontend/src/app/(authenticated)/vendas/page.tsx` (função `DroppableColumn`)

Adicionar props:

```ts
onBulkMove?: () => void; // abre o modal
```

**No header da coluna**, após o valor e antes da contagem:

- Adicionar `group` className no wrapper do header
- Ícone ⋯ (SVG ou texto `···`):
  - `opacity-0 group-hover:opacity-100 transition-opacity`
  - Só renderiza se `deals.length > 0`
  - `onClick`: abre dropdown local (estado `showMenu: boolean`)
- Dropdown absolutamente posicionado:
  - Item: "Mover deals..." → chama `onBulkMove`
  - Fecha ao clicar fora (useEffect com `mousedown` listener)

---

## Passo 3 — Integrar na `VendasPage`

**Arquivo:** `frontend/src/app/(authenticated)/vendas/page.tsx`

1. Adicionar estado:
```ts
const [bulkMoveStage, setBulkMoveStage] = useState<PipelineStage | null>(null);
```

2. Criar handler `handleBulkMove`:
```ts
async function handleBulkMove(dealIds: string[], targetStageId: string) {
  await Promise.all(
    dealIds.map((id) =>
      fetch(`/api/deals/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage_id: targetStageId }),
      })
    )
  );
}
```
Se qualquer PATCH falhar: `alert("Erro ao mover alguns deals. Tente novamente.")`

3. Passar `onBulkMove` para `DroppableColumn`:
```tsx
<DroppableColumn
  ...
  onBulkMove={() => setBulkMoveStage(stage)}
/>
```

4. Renderizar modal:
```tsx
{bulkMoveStage && (
  <BulkMoveDealsModal
    deals={filteredDeals.filter((d) => d.stage_id === bulkMoveStage.id)}
    stages={stages}
    sourceStageId={bulkMoveStage.id}
    sourceStageName={bulkMoveStage.label}
    onClose={() => setBulkMoveStage(null)}
    onMove={handleBulkMove}
  />
)}
```

---

## Passo 4 — Commit e verificação

1. Verificar TypeScript sem erros: `cd frontend && npx tsc --noEmit`
2. Verificar que drag-and-drop ainda funciona (nenhuma mudança na lógica de DnD)
3. Commit: `feat(vendas): bulk move deals entre colunas do kanban`

---

## Checklist de QA (para o usuário testar)

- [ ] Ícone ⋯ aparece ao hover da coluna (apenas se tiver deals)
- [ ] Dropdown "Mover deals..." abre e fecha ao clicar fora
- [ ] Modal abre com título correto "Mover deals de [stage]"
- [ ] "Selecionar todos" marca/desmarca todos
- [ ] Estado indeterminate funciona
- [ ] Stages protegidos e stage atual não aparecem no dropdown de destino
- [ ] Botão "Mover deals" fica disabled sem seleção ou sem destino
- [ ] Deals aparecem na nova coluna após confirmar
- [ ] Drag-and-drop individual continua funcionando normalmente

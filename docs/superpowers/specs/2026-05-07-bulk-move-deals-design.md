# Spec: Bulk Move Deals — Kanban /vendas

**Data:** 2026-05-07  
**Status:** Aprovado  

---

## Contexto

No kanban de `/vendas`, mover deals entre colunas é feito individualmente via drag-and-drop. Falta uma forma de mover vários deals de uma coluna para outra em uma única ação — útil para limpar colunas, reorganizar pipeline, ou fazer triagem em lote.

---

## Feature

Adicionar um menu de **3 pontinhos (⋯)** no header de cada coluna do kanban. Ao clicar, aparece um dropdown com a opção **"Mover deals..."** que abre um modal de seleção e movimentação em bulk.

---

## Fluxo

```
Header da coluna → clica ⋯ → dropdown "Mover deals..." → modal abre →
seleciona deals (todos ou alguns) → escolhe stage destino → confirma → modal fecha → deals movidos
```

---

## UI — Kebab no Header da Coluna

- Ícone ⋯ (três pontos horizontais) posicionado no header, entre o valor total e a contagem de deals
- Visível apenas quando a coluna tem ≥ 1 deal
- Hover: `opacity-100`; idle: `opacity-0 group-hover:opacity-100` (aparece ao hover da coluna)
- Ao clicar: abre um pequeno dropdown posicionado abaixo do ícone
- Dropdown contém: **"Mover deals..."** (único item por ora)
- Fechar dropdown ao clicar fora (listener `mousedown` no document)

---

## UI — Modal `BulkMoveDealsModal`

### Header
- Título: `Mover deals de "[stage name]"`
- Botão × para fechar

### Body (scrollável)
- Checkbox "Selecionar todos" no topo com contagem: `(X de Y)`
- Lista de deals da coluna, cada item:
  - `[ ] Deal title — Nome do Lead — R$ valor`
  - Checkbox individual por deal
- Estado vazio impossível (modal só abre quando coluna tem deals)

### Footer (fixo)
- Label: `X deals selecionados`
- Dropdown de stage destino:
  - Lista todos os stages do pipeline ativo
  - **Exclui:** o stage atual e stages com `is_protected: true`
- Botão **"Mover deals"**:
  - Disabled se: 0 deals selecionados OU nenhum stage destino selecionado
  - Loading state durante as requisições
- Botão cancelar

---

## Comportamento

- **Selecionar todos:** marca todos os checkboxes; desmarcar "todos" desmarca tudo
- **Indeterminate state:** se alguns (mas não todos) estão selecionados, o "selecionar todos" fica em estado indeterminado
- **Stage "Fechado/Perdido"** (e quaisquer stages `is_protected: true`): excluídos do dropdown de destino — nunca aparecem como opção
- **Depois de confirmar:** modal fecha, deals já aparecem na nova coluna via Realtime (hook `useRealtimeDeals` já está ativo)
- **Erro:** se algum PATCH falhar, exibir `alert("Erro ao mover alguns deals. Tente novamente.")` e manter modal fechado

---

## API

Nenhum endpoint novo. Para cada deal selecionado:

```
PATCH /api/deals/:id
{ "stage_id": "<destino>" }
```

Disparado em paralelo via `Promise.all`. O hook `useRealtimeDeals` cuida da atualização da UI.

---

## Componentes Afetados

| Arquivo | Mudança |
|---|---|
| `frontend/src/app/(authenticated)/vendas/page.tsx` | Passa `stages` e `onBulkMove` para `DroppableColumn`; renderiza `BulkMoveDealsModal` |
| `frontend/src/app/(authenticated)/vendas/page.tsx` → `DroppableColumn` | Adiciona kebab button e dropdown no header |
| `frontend/src/components/deals/bulk-move-deals-modal.tsx` | **Novo componente** — modal de seleção + destino |

---

## Fora do Escopo

- Nenhum novo endpoint de backend
- Não há movimentação para stages protegidos
- Não há undo/desfazer
- Não há animações de transição dos cards entre colunas

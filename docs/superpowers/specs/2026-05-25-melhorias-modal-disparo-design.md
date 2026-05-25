# Spec: Melhorias de UX no Modal de Novo Disparo

**Data:** 2026-05-25  
**Branch:** `fix/melhorias-modal-disparo`  
**Status:** Aprovado

---

## Contexto

O modal de "Novo Disparo" (`CreateBroadcastModal`) é um wizard de 6 etapas. A UX atual apresenta gargalos: seleção de leads um a um, filtros que exigem clique em "Aplicar", navegação manual pós-criação para iniciar o disparo, e campos legados (intervalo de envio) que não fazem mais sentido com a Meta Cloud API.

---

## Escopo

4 arquivos alterados, nenhuma mudança de banco de dados ou API de backend.

| Arquivo | Natureza |
|---|---|
| `frontend/src/lib/types.ts` | Adicionar campo `mode` ao tipo `Channel` |
| `frontend/src/components/ui/alert-dialog.tsx` | Novo componente shadcn/ui (Radix primitivo) |
| `frontend/src/components/campaigns/lead-filter-panel.tsx` | Filtro em tempo real + remoção do botão "Aplicar" |
| `frontend/src/components/campaigns/create-broadcast-modal.tsx` | 5 melhorias (detalhadas abaixo) |

---

## Mudanças detalhadas

### 1. `types.ts` — Campo `mode` no `Channel`

Adicionar `mode?: "ai" | "human"` ao `Channel` interface (linha 226). O campo já existe na tabela e é retornado pela API via `select("*")`, mas estava ausente no tipo TypeScript.

### 2. `alert-dialog.tsx` — Novo componente UI

Criar usando `radix-ui` (já instalado como `radix-ui ^1.4.3`). Exportar os mesmos sub-componentes da API shadcn/ui padrão:
- `AlertDialog`, `AlertDialogPortal`, `AlertDialogOverlay`, `AlertDialogTrigger`
- `AlertDialogContent`, `AlertDialogHeader`, `AlertDialogFooter`
- `AlertDialogTitle`, `AlertDialogDescription`
- `AlertDialogAction`, `AlertDialogCancel`

Estilo: consistente com o padrão visual do projeto (bordas `#dedbd6`, texto `#111111`, botão primário `bg-[#111111] text-white`).

### 3. `lead-filter-panel.tsx` — Filtro em tempo real

**Remover:** botão "Aplicar filtros" (o botão "Limpar" permanece como reset de estado).

**Adicionar:** dois `useEffect` para disparar `onApply` automaticamente:
- **Selects e checkbox** (`pipelineId`, `stageId`, `dealCategory`, `noDeal`, `tagIds`): reage imediatamente via `useEffect([campo_específico])`.
- **Campos de texto/data** (`search`, `createdAfter`, `createdBefore`): debounce de 400ms via `useRef<ReturnType<typeof setTimeout>>`. Cleanup limpa o timeout em cada re-render.

O `AbortController` existente no `handleApplyLeadFilters` do modal pai cancela automaticamente requests obsoletas.

### 4. `create-broadcast-modal.tsx` — 5 melhorias

#### 4.1 ESC para fechar
`useEffect` ativo quando `open === true`:
```ts
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === "Escape") { onClose(); resetForm(); }
};
window.addEventListener("keydown", handleKeyDown);
return () => window.removeEventListener("keydown", handleKeyDown);
```

#### 4.2 Ocultar campo Agente quando canal é `mode=human`
- Tipo `Channel` atualizado com `mode` (ver item 1).
- `selectedChannel` derivado de `channels.find(c => c.id === channelId)`.
- Seção "Agente" envolta em `{selectedChannel?.mode !== "human" && (...)}`.
- `useEffect([channelId])` reseta `agentMode` para `"none"` quando canal muda para `human`.

#### 4.3 Remover campos de Intervalo
Remover de todos os pontos:
- Estados `intervalMin` / `intervalMax` e seus setters
- Bloco `grid grid-cols-2` no step 1 (linhas 631-656)
- Linha "Intervalo" na revisão (step 6, linhas 1144-1148)
- Campos `send_interval_min` / `send_interval_max` no body do `handleCreate`
- Linhas `setIntervalMin(3)` / `setIntervalMax(8)` no `resetForm`

#### 4.4 Shift+Click na tabela de leads (Step 3)
Novo estado: `lastCheckedIndex: number | null` (inicializado como `null`).

Função `toggleLead` atualizada para receber `(id: string, idx: number, shiftKey: boolean)`:
```ts
const toggleLead = (id: string, idx: number, shiftKey: boolean) => {
  if (shiftKey && lastCheckedIndex !== null) {
    const [from, to] = [Math.min(lastCheckedIndex, idx), Math.max(lastCheckedIndex, idx)];
    const rangeIds = leads.slice(from, to + 1).map(l => l.id);
    const selecting = !selectedLeadIds.has(id);
    setSelectedLeadIds(prev => {
      const next = new Set(prev);
      rangeIds.forEach(rid => selecting ? next.add(rid) : next.delete(rid));
      return next;
    });
  } else {
    setSelectedLeadIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }
  setLastCheckedIndex(idx);
};
```

Cada `<tr>` e `<input checkbox>` passam `shiftKey` do evento de click:
- `<tr onClick={(e) => toggleLead(lead.id, idx, e.shiftKey)}>`
- `<input onClick={(e) => { e.stopPropagation(); toggleLead(lead.id, idx, e.shiftKey); }}>`

`lastCheckedIndex` é resetado para `null` em `deselectAllLeads` e `selectAllLeads`.

#### 4.5 AlertDialog pós-criação

**Novos estados:**
```ts
const [createdBroadcastId, setCreatedBroadcastId] = useState<string | null>(null);
const [showStartDialog, setShowStartDialog] = useState(false);
const [starting, setStarting] = useState(false);
```

**`handleCreate` atualizado (ao sucesso):**
```ts
// Em vez de: onCreated(); onClose(); resetForm();
if (scheduleMode === "immediate") {
  setCreatedBroadcastId(broadcast.id);
  setShowStartDialog(true);
} else {
  // Agendado: fecha normalmente
  onCreated();
  onClose();
  resetForm();
}
```

**`handleStartNow`:**
```ts
const handleStartNow = async () => {
  if (!createdBroadcastId) return;
  setStarting(true);
  try {
    await fetch(`/api/broadcasts/${createdBroadcastId}/start`, { method: "POST" });
  } finally {
    setStarting(false);
    setShowStartDialog(false);
    onCreated();
    onClose();
    resetForm();
    router.push(`/campanhas/disparos/${createdBroadcastId}`);
  }
};
```

**`handleCancelStart` (só fecha):**
```ts
const handleCancelStart = () => {
  setShowStartDialog(false);
  onCreated();
  onClose();
  resetForm();
};
```

O `AlertDialog` é renderizado fora do `div` do wizard (após o bloco principal), controlado por `showStartDialog`. Requer `useRouter` do `next/navigation`.

---

## Fluxos de decisão

```
Criar Disparo (clique)
  └─► API POST /api/broadcasts → sucesso
        ├─► scheduleMode === "immediate"
        │     └─► showStartDialog = true
        │           ├─► "Iniciar agora" → POST /api/broadcasts/[id]/start
        │           │     └─► onCreated() + onClose() + router.push(/campanhas/disparos/[id])
        │           └─► "Cancelar" → onCreated() + onClose() (sem start)
        └─► scheduleMode === "scheduled"
              └─► onCreated() + onClose() (fecha normalmente)
```

---

## Não está no escopo

- Mudanças em qualquer arquivo da pasta `/api/evolution/`
- Alterações de schema de banco de dados
- Mudanças nos outros steps do wizard (2, 4, 5)
- Testes automatizados

---

## Critérios de aceitação

1. ESC fecha o modal em qualquer step
2. Canal com `mode=human` → seção Agente invisível
3. Campos "Intervalo mín./máx." removidos de toda a UI e do payload da API
4. Filtros de leads reagem sem clicar em botão; texto debounced 400ms
5. Shift+Click seleciona/desseleciona range de leads
6. Após criar disparo imediato → AlertDialog pergunta "Iniciar agora?"
7. Confirmar start → navega para `/campanhas/disparos/[id]`
8. Cancelar start → fecha normalmente, sem iniciar
9. Disparo agendado → fecha sem mostrar dialog

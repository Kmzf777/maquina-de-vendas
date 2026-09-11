# Mover deal de funil e etapa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir trocar o funil e a etapa de um deal pelo modal de detalhes, e mover vários deals de uma vez pelo board via um modo de seleção com checkbox.

**Architecture:** Frontend puro. A rota `PATCH /api/deals/[id]` já aceita `pipeline_id` + `stage_id` e já valida permissão nos dois funis — nada de backend ou migration. A lógica testável (montar payload, lotear requisições, resumir falhas, filtrar etapas) sai para `src/lib/bulk-move-deals.ts` com testes vitest; a UI consome essas funções puras.

**Tech Stack:** Next.js 16 (App Router, client components), React 19, TypeScript, Tailwind v4, `@dnd-kit/core`, vitest.

**Spec:** `docs/superpowers/specs/2026-09-11-deal-move-funil-etapa-design.md`

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `frontend/src/lib/bulk-move-deals.ts` **(criar)** | Lógica pura: payload do PATCH, lotes, resumo de falhas, filtro de etapas |
| `frontend/src/lib/bulk-move-deals.test.ts` **(criar)** | Testes vitest da lógica pura |
| `frontend/src/components/deals/stage-target-picker.tsx` **(criar)** | Par de selects Funil + Etapa com carregamento de etapas de outro funil. Usado pela Parte A e pela Parte B |
| `frontend/src/components/deals/bulk-move-modal.tsx` **(criar)** | Diálogo de movimentação em massa (destino + confirmação irreversível) |
| `frontend/src/components/deals/bulk-move-deals-modal.tsx` **(remover)** | Substituído pelo novo fluxo |
| `frontend/src/components/deals/deal-detail-sidebar.tsx` **(modificar)** | Usa o `StageTargetPicker` dentro do form de edição |
| `frontend/src/components/deals/deal-card.tsx` **(modificar)** | Indicador de seleção quando `selectable` |
| `frontend/src/app/(authenticated)/vendas/page.tsx` **(modificar)** | Botão "Editar Deals", modo seleção, execução do bulk |

**Ordem:** Task 1 (lógica pura) → Task 2 (picker compartilhado) → Task 3 (Parte A) → Tasks 4-7 (Parte B).

**Comandos base** (sempre a partir de `frontend/`):
- testes: `npm test`
- um arquivo: `npx vitest run src/lib/bulk-move-deals.test.ts`
- tipos: `npm run type-check`
- lint: `npm run lint`

---

## Task 1: Lógica pura de movimentação

**Files:**
- Create: `frontend/src/lib/bulk-move-deals.ts`
- Test: `frontend/src/lib/bulk-move-deals.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

Criar `frontend/src/lib/bulk-move-deals.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  buildMovePayload,
  chunk,
  summarizeMoveResults,
  selectableStages,
} from "./bulk-move-deals";
import type { PipelineStage } from "./types";

function stage(over: Partial<PipelineStage> & { id: string }): PipelineStage {
  return {
    pipeline_id: "p1",
    label: over.id,
    key: null,
    dot_color: "#5b8aad",
    order_index: 0,
    is_protected: false,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("buildMovePayload", () => {
  it("omite pipeline_id quando o funil nao muda", () => {
    const payload = buildMovePayload({ pipeline_id: "p1" }, "p1", "s9");
    expect(payload).toEqual({ stage_id: "s9" });
  });

  it("inclui pipeline_id quando o funil muda", () => {
    const payload = buildMovePayload({ pipeline_id: "p1" }, "p2", "s9");
    expect(payload).toEqual({ stage_id: "s9", pipeline_id: "p2" });
  });

  it("inclui pipeline_id quando o deal nao tem funil", () => {
    const payload = buildMovePayload({ pipeline_id: null }, "p2", "s9");
    expect(payload).toEqual({ stage_id: "s9", pipeline_id: "p2" });
  });
});

describe("chunk", () => {
  it("quebra 12 itens em lotes de 5", () => {
    const items = Array.from({ length: 12 }, (_, i) => i);
    expect(chunk(items, 5)).toEqual([
      [0, 1, 2, 3, 4],
      [5, 6, 7, 8, 9],
      [10, 11],
    ]);
  });

  it("devolve lista vazia para entrada vazia", () => {
    expect(chunk([], 5)).toEqual([]);
  });

  it("devolve um unico lote quando cabe tudo", () => {
    expect(chunk([1, 2], 5)).toEqual([[1, 2]]);
  });
});

describe("summarizeMoveResults", () => {
  it("conta tudo como movido quando nao ha falha", () => {
    const summary = summarizeMoveResults([
      { id: "d1", ok: true },
      { id: "d2", ok: true },
    ]);
    expect(summary).toEqual({ moved: 2, failed: 0, failedIds: [], message: "" });
  });

  it("reporta parciais com a mensagem da API", () => {
    const summary = summarizeMoveResults([
      { id: "d1", ok: true },
      { id: "d2", ok: false, error: "Permissão insuficiente para este funil." },
      { id: "d3", ok: false, error: "Permissão insuficiente para este funil." },
    ]);
    expect(summary.moved).toBe(1);
    expect(summary.failed).toBe(2);
    expect(summary.failedIds).toEqual(["d2", "d3"]);
    expect(summary.message).toBe(
      "1 de 3 deals movidos. 2 falharam: Permissão insuficiente para este funil."
    );
  });

  it("junta mensagens de erro diferentes sem repetir", () => {
    const summary = summarizeMoveResults([
      { id: "d1", ok: false, error: "Erro A" },
      { id: "d2", ok: false, error: "Erro B" },
      { id: "d3", ok: false, error: "Erro A" },
    ]);
    expect(summary.message).toBe("0 de 3 deals movidos. 3 falharam: Erro A; Erro B");
  });

  it("usa mensagem generica quando a API nao devolve erro", () => {
    const summary = summarizeMoveResults([{ id: "d1", ok: false }]);
    expect(summary.message).toBe("0 de 1 deals movidos. 1 falharam: Erro desconhecido");
  });
});

describe("selectableStages", () => {
  it("esconde etapas protegidas", () => {
    const stages = [
      stage({ id: "s1" }),
      stage({ id: "s2" }),
      stage({ id: "won", is_protected: true }),
    ];
    expect(selectableStages(stages, "s1").map((s) => s.id)).toEqual(["s1", "s2"]);
  });

  it("mantem a etapa atual mesmo protegida, na posicao original", () => {
    const stages = [
      stage({ id: "s1", order_index: 0 }),
      stage({ id: "won", is_protected: true, order_index: 1 }),
      stage({ id: "lost", is_protected: true, order_index: 2 }),
    ];
    expect(selectableStages(stages, "won").map((s) => s.id)).toEqual(["s1", "won"]);
  });

  it("aceita etapa atual nula", () => {
    const stages = [stage({ id: "s1" }), stage({ id: "won", is_protected: true })];
    expect(selectableStages(stages, null).map((s) => s.id)).toEqual(["s1"]);
  });
});
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/bulk-move-deals.test.ts`
Expected: FAIL — `Failed to resolve import "./bulk-move-deals"`

- [ ] **Step 3: Implementar**

Criar `frontend/src/lib/bulk-move-deals.ts`:

```ts
import type { PipelineStage } from "./types";

/** Quantas PATCHes rodam em paralelo por lote. Cada PATCH faz 3 round-trips no
 *  Supabase e dispara um webhook de automação — mandar 50 de uma vez martela o
 *  backend sem necessidade. */
export const MOVE_BATCH_SIZE = 5;

export interface MoveResult {
  id: string;
  ok: boolean;
  error?: string;
}

export interface MoveSummary {
  moved: number;
  failed: number;
  failedIds: string[];
  message: string;
}

/**
 * Corpo do PATCH para mover um deal. `pipeline_id` só entra quando o funil muda:
 * mandar o mesmo valor de volta faria a rota rodar a guarda de destino à toa.
 */
export function buildMovePayload(
  deal: { pipeline_id: string | null },
  targetPipelineId: string,
  targetStageId: string
): Record<string, string> {
  const payload: Record<string, string> = { stage_id: targetStageId };
  if (deal.pipeline_id !== targetPipelineId) payload.pipeline_id = targetPipelineId;
  return payload;
}

export function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

export function summarizeMoveResults(results: MoveResult[]): MoveSummary {
  const failures = results.filter((r) => !r.ok);
  const moved = results.length - failures.length;
  if (failures.length === 0) {
    return { moved, failed: 0, failedIds: [], message: "" };
  }
  const reasons = [...new Set(failures.map((f) => f.error || "Erro desconhecido"))];
  return {
    moved,
    failed: failures.length,
    failedIds: failures.map((f) => f.id),
    message: `${moved} de ${results.length} deals movidos. ${failures.length} falharam: ${reasons.join("; ")}`,
  };
}

/**
 * Etapas oferecidas como destino: só as ativas. A etapa atual entra mesmo se for
 * protegida, senão o select mostraria outra etapa e mentiria sobre onde o deal está.
 */
export function selectableStages(
  stages: PipelineStage[],
  currentStageId: string | null
): PipelineStage[] {
  return stages.filter((s) => !s.is_protected || s.id === currentStageId);
}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/bulk-move-deals.test.ts`
Expected: PASS — 13 tests passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/bulk-move-deals.ts frontend/src/lib/bulk-move-deals.test.ts
git commit -m "feat(vendas): logica pura de movimentacao de deals entre funil e etapa"
```

---

## Task 2: Componente compartilhado de destino (funil + etapa)

Usado pelo modal de detalhes (Task 3) e pelo diálogo de massa (Task 5). Evita duplicar o carregamento de etapas de outro funil nos dois lugares.

**Files:**
- Create: `frontend/src/components/deals/stage-target-picker.tsx`

- [ ] **Step 1: Implementar o componente**

Criar `frontend/src/components/deals/stage-target-picker.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import type { Pipeline, PipelineStage } from "@/lib/types";
import { selectableStages } from "@/lib/bulk-move-deals";

interface StageTargetPickerProps {
  pipelines: Pipeline[];
  /** Funil escolhido no momento. */
  pipelineId: string;
  /** Etapa escolhida no momento. "" = nenhuma. */
  stageId: string;
  /** Etapas já carregadas do funil aberto no board — evita um fetch redundante. */
  localPipelineId: string | null;
  localStages: PipelineStage[];
  /** Etapa atual do deal; entra na lista mesmo se for protegida. null no modo massa. */
  currentStageId: string | null;
  /** Se true, seleciona a primeira etapa ao trocar de funil. Se false, zera a escolha. */
  autoSelectFirstStage: boolean;
  disabled?: boolean;
  onChange: (pipelineId: string, stageId: string) => void;
}

export function StageTargetPicker({
  pipelines,
  pipelineId,
  stageId,
  localPipelineId,
  localStages,
  currentStageId,
  autoSelectFirstStage,
  disabled = false,
  onChange,
}: StageTargetPickerProps) {
  const [remoteStages, setRemoteStages] = useState<PipelineStage[]>([]);
  const [loading, setLoading] = useState(false);

  const isLocal = pipelineId === localPipelineId;

  useEffect(() => {
    if (!pipelineId || isLocal) { setRemoteStages([]); return; }
    const controller = new AbortController();
    setLoading(true);
    fetch(`/api/pipelines/${pipelineId}/stages`, { signal: controller.signal })
      .then((r) => r.json())
      .then((data: PipelineStage[]) => {
        setRemoteStages(Array.isArray(data) ? data : []);
      })
      .catch((e) => { if (e?.name !== "AbortError") setRemoteStages([]); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [pipelineId, isLocal]);

  const stages = isLocal ? localStages : remoteStages;
  const options = selectableStages(stages, currentStageId);

  function handlePipelineChange(nextPipelineId: string) {
    if (nextPipelineId === localPipelineId) {
      const opts = selectableStages(localStages, currentStageId);
      onChange(nextPipelineId, autoSelectFirstStage ? opts[0]?.id ?? "" : "");
    } else {
      // As etapas do novo funil ainda não chegaram; zera e deixa o efeito abaixo
      // preencher quando o fetch resolver.
      onChange(nextPipelineId, "");
    }
  }

  // Depois que as etapas de um funil remoto chegam, preenche a escolha se pedido.
  useEffect(() => {
    if (!autoSelectFirstStage || isLocal || loading || stageId) return;
    const first = selectableStages(remoteStages, currentStageId)[0]?.id;
    if (first) onChange(pipelineId, first);
    // onChange vem do pai e pode mudar de identidade a cada render; depender dele
    // aqui causaria loop. As dependências abaixo bastam para o preenchimento único.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remoteStages, loading, isLocal, autoSelectFirstStage, stageId, pipelineId, currentStageId]);

  const selectClass =
    "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full disabled:opacity-50";

  return (
    <div className="space-y-3">
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Funil</label>
        <select
          value={pipelineId}
          disabled={disabled}
          onChange={(e) => handlePipelineChange(e.target.value)}
          className={selectClass}
        >
          {pipelines.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Etapa</label>
        <select
          value={stageId}
          disabled={disabled || loading}
          onChange={(e) => onChange(pipelineId, e.target.value)}
          className={selectClass}
        >
          {loading && <option value="">Carregando...</option>}
          {!loading && <option value="">Selecionar etapa...</option>}
          {!loading && options.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos e lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: ambos sem erro. (O componente ainda não é usado — é esperado que nada mude visualmente.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/deals/stage-target-picker.tsx
git commit -m "feat(vendas): componente compartilhado de destino funil+etapa"
```

---

## Task 3: Trocar funil e etapa no modal de detalhes (Parte A)

**Files:**
- Modify: `frontend/src/components/deals/deal-detail-sidebar.tsx`
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx` (passar `pipelines`, repassar erro da API)

- [ ] **Step 1: Adicionar a prop `pipelines` e o estado de destino no sidebar**

Em `deal-detail-sidebar.tsx`:

Trocar o import de tipos e adicionar o do picker:

```tsx
import type { Deal, Pipeline, PipelineStage } from "@/lib/types";
import { StageTargetPicker } from "@/components/deals/stage-target-picker";
```

Adicionar `pipelines` à interface de props:

```tsx
interface DealDetailSidebarProps {
  deal: Deal;
  stages: PipelineStage[];
  pipelines: Pipeline[];
  onClose: () => void;
  onUpdate: (dealId: string, data: Record<string, unknown>) => Promise<void>;
  onDelete: (dealId: string) => void;
}
```

E à assinatura:

```tsx
export function DealDetailSidebar({ deal, stages, pipelines, onClose, onUpdate, onDelete }: DealDetailSidebarProps) {
```

Adicionar os dois campos ao `form` (estado inicial):

```tsx
  const [form, setForm] = useState({
    title: deal.title,
    value: deal.value,
    category: deal.category || "",
    assigned_to: deal.assigned_to || "",
    expected_close_date: deal.expected_close_date || "",
    pipeline_id: deal.pipeline_id || "",
    stage_id: deal.stage_id || "",
  });
```

E ao efeito de ressincronização (que também cobre o "Cancelar", já que sair do modo edição
re-executa o efeito e restaura os valores do deal):

```tsx
  useEffect(() => {
    if (!editing) {
      setForm({
        title: deal.title,
        value: deal.value,
        category: deal.category || "",
        assigned_to: deal.assigned_to || "",
        expected_close_date: deal.expected_close_date || "",
        pipeline_id: deal.pipeline_id || "",
        stage_id: deal.stage_id || "",
      });
    }
  }, [deal, editing]);
```

- [ ] **Step 2: Incluir funil/etapa no payload do Salvar**

Substituir o array `savePromises` dentro de `handleSave` por:

```tsx
      const dealUpdates: Record<string, unknown> = {
        title: form.title,
        value: Number(form.value) || 0,
        category: form.category || null,
        assigned_to: form.assigned_to || null,
        expected_close_date: form.expected_close_date || null,
      };
      if (form.stage_id && form.stage_id !== deal.stage_id) {
        dealUpdates.stage_id = form.stage_id;
      }
      if (form.pipeline_id && form.pipeline_id !== deal.pipeline_id) {
        dealUpdates.pipeline_id = form.pipeline_id;
      }
      const savePromises: Promise<unknown>[] = [onUpdate(deal.id, dealUpdates)];
```

E trocar o `catch` para mostrar a mensagem real da API:

```tsx
    } catch (err) {
      setSaveError(err instanceof Error && err.message ? err.message : "Erro ao salvar. Tente novamente.");
    } finally {
```

- [ ] **Step 3: Renderizar o picker no topo do formulário**

Dentro do bloco `{editing ? (` → `<div className="space-y-3">`, **antes** do bloco de
"Observacoes do Lead", inserir:

```tsx
            <div>
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-2">Etapa do funil</span>
              <StageTargetPicker
                pipelines={pipelines}
                pipelineId={form.pipeline_id}
                stageId={form.stage_id}
                localPipelineId={deal.pipeline_id}
                localStages={stages}
                currentStageId={deal.stage_id}
                autoSelectFirstStage
                onChange={(pipeline_id, stage_id) => setForm((f) => ({ ...f, pipeline_id, stage_id }))}
              />
            </div>
```

- [ ] **Step 4: Passar `pipelines` e repassar o erro da API na página**

Em `frontend/src/app/(authenticated)/vendas/page.tsx`:

Trocar a renderização do sidebar (por volta da linha 384) para incluir `pipelines`:

```tsx
      {selectedDeal && (
        <DealDetailSidebar deal={selectedDeal} stages={stages} pipelines={pipelines} onClose={() => setSelectedDealId(null)} onUpdate={handleUpdateDeal} onDelete={handleDeleteDeal} />
      )}
```

Substituir `handleUpdateDeal` inteiro por:

```tsx
  async function handleUpdateDeal(dealId: string, data: Record<string, unknown>) {
    const res = await fetch(`/api/deals/${dealId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      // A rota devolve mensagens úteis (ex.: "Permissão insuficiente para este funil.")
      // ao mover para um funil de outro vendedor — jogar fora vira erro genérico na tela.
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || "Erro ao atualizar deal");
    }
    setSelectedDealId(null);
  }
```

- [ ] **Step 5: Verificar tipos, lint e testes**

Run: `cd frontend && npm run type-check && npm run lint && npm test`
Expected: type-check e lint sem erro; `npm test` com 805 testes passando (792 da baseline + 13 da Task 1).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/deals/deal-detail-sidebar.tsx "frontend/src/app/(authenticated)/vendas/page.tsx"
git commit -m "feat(vendas): trocar funil e etapa do deal pelo modal de detalhes"
```

---

## Task 4: Indicador de seleção no card

**Files:**
- Modify: `frontend/src/components/deals/deal-card.tsx`

- [ ] **Step 1: Adicionar as props e o indicador**

Substituir a interface e a abertura do componente em `deal-card.tsx`:

```tsx
interface DealCardProps {
  deal: Deal;
  onClick: (deal: Deal) => void;
  /** Modo seleção em massa: mostra o quadrado e troca o clique por "marcar". */
  selectable?: boolean;
  selected?: boolean;
}

export function DealCard({ deal, onClick, selectable = false, selected = false }: DealCardProps) {
```

Substituir o `<button>` de abertura por:

```tsx
    <button
      onClick={() => onClick(deal)}
      aria-pressed={selectable ? selected : undefined}
      className={`bg-white border rounded-[8px] p-3 mx-2 mb-2 cursor-pointer transition-colors w-[calc(100%-16px)] text-left ${
        selectable && selected ? "border-[#111111]" : "border-[#dedbd6] hover:border-[#111111]"
      }`}
    >
```

Substituir a primeira `<div>` interna (a do título/valor) por:

```tsx
      <div className="flex items-start justify-between mb-2">
        {selectable && (
          <span
            className={`w-4 h-4 rounded-[3px] border flex items-center justify-center flex-shrink-0 mr-2 mt-[1px] ${
              selected ? "bg-[#111111] border-[#111111]" : "bg-white border-[#dedbd6]"
            }`}
          >
            {selected && (
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 6L9 17l-5-5" />
              </svg>
            )}
          </span>
        )}
        <p className="text-[13px] font-normal text-[#111111] truncate flex-1">{deal.title}</p>
        {deal.value > 0 && (
          <span className="text-[12px] text-[#7b7b78] ml-2 flex-shrink-0">
            {formatCurrency(deal.value)}
          </span>
        )}
      </div>
```

Nota: um `<input type="checkbox">` real aqui seria HTML inválido (interativo dentro de `<button>`)
e o clique se perderia. O `<span>` + `aria-pressed` no botão resolve visual e semântica.

- [ ] **Step 2: Verificar tipos e lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: sem erro. As props novas são opcionais, então `vendas/page.tsx` e o `DragOverlay`
continuam compilando sem mudança.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/deals/deal-card.tsx
git commit -m "feat(vendas): indicador de selecao no card do kanban"
```

---

## Task 5: Diálogo de movimentação em massa

**Files:**
- Create: `frontend/src/components/deals/bulk-move-modal.tsx`

- [ ] **Step 1: Criar o diálogo**

Criar `frontend/src/components/deals/bulk-move-modal.tsx`:

```tsx
"use client";

import { useState } from "react";
import type { Pipeline, PipelineStage } from "@/lib/types";
import { StageTargetPicker } from "@/components/deals/stage-target-picker";

interface BulkMoveModalProps {
  count: number;
  pipelines: Pipeline[];
  currentPipelineId: string;
  currentStages: PipelineStage[];
  /** Progresso do lote em andamento; null quando parado. */
  progress: { done: number; total: number } | null;
  onClose: () => void;
  onMove: (pipelineId: string, stageId: string) => Promise<void>;
}

export function BulkMoveModal({
  count,
  pipelines,
  currentPipelineId,
  currentStages,
  progress,
  onClose,
  onMove,
}: BulkMoveModalProps) {
  const [targetPipelineId, setTargetPipelineId] = useState(currentPipelineId);
  const [targetStageId, setTargetStageId] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const moving = progress !== null;
  const canMove = Boolean(targetStageId) && confirmed && !moving;

  async function handleMove() {
    if (!canMove) return;
    await onMove(targetPipelineId, targetStageId);
  }

  return (
    <div
      className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
      onClick={() => { if (!moving) onClose(); }}
    >
      <div
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[460px] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-[#dedbd6] flex items-center justify-between">
          <div>
            <h3 className="text-[16px] font-normal text-[#111111]" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>
              Mover deals
            </h3>
            <p className="text-[12px] text-[#7b7b78] mt-0.5">
              {count} deal{count !== 1 ? "s" : ""} selecionado{count !== 1 ? "s" : ""}
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={moving}
            className="text-[#7b7b78] hover:text-[#111111] transition-colors disabled:opacity-40"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="3" x2="13" y2="13" />
              <line x1="13" y1="3" x2="3" y2="13" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          <StageTargetPicker
            pipelines={pipelines}
            pipelineId={targetPipelineId}
            stageId={targetStageId}
            localPipelineId={currentPipelineId}
            localStages={currentStages}
            currentStageId={null}
            autoSelectFirstStage={false}
            disabled={moving}
            onChange={(pipelineId, stageId) => {
              setTargetPipelineId(pipelineId);
              setTargetStageId(stageId);
            }}
          />

          {/* Trio de aviso já estabelecido no projeto (esteiras-tab, templates-tab). */}
          <div className="bg-[#fff8e0] border border-[#eadfb4] rounded-[6px] px-3 py-2.5">
            <p className="text-[12px] text-[#7a5a00] leading-[1.5]">
              Esta ação move {count} deal{count !== 1 ? "s" : ""} e não pode ser desfeita.
              As automações da etapa de destino serão disparadas para cada lead.
            </p>
          </div>

          <label className="flex items-center gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={moving}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="w-4 h-4 accent-[#111111] cursor-pointer"
            />
            <span className="text-[13px] text-[#111111]">Confirmo que quero mover estes deals</span>
          </label>
        </div>

        <div className="px-6 py-4 border-t border-[#dedbd6] bg-[#faf9f6] flex gap-2 justify-end rounded-b-[8px]">
          <button
            onClick={onClose}
            disabled={moving}
            className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors disabled:opacity-40"
          >
            Cancelar
          </button>
          <button
            onClick={handleMove}
            disabled={!canMove}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[13px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
          >
            {moving ? `Movendo ${progress.done}/${progress.total}...` : `Mover ${count} deal${count !== 1 ? "s" : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos e lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: sem erro.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/deals/bulk-move-modal.tsx
git commit -m "feat(vendas): dialogo de movimentacao em massa com confirmacao"
```

---

## Task 6: Modo "Editar Deals" no board

**Files:**
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx`

- [ ] **Step 1: Trocar o menu `···` da coluna pelo "selecionar todos"**

Em `vendas/page.tsx`, substituir a função `DroppableColumn` inteira (linhas 28-98) por:

```tsx
function DroppableColumn({
  id, title, dotColor, deals, onDealClick, selectionMode, selectedIds, onToggleAll,
}: {
  id: string; title: string; dotColor: string; deals: Deal[];
  onDealClick: (deal: Deal) => void;
  selectionMode: boolean;
  selectedIds: Set<string>;
  onToggleAll: (dealIds: string[], selectAll: boolean) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  const columnValue = deals.reduce((sum, d) => sum + (d.value || 0), 0);
  const fmt = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;

  const selectedHere = deals.filter((d) => selectedIds.has(d.id)).length;
  const allSelected = deals.length > 0 && selectedHere === deals.length;
  const someSelected = selectedHere > 0 && !allSelected;

  return (
    <div className="bg-[#f7f5f1] border border-[#dedbd6] rounded-[8px] flex flex-col min-h-[200px] w-72 flex-shrink-0">
      <div className="px-4 py-3 bg-[#f0ede8] border-b border-[#dedbd6] rounded-t-[8px] flex items-center justify-between">
        <div className="flex items-center gap-2">
          {selectionMode && deals.length > 0 && (
            <button
              onClick={() => onToggleAll(deals.map((d) => d.id), !allSelected)}
              title={allSelected ? "Desmarcar coluna" : "Selecionar coluna"}
              className={`w-4 h-4 rounded-[3px] border flex items-center justify-center flex-shrink-0 ${
                allSelected || someSelected ? "bg-[#111111] border-[#111111]" : "bg-white border-[#dedbd6]"
              }`}
            >
              {allSelected && (
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 6L9 17l-5-5" />
                </svg>
              )}
              {someSelected && <span className="w-2 h-[2px] bg-white rounded-full" />}
            </button>
          )}
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: dotColor }} />
          <h3 className="text-[13px] font-medium text-[#111111] uppercase tracking-[0.6px]">{title}</h3>
        </div>
        <div className="flex items-center gap-2">
          {columnValue > 0 && <span className="text-[11px] text-[#7b7b78]">{fmt(columnValue)}</span>}
          <span className="text-[12px] text-[#7b7b78] bg-white border border-[#dedbd6] rounded-full px-2 py-0.5">{deals.length}</span>
        </div>
      </div>
      <div
        ref={setNodeRef}
        className={`flex-1 py-2 overflow-y-auto transition-all duration-200 ${isOver ? "ring-2 ring-[#111111] ring-inset rounded-b-[8px]" : ""}`}
      >
        {deals.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16">
            <p className="text-[12px] text-[#7b7b78]">Nenhum deal</p>
          </div>
        )}
        {deals.map((deal) => (
          <DraggableDealCard
            key={deal.id}
            deal={deal}
            onClick={onDealClick}
            selectionMode={selectionMode}
            selected={selectedIds.has(deal.id)}
          />
        ))}
      </div>
    </div>
  );
}
```

Isso remove `showMenu`, `menuRef` e o efeito de clique-fora — junto com os imports que ficarem
órfãos. `useRef` continua usado pelo deep-link e `useEffect` pelos efeitos da página, então os dois
permanecem no import do topo.

- [ ] **Step 2: Desligar o drag em modo seleção**

Substituir `DraggableDealCard` (linhas 100-107 do arquivo original) por:

```tsx
function DraggableDealCard({
  deal, onClick, selectionMode, selected,
}: {
  deal: Deal; onClick: (deal: Deal) => void; selectionMode: boolean; selected: boolean;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: deal.id,
    data: deal,
    // Em modo seleção o PointerSensor competiria com o clique de marcar, e um
    // arrasto acidental moveria um card no meio da seleção.
    disabled: selectionMode,
  });
  return (
    <div
      ref={setNodeRef}
      {...(selectionMode ? {} : listeners)}
      {...attributes}
      className={isDragging ? "opacity-30" : ""}
    >
      <DealCard deal={deal} onClick={onClick} selectable={selectionMode} selected={selected} />
    </div>
  );
}
```

- [ ] **Step 3: Estado do modo seleção**

Em `VendasPageInner`, substituir a linha `const [bulkMoveStage, setBulkMoveStage] = useState<PipelineStage | null>(null);` por:

```tsx
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showBulkMove, setShowBulkMove] = useState(false);
  const [moveProgress, setMoveProgress] = useState<{ done: number; total: number } | null>(null);
```

Remover `PipelineStage` do import de tipos se ele ficar sem uso — verificar com `npm run lint`.

Adicionar, logo abaixo desse bloco de estado, os handlers de seleção:

```tsx
  function exitSelection() {
    setSelectionMode(false);
    setSelectedIds(new Set());
    setShowBulkMove(false);
  }

  function toggleDealSelection(dealId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(dealId)) next.delete(dealId);
      else next.add(dealId);
      return next;
    });
  }

  function toggleColumnSelection(dealIds: string[], selectAll: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const id of dealIds) {
        if (selectAll) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }
```

E um efeito que limpa a seleção ao trocar de funil — os ids selecionados são de outro board:

```tsx
  useEffect(() => {
    setSelectionMode(false);
    setSelectedIds(new Set());
    setShowBulkMove(false);
  }, [selectedPipelineId]);
```

- [ ] **Step 4: Botões no header**

Substituir o bloco `<div className="flex items-center gap-2">` do header (linhas 325-335 do
arquivo original, o que contém o botão "Novo Card") por:

```tsx
        <div className="flex items-center gap-2">
          {selectionMode ? (
            <>
              <button
                onClick={exitSelection}
                className="border border-[#dedbd6] text-[#313130] px-3 py-2 rounded-[4px] text-[14px] hover:border-[#111111] transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={() => setShowBulkMove(true)}
                disabled={selectedIds.size === 0}
                title={selectedIds.size === 0 ? "Selecione ao menos 1 deal" : undefined}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
              >
                Mover ({selectedIds.size})
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setSelectionMode(true)}
                className="border border-[#dedbd6] text-[#313130] px-3 py-2 rounded-[4px] text-[14px] hover:border-[#111111] transition-colors"
              >
                Editar Deals
              </button>
              <button
                onClick={() => setShowCreate(true)}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] flex items-center gap-2"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
                </svg>
                Novo Card
              </button>
            </>
          )}
        </div>
```

- [ ] **Step 5: Ligar as colunas ao modo seleção**

Substituir o `<DroppableColumn ... />` dentro do `stages.map` por:

```tsx
                <DroppableColumn
                  key={stage.id}
                  id={stage.id}
                  title={stage.label}
                  dotColor={stage.dot_color}
                  deals={stageDeals}
                  onDealClick={(deal) => {
                    if (selectionMode) toggleDealSelection(deal.id);
                    else setSelectedDealId(deal.id);
                  }}
                  selectionMode={selectionMode}
                  selectedIds={selectedIds}
                  onToggleAll={toggleColumnSelection}
                />
```

- [ ] **Step 6: Verificar tipos e lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: type-check sem erro. O lint deve apontar `BulkMoveDealsModal` e `bulkMoveStage` como não
usados — a limpeza acontece na Task 7. Se o lint falhar só por isso, seguir para a Task 7 e
verificar de novo lá.

- [ ] **Step 7: Commit**

```bash
git add "frontend/src/app/(authenticated)/vendas/page.tsx"
git commit -m "feat(vendas): modo de selecao em massa no kanban"
```

---

## Task 7: Executar a movimentação em massa e remover o modal antigo

**Files:**
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx`
- Delete: `frontend/src/components/deals/bulk-move-deals-modal.tsx`

- [ ] **Step 1: Trocar os imports**

Em `vendas/page.tsx`, substituir:

```tsx
import { BulkMoveDealsModal } from "@/components/deals/bulk-move-deals-modal";
```

por:

```tsx
import { BulkMoveModal } from "@/components/deals/bulk-move-modal";
import { buildMovePayload, chunk, summarizeMoveResults, MOVE_BATCH_SIZE, type MoveResult } from "@/lib/bulk-move-deals";
```

- [ ] **Step 2: Substituir `handleBulkMove`**

Trocar a função `handleBulkMove` inteira por:

```tsx
  async function handleBulkMove(targetPipelineId: string, targetStageId: string) {
    const ids = [...selectedIds];
    const byId = new Map(deals.map((d) => [d.id, d]));
    setMoveProgress({ done: 0, total: ids.length });

    const results: MoveResult[] = [];
    // Em lotes: cada PATCH faz 3 round-trips no Supabase e dispara um webhook de
    // automação. Mandar tudo de uma vez martela o backend sem ganho nenhum.
    for (const batch of chunk(ids, MOVE_BATCH_SIZE)) {
      const batchResults = await Promise.all(
        batch.map(async (id): Promise<MoveResult> => {
          const deal = byId.get(id);
          if (!deal) return { id, ok: false, error: "Deal não encontrado na tela" };
          try {
            const res = await fetch(`/api/deals/${id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(buildMovePayload(deal, targetPipelineId, targetStageId)),
            });
            if (res.ok) return { id, ok: true };
            const body = await res.json().catch(() => ({}));
            return { id, ok: false, error: body.error || `HTTP ${res.status}` };
          } catch {
            return { id, ok: false, error: "Falha de rede" };
          }
        })
      );
      results.push(...batchResults);
      setMoveProgress({ done: results.length, total: ids.length });
    }

    setMoveProgress(null);
    const summary = summarizeMoveResults(results);
    setShowBulkMove(false);

    if (summary.failed === 0) {
      exitSelection();
      return;
    }
    // Mantém os que falharam marcados: o usuário vê quais são e pode tentar de novo.
    setSelectedIds(new Set(summary.failedIds));
    alert(summary.message);
  }
```

- [ ] **Step 3: Trocar a renderização do modal**

Substituir o bloco `{bulkMoveStage && (<BulkMoveDealsModal ... />)}` por:

```tsx
      {showBulkMove && selectedPipelineId && (
        <BulkMoveModal
          count={selectedIds.size}
          pipelines={pipelines}
          currentPipelineId={selectedPipelineId}
          currentStages={stages}
          progress={moveProgress}
          onClose={() => setShowBulkMove(false)}
          onMove={handleBulkMove}
        />
      )}
```

- [ ] **Step 4: Apagar o modal antigo**

```bash
git rm frontend/src/components/deals/bulk-move-deals-modal.tsx
```

- [ ] **Step 5: Verificar tipos, lint e testes**

Run: `cd frontend && npm run type-check && npm run lint && npm test`
Expected: type-check e lint sem erro (nenhum símbolo órfão sobrando); `npm test` com 805 testes
passando.

- [ ] **Step 6: Confirmar que nada mais referencia o modal removido**

Run: `cd frontend && grep -rn "bulk-move-deals-modal\|BulkMoveDealsModal\|bulkMoveStage" src/`
Expected: sem resultado.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/
git commit -m "feat(vendas): mover deals selecionados para outro funil e etapa"
```

---

## Task 8: Verificação manual no navegador

Nada abaixo é coberto por unit test — precisa de olho humano ou navegador.

**Files:** nenhum

- [ ] **Step 1: Subir o dev server**

Run: `cd frontend && npm run dev`
Abrir `http://localhost:3000/vendas`.

- [ ] **Step 2: Conferir a Parte A**

- Clicar num card → modal abre → **Editar** → aparecem os selects **Funil** e **Etapa** no topo.
- Trocar o funil → o select de etapa mostra "Carregando..." e depois as etapas do funil novo.
- **Salvar** → o card some do board atual. Trocar para o outro funil no `PipelineSwitcher` → o card
  está lá, na etapa escolhida.
- Entrar em **Editar**, mexer nos selects e clicar em **Cancelar** → ao reabrir o Editar, os
  valores voltaram aos do deal.
- Etapas "Fechado Ganho"/"Fechado Perdido" **não** aparecem na lista (a menos que o deal já esteja
  numa delas).

- [ ] **Step 3: Conferir a Parte B**

- **Editar Deals** → todos os cards ganham quadrado; o header vira `Cancelar` + `Mover (0)`.
- `Mover (0)` está desabilitado.
- Marcar cards de **duas colunas diferentes** → contador sobe corretamente.
- Clicar no quadrado do cabeçalho de uma coluna → marca a coluna inteira; clicar de novo desmarca.
- Com alguns (não todos) marcados, o quadrado do cabeçalho mostra o traço de indeterminado.
- Tentar **arrastar** um card em modo seleção → nada se move.
- `Mover (N)` → diálogo abre com o funil atual pré-selecionado e etapa vazia.
- O botão de mover fica travado até escolher etapa **e** marcar o checkbox de confirmação.
- Confirmar → os cards selecionados somem do board juntos.
- **Cancelar** o modo → quadrados somem, clicar num card volta a abrir o modal de detalhes.

- [ ] **Step 4: Reportar**

Anotar qualquer divergência. Não commitar nada nesta task.

---

## Self-review (feito)

**Cobertura do spec:**

| Requisito do spec | Task |
|---|---|
| Parte A — selects Funil/Etapa no form de Editar | 3 |
| Parte A — carregar etapas de outro funil, auto-selecionar a primeira | 2, 3 |
| Parte A — só etapas ativas + a atual se protegida | 1 (`selectableStages`), 2 |
| Parte A — salvar só o que mudou | 3 |
| Parte A — repassar mensagem real da API | 3 |
| B1 — botão "Editar Deals", `Cancelar` + `Mover (N)`, disabled em N=0 | 6 |
| B1 — trocar de funil limpa a seleção | 6 |
| B2 — indicador no card, clique seleciona, drag desligado | 4, 6 |
| B3 — selecionar todos da coluna, estado indeterminado | 6 |
| B4 — diálogo com destino, aviso irreversível + automações, checkbox | 5 |
| B5 — lotes de 5, `pipeline_id` só se mudou, parciais mantêm seleção | 1, 7 |
| Remover menu `···` e `bulk-move-deals-modal.tsx` | 6, 7 |
| Testes de `bulk-move-deals.ts` | 1 |
| Verificação manual | 8 |

# Painel de múltiplas oportunidades em /conversas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o painel lateral do lead em `/conversas` listar e permitir editar o stage de **todas** as oportunidades do lead, numa seção única posicionada acima de Vendas.

**Architecture:** Lógica pura em `src/lib/deal-rows.ts` (com teste vitest), busca de stages de N funis num hook, apresentação de cada deal num componente de linha com estado de erro próprio, e a aba de perfil reduzida a montagem. Nenhuma mudança de backend, API ou banco.

**Tech Stack:** Next.js App Router (client components), TypeScript, vitest (`environment: "node"`, coleta só `src/**/*.test.ts` — **não há teste de componente React neste repo**).

**Spec:** `docs/superpowers/specs/2026-09-10-conversas-multi-deal-design.md`

**Working dir de todos os comandos:** `<worktree>/frontend`

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `src/lib/deal-rows.ts` *(criar)* | Puro: tipos, ordenação, classificação aberto/fechado, opções de stage por funil, stage de reabertura, patch de reabertura. | 1 |
| `src/lib/deal-rows.test.ts` *(criar)* | Cobre o acima. Teste-chave: dois deals abertos no mesmo funil. | 1 |
| `src/hooks/use-stages-by-pipeline.ts` *(criar)* | Busca stages de N funis em paralelo, cache por `pipeline_id`, abort no unmount. | 2 |
| `src/components/conversas/deal-stage-row.tsx` *(criar)* | Uma linha = um deal. Estado `pending`/`erro` local à linha. | 3 |
| `src/components/conversas/tabs/crm-perfil-tab.tsx` *(modificar)* | Funde Estágio + Oportunidades numa seção no topo; move "Atribuído a". | 4 |
| `src/components/conversas/contact-detail.tsx` *(modificar)* | `handleDealStageChange` → `handleDealUpdate`, que **lança** em falha. | 4 |

**Nota sobre TDD:** Task 1 é TDD de verdade (lógica pura, vitest). Tasks 2–4 mexem em React, para o qual **este repositório não tem infraestrutura de teste** (`vitest.config.ts` usa `environment: "node"` e `include: ["src/**/*.test.ts"]`). A verificação dessas tasks é `npm run type-check` + `npm run lint` + os critérios de aceite manuais da Task 5. Não invente setup de jsdom/testing-library — está fora do escopo e mudaria a config do projeto.

---

## Task 0: Pré-requisito

- [ ] **Step 1: Garantir dependências instaladas no worktree**

Worktrees git não copiam `node_modules`.

```bash
cd frontend && npm install --no-audit --no-fund
```

Expected: termina sem erro; `frontend/node_modules` passa a existir.

---

## Task 1: `deal-rows.ts` — a lógica pura

**Files:**
- Create: `frontend/src/lib/deal-rows.ts`
- Test: `frontend/src/lib/deal-rows.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

Criar `frontend/src/lib/deal-rows.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  buildDealRows,
  distinctPipelineIds,
  isDealClosed,
  reopenPatch,
  type LeadDeal,
  type StageOption,
} from "@/lib/deal-rows";

const ATACADO: StageOption[] = [
  { id: "a-entrada", label: "Entrada", dot_color: "#aaaaaa", order_index: 0, is_protected: false },
  { id: "a-qualif", label: "Qualificação", dot_color: "#bbbbbb", order_index: 1, is_protected: false },
  { id: "a-ganho", label: "Fechado/Ganho", dot_color: "#00aa00", order_index: 2, is_protected: true },
  { id: "a-perdido", label: "Fechado/Perdido", dot_color: "#aa0000", order_index: 3, is_protected: true },
];

const REPOSICAO: StageOption[] = [
  { id: "r-contato", label: "Contato", dot_color: "#cccccc", order_index: 0, is_protected: false },
  { id: "r-negoc", label: "Negociação", dot_color: "#dddddd", order_index: 1, is_protected: false },
  { id: "r-ganho", label: "Fechado/Ganho", dot_color: "#00aa00", order_index: 2, is_protected: true },
];

const STAGES = { "p-atacado": ATACADO, "p-reposicao": REPOSICAO };

function deal(over: Partial<LeadDeal> = {}): LeadDeal {
  return {
    id: "d1",
    title: "Atacado 60kg",
    value: 4200,
    category: null,
    stage_id: "a-qualif",
    pipeline_id: "p-atacado",
    updated_at: "2026-09-10T12:00:00Z",
    lost_reason: null,
    pipeline_stages: {
      id: "a-qualif",
      label: "Qualificação",
      dot_color: "#bbbbbb",
      key: null,
      is_protected: false,
    },
    pipelines: { id: "p-atacado", name: "Valeria - Atacado" },
    ...over,
  };
}

const CLOSED_STAGE = {
  id: "a-perdido",
  label: "Fechado/Perdido",
  dot_color: "#aa0000",
  key: "fechado_perdido",
  is_protected: true,
};

describe("isDealClosed", () => {
  it("é falso para deal em stage ativo", () => {
    expect(isDealClosed(deal())).toBe(false);
  });

  it("é verdadeiro pela key de fechamento", () => {
    expect(isDealClosed(deal({ pipeline_stages: { ...CLOSED_STAGE, is_protected: false } }))).toBe(true);
  });

  it("é verdadeiro por is_protected, mesmo sem key", () => {
    expect(isDealClosed(deal({ pipeline_stages: { ...CLOSED_STAGE, key: null } }))).toBe(true);
  });

  it("é falso quando o deal não tem stage carregado", () => {
    expect(isDealClosed(deal({ pipeline_stages: null }))).toBe(false);
  });
});

describe("distinctPipelineIds", () => {
  it("deduplica e descarta nulos", () => {
    const deals = [
      deal({ id: "d1", pipeline_id: "p-atacado" }),
      deal({ id: "d2", pipeline_id: "p-atacado" }),
      deal({ id: "d3", pipeline_id: "p-reposicao" }),
      deal({ id: "d4", pipeline_id: null }),
    ];
    expect(distinctPipelineIds(deals).sort()).toEqual(["p-atacado", "p-reposicao"]);
  });

  it("devolve lista vazia sem deals", () => {
    expect(distinctPipelineIds([])).toEqual([]);
  });
});

describe("buildDealRows", () => {
  it("gera uma linha editável por deal aberto no MESMO funil", () => {
    // Este é o bug original: dealForSelectedPipeline casava por pipeline_id,
    // então o segundo deal do mesmo funil era inalcançável.
    const deals = [
      deal({ id: "d1", title: "Atacado 60kg", stage_id: "a-qualif" }),
      deal({ id: "d2", title: "Atacado 20kg", stage_id: "a-entrada" }),
    ];
    const rows = buildDealRows(deals, STAGES);

    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.deal.id)).toEqual(["d1", "d2"]);
    expect(rows.every((r) => r.canEditStage)).toBe(true);
    expect(rows[0].deal.stage_id).toBe("a-qualif");
    expect(rows[1].deal.stage_id).toBe("a-entrada");
  });

  it("dá a cada linha os stages não-protegidos do SEU funil", () => {
    const deals = [
      deal({ id: "d1", pipeline_id: "p-atacado" }),
      deal({
        id: "d2",
        pipeline_id: "p-reposicao",
        stage_id: "r-negoc",
        pipelines: { id: "p-reposicao", name: "João - Reposição" },
        pipeline_stages: { id: "r-negoc", label: "Negociação", dot_color: "#dddddd", key: null, is_protected: false },
      }),
    ];
    const rows = buildDealRows(deals, STAGES);

    expect(rows[0].stageOptions.map((s) => s.id)).toEqual(["a-entrada", "a-qualif"]);
    expect(rows[1].stageOptions.map((s) => s.id)).toEqual(["r-contato", "r-negoc"]);
    expect(rows[1].pipelineName).toBe("João - Reposição");
  });

  it("põe abertos antes de fechados, cada grupo por updated_at desc", () => {
    const deals = [
      deal({ id: "fechado-novo", pipeline_stages: CLOSED_STAGE, updated_at: "2026-09-09T00:00:00Z" }),
      deal({ id: "aberto-velho", updated_at: "2026-01-01T00:00:00Z" }),
      deal({ id: "aberto-novo", updated_at: "2026-09-08T00:00:00Z" }),
      deal({ id: "fechado-velho", pipeline_stages: CLOSED_STAGE, updated_at: "2026-02-01T00:00:00Z" }),
    ];
    expect(buildDealRows(deals, STAGES).map((r) => r.deal.id)).toEqual([
      "aberto-novo",
      "aberto-velho",
      "fechado-novo",
      "fechado-velho",
    ]);
  });

  it("deal fechado não é editável e reabre no primeiro stage ativo", () => {
    const rows = buildDealRows([deal({ pipeline_stages: CLOSED_STAGE, lost_reason: "preço alto" })], STAGES);

    expect(rows[0].isClosed).toBe(true);
    expect(rows[0].canEditStage).toBe(false);
    expect(rows[0].reopenStageId).toBe("a-entrada");
    expect(rows[0].stageLabel).toBe("Fechado/Perdido");
    expect(rows[0].deal.lost_reason).toBe("preço alto");
  });

  it("escolhe o stage de reabertura por order_index, não pela ordem do array", () => {
    const embaralhado = {
      "p-atacado": [
        { id: "a-qualif", label: "Qualificação", dot_color: "#bbbbbb", order_index: 1, is_protected: false },
        { id: "a-perdido", label: "Fechado/Perdido", dot_color: "#aa0000", order_index: 3, is_protected: true },
        { id: "a-entrada", label: "Entrada", dot_color: "#aaaaaa", order_index: 0, is_protected: false },
      ],
    };
    const rows = buildDealRows([deal({ pipeline_stages: CLOSED_STAGE })], embaralhado);
    expect(rows[0].reopenStageId).toBe("a-entrada");
  });

  it("deal sem funil vira linha read-only", () => {
    const rows = buildDealRows(
      [deal({ pipeline_id: null, pipelines: null, pipeline_stages: null })],
      STAGES
    );
    expect(rows[0].pipelineName).toBe("Sem funil");
    expect(rows[0].canEditStage).toBe(false);
    expect(rows[0].reopenStageId).toBe(null);
    expect(rows[0].stageOptions).toEqual([]);
  });

  it("não deixa editar enquanto os stages do funil ainda não chegaram", () => {
    const rows = buildDealRows([deal()], {});
    expect(rows[0].canEditStage).toBe(false);
    expect(rows[0].stageOptions).toEqual([]);
  });
});

describe("reopenPatch", () => {
  it("limpa closed_at e lost_reason junto com o stage", () => {
    expect(reopenPatch("a-entrada")).toEqual({
      stage_id: "a-entrada",
      closed_at: null,
      lost_reason: null,
    });
  });
});
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

```bash
cd frontend && npx vitest run src/lib/deal-rows.test.ts
```

Expected: FAIL — `Failed to resolve import "@/lib/deal-rows"`.

- [ ] **Step 3: Implementar `deal-rows.ts`**

Criar `frontend/src/lib/deal-rows.ts`:

```ts
import type { Pipeline, PipelineStage } from "@/lib/types";

/** Keys das colunas terminais. Espelha o que o Kanban trata como fechamento. */
export const CLOSED_STAGE_KEYS = ["fechado_ganho", "fechado_perdido"];

/** Deal como vem de GET /api/leads/[id]/deals. */
export interface LeadDeal {
  id: string;
  title: string;
  value: number;
  category: string | null;
  stage_id: string | null;
  pipeline_id: string | null;
  updated_at: string;
  lost_reason: string | null;
  pipeline_stages: Pick<PipelineStage, "id" | "label" | "dot_color" | "key" | "is_protected"> | null;
  pipelines: Pick<Pipeline, "id" | "name"> | null;
}

/** Stage como vem de GET /api/pipelines/[id]/stages. */
export type StageOption = Pick<
  PipelineStage,
  "id" | "label" | "dot_color" | "order_index" | "is_protected"
>;

export type StagesByPipeline = Record<string, StageOption[]>;

export interface DealRow {
  deal: LeadDeal;
  isClosed: boolean;
  /** Só os stages não-protegidos do funil DESTE deal. Vazio => sem dropdown. */
  stageOptions: StageOption[];
  /** Rótulo do stage atual, exibido quando não há dropdown. */
  stageLabel: string;
  dotColor: string;
  pipelineName: string;
  /** Para onde "Reabrir" leva. null => não dá para reabrir. */
  reopenStageId: string | null;
  canEditStage: boolean;
}

/** Um deal está fechado se caiu numa coluna protegida — por key ou pela flag. */
export function isDealClosed(deal: LeadDeal): boolean {
  const stage = deal.pipeline_stages;
  if (!stage) return false;
  return stage.is_protected === true || CLOSED_STAGE_KEYS.includes(stage.key ?? "");
}

/** Funis distintos presentes nos deals — o que o painel precisa buscar. */
export function distinctPipelineIds(deals: LeadDeal[]): string[] {
  const ids = new Set<string>();
  for (const deal of deals) {
    if (deal.pipeline_id) ids.add(deal.pipeline_id);
  }
  return [...ids];
}

function firstOpenStageId(stages: StageOption[]): string | null {
  // order_index manda: a API já ordena, mas um cache remontado pode não estar
  // ordenado e reabrir no stage errado é um erro silencioso e caro.
  const open = stages.filter((s) => !s.is_protected);
  if (open.length === 0) return null;
  return open.reduce((a, b) => (a.order_index <= b.order_index ? a : b)).id;
}

/**
 * Monta uma linha por deal — abertos primeiro, cada grupo por updated_at desc.
 * Casa stage por deal.id, e não por pipeline_id: é o que torna dois deals
 * abertos no mesmo funil independentemente editáveis.
 */
export function buildDealRows(deals: LeadDeal[], stagesByPipeline: StagesByPipeline): DealRow[] {
  const rows = deals.map((deal) => {
    const stages = stagesByPipeline[deal.pipeline_id ?? ""] ?? [];
    const stageOptions = stages.filter((s) => !s.is_protected);
    const isClosed = isDealClosed(deal);
    return {
      deal,
      isClosed,
      stageOptions,
      stageLabel: deal.pipeline_stages?.label ?? "—",
      dotColor: deal.pipeline_stages?.dot_color || "#dedbd6",
      pipelineName: deal.pipelines?.name ?? "Sem funil",
      reopenStageId: isClosed ? firstOpenStageId(stages) : null,
      canEditStage: !isClosed && stageOptions.length > 0,
    };
  });

  return rows.sort((a, b) => {
    if (a.isClosed !== b.isClosed) return a.isClosed ? 1 : -1;
    return b.deal.updated_at.localeCompare(a.deal.updated_at);
  });
}

/**
 * Patch de reabertura. PATCH /api/deals/[id] grava closed_at ao entrar em stage
 * protegido mas nunca limpa ao sair — sem estes nulls, todo deal reaberto fica
 * com closed_at e lost_reason antigos. O route faz {...body}, então isto
 * resolve sem tocar no backend.
 */
export function reopenPatch(stageId: string): Record<string, unknown> {
  return { stage_id: stageId, closed_at: null, lost_reason: null };
}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

```bash
cd frontend && npx vitest run src/lib/deal-rows.test.ts
```

Expected: PASS — 14 testes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/deal-rows.ts frontend/src/lib/deal-rows.test.ts
git commit -m "feat(conversas): logica de linhas de oportunidade do painel do lead"
```

---

## Task 2: `use-stages-by-pipeline.ts` — stages de N funis

**Files:**
- Create: `frontend/src/hooks/use-stages-by-pipeline.ts`

Sem teste automatizado: é um hook React e o repo não tem infra para testá-los (ver nota no topo). Verificação = `type-check` + `lint` + critério de aceite 2 da Task 5.

- [ ] **Step 1: Criar o hook**

Criar `frontend/src/hooks/use-stages-by-pipeline.ts`:

```ts
"use client";

import { useEffect, useRef, useState } from "react";
import type { StageOption, StagesByPipeline } from "@/lib/deal-rows";

/**
 * Busca os stages de vários funis de uma vez.
 *
 * O painel do lead pode ter deals em funis diferentes, então precisa dos stages
 * de cada um. O cache por pipeline_id sobrevive à troca de conversa: dois leads
 * do mesmo funil não refazem o fetch.
 */
export function useStagesByPipeline(pipelineIds: string[]): {
  stagesByPipeline: StagesByPipeline;
  loading: boolean;
} {
  const cacheRef = useRef<StagesByPipeline>({});
  const [stagesByPipeline, setStagesByPipeline] = useState<StagesByPipeline>({});
  const [loading, setLoading] = useState(false);

  // Chave estável: o array de ids é recriado a cada render do pai, então
  // usá-lo direto como dependência dispararia o efeito para sempre.
  const key = [...pipelineIds].sort().join(",");

  useEffect(() => {
    const ids = key ? key.split(",") : [];
    const missing = ids.filter((id) => !cacheRef.current[id]);

    if (missing.length === 0) {
      setStagesByPipeline({ ...cacheRef.current });
      return;
    }

    const controller = new AbortController();
    setLoading(true);

    Promise.all(
      missing.map((id) =>
        fetch(`/api/pipelines/${id}/stages`, { signal: controller.signal })
          .then((r) => (r.ok ? r.json() : []))
          .then((data) => [id, (Array.isArray(data) ? data : []) as StageOption[]] as const)
          .catch(() => [id, [] as StageOption[]] as const)
      )
    )
      .then((entries) => {
        // Sem este guard, um fetch abortado gravaria [] no cache e o funil
        // ficaria permanentemente sem stages até um reload.
        if (controller.signal.aborted) return;
        for (const [id, stages] of entries) cacheRef.current[id] = stages;
        setStagesByPipeline({ ...cacheRef.current });
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [key]);

  return { stagesByPipeline, loading };
}
```

- [ ] **Step 2: Verificar tipos**

```bash
cd frontend && npm run type-check
```

Expected: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/use-stages-by-pipeline.ts
git commit -m "feat(conversas): hook de stages de multiplos funis"
```

---

## Task 3: `deal-stage-row.tsx` — a linha

**Files:**
- Create: `frontend/src/components/conversas/deal-stage-row.tsx`

- [ ] **Step 1: Criar o componente**

Criar `frontend/src/components/conversas/deal-stage-row.tsx`:

```tsx
"use client";

import { useState } from "react";
import { reopenPatch, type DealRow } from "@/lib/deal-rows";

interface DealStageRowProps {
  row: DealRow;
  /** Resolve em sucesso; LANÇA Error com mensagem legível em falha. */
  onDealUpdate: (dealId: string, patch: Record<string, unknown>) => Promise<void>;
}

export function DealStageRow({ row, onDealUpdate }: DealStageRowProps) {
  const { deal, isClosed, stageOptions, stageLabel, dotColor, pipelineName, reopenStageId, canEditStage } = row;

  // `pending` é o stage escolhido enquanto o PATCH está no ar. Em sucesso, o pai
  // refaz o fetch e deal.stage_id já vem novo; em falha, limpar `pending` reverte
  // sozinho para a verdade do servidor. Sem estado espelhado para dessincronizar.
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = pending !== null;
  const selectedStageId = pending ?? deal.stage_id ?? "";

  async function apply(patch: Record<string, unknown>, optimisticStageId: string) {
    setPending(optimisticStageId);
    setError(null);
    try {
      await onDealUpdate(deal.id, patch);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao atualizar oportunidade.");
    } finally {
      setPending(null);
    }
  }

  return (
    <div
      className={`flex items-start gap-2 p-2 rounded-[6px] border border-[#dedbd6] bg-white ${isClosed ? "opacity-60" : ""}`}
    >
      <span
        className="w-2 h-2 rounded-full flex-shrink-0 mt-1.5"
        style={
          isClosed
            ? { border: `1.5px solid ${dotColor}`, backgroundColor: "transparent" }
            : { backgroundColor: dotColor }
        }
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-[13px] text-[#111111] truncate">{deal.title}</p>
          {deal.value > 0 && (
            <p className="text-[12px] text-[#111111] flex-shrink-0">
              R$ {deal.value.toLocaleString("pt-BR")}
            </p>
          )}
        </div>
        <p className="text-[11px] text-[#7b7b78] truncate">{pipelineName}</p>

        {canEditStage ? (
          <select
            value={selectedStageId}
            disabled={busy}
            aria-label={`Estágio de ${deal.title}`}
            onChange={(e) => apply({ stage_id: e.target.value }, e.target.value)}
            className="mt-1.5 bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none w-full disabled:opacity-60"
          >
            {stageOptions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        ) : (
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="text-[12px] text-[#7b7b78] truncate">{stageLabel}</span>
            {isClosed && reopenStageId && (
              <button
                type="button"
                disabled={busy}
                onClick={() => apply(reopenPatch(reopenStageId), reopenStageId)}
                className="text-[12px] text-[#111111] border border-[#dedbd6] rounded-[4px] px-2 py-0.5 hover:border-[#111111] transition-colors flex-shrink-0 disabled:opacity-60"
              >
                {busy ? "..." : "Reabrir"}
              </button>
            )}
          </div>
        )}

        {isClosed && deal.lost_reason && (
          <p className="text-[11px] text-[#7b7b78] mt-1">⤷ motivo: {deal.lost_reason}</p>
        )}

        {/* Erro por linha, nunca global: com N deals de funis diferentes, um 403
            de permissão num funil não pode borrar o painel inteiro. */}
        {error && <p className="text-[11px] text-[#e53e3e] mt-1">{error}</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos e lint**

```bash
cd frontend && npm run type-check && npm run lint
```

Expected: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversas/deal-stage-row.tsx
git commit -m "feat(conversas): linha de oportunidade com stage editavel"
```

---

## Task 4: Religar o painel

Esta task muda os dois arquivos juntos porque a prop `onDealStageChange` vira
`onDealUpdate`: separar deixaria o `type-check` vermelho entre commits.

**Files:**
- Modify: `frontend/src/components/conversas/contact-detail.tsx`
- Modify: `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`

### 4a — `contact-detail.tsx`

- [ ] **Step 1: Trocar o `LeadDeal` local pelo compartilhado**

Apagar o bloco de tipo local (linhas ~17-27, começa em `interface LeadDeal {`) e importar o do lib. No topo, a linha:

```tsx
import type { Lead, Tag, Conversation, Pipeline, PipelineStage, Sale } from "@/lib/types";
```

vira:

```tsx
import type { Lead, Tag, Conversation, Pipeline, Sale } from "@/lib/types";
import type { LeadDeal } from "@/lib/deal-rows";
```

- [ ] **Step 2: Renomear a prop no `ContactDetailProps`**

```tsx
  onDealStageChange?: (dealId: string, stageId: string) => Promise<void>;
```

vira:

```tsx
  onDealUpdate?: (dealId: string, patch: Record<string, unknown>) => Promise<void>;
```

E no destructuring do componente, `onDealStageChange,` vira `onDealUpdate,`.

- [ ] **Step 3: Fazer o handler lançar em vez de engolir o erro**

Substituir a função inteira:

```tsx
  async function handleDealStageChange(dealId: string, stageId: string) {
    const res = await fetch(`/api/deals/${dealId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_id: stageId }),
    });
    if (res.ok) await fetchDeals();
  }
```

por:

```tsx
  // Lança de propósito: o `if (res.ok)` anterior engolia 403 do guard de funil e
  // 500 em silêncio — o select voltava sozinho e o vendedor não sabia por quê.
  // Quem chama (DealStageRow) captura e mostra o erro na própria linha.
  async function handleDealUpdate(dealId: string, patch: Record<string, unknown>) {
    const res = await fetch(`/api/deals/${dealId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `Erro ao atualizar oportunidade (${res.status}).`);
    }
    await fetchDeals();
  }
```

- [ ] **Step 4: Atualizar a passagem de prop para `CrmPerfilTab`**

```tsx
                onDealStageChange={onDealStageChange ?? handleDealStageChange}
```

vira:

```tsx
                onDealUpdate={onDealUpdate ?? handleDealUpdate}
```

### 4b — `crm-perfil-tab.tsx`

- [ ] **Step 5: Trocar imports e tipos do topo**

Substituir o bloco de imports e o `interface LeadDeal` local. O arquivo hoje começa assim (linhas 1-26); trocar por:

```tsx
"use client";

import { useMemo, useState } from "react";
import { FileTextIcon, Pencil, Trash2 } from "lucide-react";
import { EditableField } from "../editable-field";
import type { Lead, Tag, Quote, Sale } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { CadenceTimeline } from "@/components/conversas/cadence-timeline";
import { DealStageRow } from "@/components/conversas/deal-stage-row";
import { buildDealRows, distinctPipelineIds, type LeadDeal } from "@/lib/deal-rows";
import { useStagesByPipeline } from "@/hooks/use-stages-by-pipeline";
import {
  formatQuoteDate,
  quoteNumberLabel,
  quotePdfHref,
  quoteStatusView,
} from "@/lib/quote-modal-state";
```

Note que `useEffect` e `PipelineStage` saem (deixam de ser usados) e o `interface LeadDeal { ... }` local é apagado.

- [ ] **Step 6: Trocar a prop no `CrmPerfilTabProps`**

```tsx
  onDealStageChange?: (dealId: string, stageId: string) => Promise<void>;
```

vira — **sem `?`, agora é obrigatória**:

```tsx
  onDealUpdate: (dealId: string, patch: Record<string, unknown>) => Promise<void>;
```

E no destructuring, `onDealStageChange,` vira `onDealUpdate,`.

Por que obrigatória: `contact-detail.tsx` sempre fornece um handler (`onDealUpdate ?? handleDealUpdate`). Deixá-la opcional exigiria um fallback no-op na linha, que engoliria a ação em silêncio — exatamente o defeito que esta task existe para matar.

**Atenção:** a prop `pipelines: Pipeline[]` deixa de ser usada pelo componente (era só do select "Funil", que sai no Step 9). Remova `pipelines` de `CrmPerfilTabProps`, do destructuring, e remova a linha `pipelines={pipelines}` da chamada `<CrmPerfilTab ...>` em `contact-detail.tsx`. A variável `pipelines` **continua existindo** em `contact-detail.tsx` — o `DealCreateModal` a consome. Com isso, o import `Pipeline` sai de `crm-perfil-tab.tsx` mas permanece em `contact-detail.tsx`.

- [ ] **Step 7: Apagar o estado morto do topo do componente**

Apagar, do corpo de `CrmPerfilTab`:
- a constante `const CLOSED_KEYS = ["fechado_ganho", "fechado_perdido"];` (acima do componente)
- `const activeDeal = ...`
- os quatro `useState` de `selectedPipelineId`, `selectedStageId`, `stageOptions`, `stageLoading`
- `const dealForSelectedPipeline = ...`
- os dois `useEffect`
- a função `handleStageChange`

Fica, logo abaixo de `const [showTagDropdown, setShowTagDropdown] = useState(false);`:

```tsx
  const pipelineIds = useMemo(() => distinctPipelineIds(deals), [deals]);
  const { stagesByPipeline } = useStagesByPipeline(pipelineIds);
  const dealRows = useMemo(() => buildDealRows(deals, stagesByPipeline), [deals, stagesByPipeline]);
```

- [ ] **Step 8: Inserir a seção Oportunidades no topo do JSX**

Logo depois de `<div className="p-4 space-y-4 text-sm">`, **antes** do bloco de Vendas, inserir:

```tsx
      {/* Oportunidades primeiro: é onde o vendedor decide o que fazer com o
          lead. Uma linha por deal, cada uma com o dropdown do seu próprio
          funil — o painel antigo listava N cards e deixava editar um. */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Oportunidades</span>
          <button
            onClick={onCreateDeal}
            className="w-6 h-6 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111] transition-colors"
            title="Nova oportunidade"
            aria-label="Nova oportunidade"
          >
            <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
            </svg>
          </button>
        </div>
        {dealRows.length === 0 ? (
          <p className="text-[12px] text-[#7b7b78]">Nenhuma oportunidade</p>
        ) : (
          <div className="space-y-2">
            {dealRows.map((row) => (
              <DealStageRow key={row.deal.id} row={row} onDealUpdate={onDealUpdate} />
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-[#dedbd6] pt-4">
```

E o `<div>` que abria a seção Vendas (`<div>` sem classe, logo antes de `<span ...>Vendas</span>`) é substituído pelo `<div className="border-t border-[#dedbd6] pt-4">` acima — ou seja, Vendas ganha a divisória que antes não tinha por ser a primeira seção.

- [ ] **Step 9: Apagar a seção "Estágio" inteira**

Apagar o bloco que começa em:

```tsx
      <div className="border-t border-[#dedbd6] pt-4 space-y-3">
        <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Estágio</h4>
```

e termina no `</div>` que fecha esse bloco, logo após a linha do `EditableField` de "Atribuido a". **Guarde essa linha do EditableField** — ela é reaproveitada no Step 11.

- [ ] **Step 10: Apagar a seção "Oportunidades" antiga (read-only)**

Apagar o bloco que começa em:

```tsx
      <div className="border-t border-[#dedbd6] pt-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Oportunidades</span>
```

e vai até o `</div>` que o fecha, logo antes da seção de Tags. É o bloco que mapeava `deals.map((deal) => { const stage = deal.pipeline_stages; ... })`.

**Cuidado:** depois do Step 8 existem DUAS seções com o título "Oportunidades". A que sai é a de baixo — a que contém `deals.map`. A nova, no topo, contém `dealRows.map`.

- [ ] **Step 11: Mover "Atribuído a" para Identificação**

No bloco de Identificação, logo depois do `EditableField` de Instagram e antes do `</div>` que fecha o bloco, inserir:

```tsx
        <EditableField label="Atribuido a" value={lead.assigned_to} onSave={(v) => onSaveField("assigned_to", v)} placeholder="Ninguem" />
```

- [ ] **Step 12: Verificar tipos, lint e suíte inteira**

```bash
cd frontend && npm run type-check && npm run lint && npm run test
```

Expected: sem erros de tipo, sem erros de lint, todos os testes passando.

Se o lint acusar `pipelines` ou `useEffect` não usados, é sinal de que algum passo de remoção ficou pela metade — volte e complete, não silencie com `eslint-disable`.

- [ ] **Step 13: Commit**

```bash
git add frontend/src/components/conversas/contact-detail.tsx frontend/src/components/conversas/tabs/crm-perfil-tab.tsx
git commit -m "feat(conversas): painel edita todas as oportunidades do lead"
```

---

## Task 5: Verificação final

**Files:** nenhum

- [ ] **Step 1: Suíte completa**

```bash
cd frontend && npm run test
```

Expected: 0 falhas. Anote o total de testes.

- [ ] **Step 2: Type-check e lint**

```bash
cd frontend && npm run type-check && npm run lint
```

Expected: ambos limpos.

- [ ] **Step 3: Build**

```bash
cd frontend && npm run build
```

Expected: build completa sem erro.

**Em worktree, o build precisa de `.env.local`.** Worktrees não herdam arquivos
git-ignored, então `frontend/.env.local` não existe lá e o prerender de `/login`
quebra com *"@supabase/ssr: Your project's URL and API key are required"* — falha
ambiental, não do código. Copie o `.env.local` do checkout principal, rode o
build, e **apague a cópia depois**: são credenciais de produção e não devem ficar
espalhadas por diretórios extras. `.env.build` não serve — o Next não lê esse
nome.

E capture o exit code do **npm**, não o do pipe:

```bash
npm run build > /tmp/build.log 2>&1; echo "EXIT = $?"
```

`npm run build | tail -20` devolve o status do `tail` (sempre 0) e faz um build
quebrado parecer verde.

- [ ] **Step 4: Conferir os critérios de aceite contra o código**

Ler `crm-perfil-tab.tsx` de ponta a ponta e confirmar:

1. Ordem das seções: Oportunidades → Vendas → Orçamentos → Identificação → Empresa B2B → Tags → Cadências.
2. Não existe mais nenhuma ocorrência de `Estágio`, `CLOSED_KEYS`, `selectedPipelineId`, `dealForSelectedPipeline` no arquivo.
3. `Atribuido a` aparece exatamente uma vez, dentro do bloco de Identificação.
4. `Oportunidades` aparece exatamente uma vez.

```bash
cd frontend && grep -n "Estágio\|CLOSED_KEYS\|selectedPipelineId\|dealForSelectedPipeline\|Atribuido a\|Oportunidades" src/components/conversas/tabs/crm-perfil-tab.tsx
```

Expected: só duas linhas — a do `Atribuido a` e a do título `Oportunidades`.

- [ ] **Step 5: Commit final se houver ajuste**

```bash
git add -A && git commit -m "chore(conversas): ajustes finais do painel de oportunidades"
```

(Pule se nada mudou.)

---

## Fora do escopo — não corrigir neste plano

Estão registrados na seção 6 do spec e devem continuar como estão:

1. `GET /api/leads/[id]/deals` não filtra por permissão de funil.
2. `closed_at` sujo ao arrastar card de volta no Kanban.
3. `dedupe_open` não escopado por funil no backend.

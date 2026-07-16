# Importar Leads (CSV) → Selecionar Funil e Etapa — Plano de Implementação

> **Para workers agênticos:** SUB-SKILL OBRIGATÓRIA: Use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar tarefa a tarefa. Os passos usam checkbox (`- [ ]`) para rastreamento.

**Goal:** Permitir que, no modal de importação de CSV, o usuário escolha (opcionalmente) um Funil e uma Etapa; ao importar, criar um card (`deals`) para cada lead nesse funil/etapa, refletindo em tempo real no Kanban.

**Architecture:** O Kanban renderiza a tabela `deals` (não `leads`). Cada card é um `deal` que liga `lead_id` → `pipeline_id` → `stage_id`. A importação hoje só grava `leads`. Vamos: (1) extrair a montagem das linhas de `deals` para um helper puro testável em `src/lib`; (2) estender `POST /api/leads/import` para, quando um funil/etapa for informado, criar os deals (evitando duplicar quando o lead já tem deal naquele funil); (3) adicionar seletores de Funil/Etapa no modal, reaproveitando o padrão do `deal-create-modal`. Nenhuma migration é necessária — todas as colunas já existem. O Kanban atualiza sozinho via realtime em `deals` (`use-realtime-deals.ts`).

**Tech Stack:** Next.js 16 (App Router, Route Handlers), React 19 (Client Component), Supabase JS (service role), Vitest (node env), Tailwind.

**Decisões de produto (confirmadas com o usuário):**
- Seleção de Funil/Etapa é **opcional** (vazio = só importa leads, comportamento atual).
- Card é criado para **todos** os leads importados (novos **e** duplicados existentes).
- **Anti-duplicação:** se o lead já tiver um deal no funil escolhido, **não** cria outro.

**Campos relevantes do schema (verificados em prod):**
- `deals`: `lead_id` (NOT NULL, FK→leads), `title` (NOT NULL), `value` (default 0), `stage` text (NOT NULL, default `'novo'`), `pipeline_id` (nullable, FK→pipelines), `stage_id` (nullable, FK→pipeline_stages).
- `pipeline_stages`: `id`, `pipeline_id`, `label`, `is_protected` (bool), `order_index`. Stages protegidos NÃO devem receber cards manuais.
- `pipelines`: `id`, `name`, `order_index`.

---

### Task 1: Helper puro `buildImportDeals` (TDD)

Lógica pura de montagem das linhas de `deals`: aplica anti-duplicação e monta o título. Isolada para ser testável com a infra existente (vitest, `src/lib/**/*.test.ts`, env node).

**Files:**
- Create: `frontend/src/lib/import-deals.ts`
- Test: `frontend/src/lib/import-deals.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

Criar `frontend/src/lib/import-deals.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildImportDeals, type ImportDealLead } from "@/lib/import-deals";

const leads: ImportDealLead[] = [
  { id: "lead-1", name: "Padaria Sol", phone: "5531999990001" },
  { id: "lead-2", name: null, phone: "5531999990002" },
  { id: "lead-3", name: "Mercado Lua", phone: "5531999990003" },
];

describe("buildImportDeals", () => {
  it("cria uma linha de deal por lead, com pipeline/stage e stage 'novo'", () => {
    const rows = buildImportDeals({
      leads,
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(),
    });
    expect(rows).toHaveLength(3);
    expect(rows[0]).toEqual({
      lead_id: "lead-1",
      title: "Padaria Sol - Leads Frio Disparos",
      value: 0,
      pipeline_id: "pipe-1",
      stage_id: "stage-frio",
      stage: "novo",
    });
  });

  it("usa o telefone como título quando o lead não tem nome", () => {
    const rows = buildImportDeals({
      leads: [leads[1]],
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(),
    });
    expect(rows[0].title).toBe("5531999990002 - Leads Frio Disparos");
  });

  it("pula leads que já têm deal no funil (anti-duplicação)", () => {
    const rows = buildImportDeals({
      leads,
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(["lead-2"]),
    });
    expect(rows.map((r) => r.lead_id)).toEqual(["lead-1", "lead-3"]);
  });

  it("retorna vazio quando todos já têm deal no funil", () => {
    const rows = buildImportDeals({
      leads,
      pipelineId: "pipe-1",
      stageId: "stage-frio",
      pipelineName: "Leads Frio Disparos",
      existingDealLeadIds: new Set<string>(["lead-1", "lead-2", "lead-3"]),
    });
    expect(rows).toEqual([]);
  });
});
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/import-deals.test.ts`
Expected: FAIL — `Cannot find module '@/lib/import-deals'`.

- [ ] **Step 3: Implementar o helper mínimo**

Criar `frontend/src/lib/import-deals.ts`:

```ts
export interface ImportDealLead {
  id: string;
  name: string | null;
  phone: string;
}

export interface ImportDealRow {
  lead_id: string;
  title: string;
  value: number;
  pipeline_id: string;
  stage_id: string;
  stage: string;
}

/**
 * Monta as linhas de `deals` para os leads importados.
 * - Pula leads que já possuem um deal no funil escolhido (anti-duplicação).
 * - Título segue o padrão do deal-create-modal: "<nome ou telefone> - <funil>".
 */
export function buildImportDeals(params: {
  leads: ImportDealLead[];
  pipelineId: string;
  stageId: string;
  pipelineName: string;
  existingDealLeadIds: Set<string>;
}): ImportDealRow[] {
  const { leads, pipelineId, stageId, pipelineName, existingDealLeadIds } = params;
  return leads
    .filter((l) => !existingDealLeadIds.has(l.id))
    .map((l) => ({
      lead_id: l.id,
      title: `${l.name || l.phone} - ${pipelineName}`,
      value: 0,
      pipeline_id: pipelineId,
      stage_id: stageId,
      stage: "novo",
    }));
}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/import-deals.test.ts`
Expected: PASS — 4 testes verdes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/import-deals.ts frontend/src/lib/import-deals.test.ts
git commit -m "feat(leads): helper puro buildImportDeals para importacao com funil/etapa"
```

---

### Task 2: Estender `POST /api/leads/import` para criar deals

Aceitar `pipelineId`/`stageId` opcionais. Após inserir/atualizar leads, quando houver funil: resolver/validar o stage (mesmo padrão de `POST /api/deals`), buscar os leads importados (novos + duplicados), checar deals existentes no funil, montar via `buildImportDeals` e inserir. Retornar `dealsCreated`.

**Files:**
- Modify: `frontend/src/app/api/leads/import/route.ts`

- [ ] **Step 1: Atualizar a tipagem do body e a assinatura**

Em `frontend/src/app/api/leads/import/route.ts`, adicionar o import do helper no topo (logo após o import de `getServiceSupabase`):

```ts
import { buildImportDeals, type ImportDealLead } from "@/lib/import-deals";
```

Substituir o bloco de desestruturação do body (linhas ~20-23):

```ts
  const { leads, skipDuplicates } = (await request.json()) as {
    leads: ImportLead[];
    skipDuplicates: boolean;
  };
```

por:

```ts
  const { leads, skipDuplicates, pipelineId, stageId } = (await request.json()) as {
    leads: ImportLead[];
    skipDuplicates: boolean;
    pipelineId?: string;
    stageId?: string;
  };
```

- [ ] **Step 2: Fazer o insert de leads retornar `id` e `phone`**

Localizar o insert dentro de `if (toInsert.length > 0)` (linha ~68):

```ts
    const { error } = await supabase.from("leads").insert(rows);
    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }
    insertedCount = rows.length;
```

Substituir por (o `.select` é barato e deixa o código pronto para evoluções; a criação de deals abaixo re-busca por telefone para cobrir também os duplicados):

```ts
    const { error } = await supabase.from("leads").insert(rows).select("id, phone");
    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }
    insertedCount = rows.length;
```

- [ ] **Step 3: Adicionar a criação de deals antes do `return` final**

Substituir o bloco final (linhas ~92-96):

```ts
  return NextResponse.json({
    inserted: insertedCount,
    updated: updatedCount,
    skipped: skipped.length,
  });
```

por:

```ts
  let dealsCreated = 0;

  if (pipelineId) {
    // 1. Resolver e validar o stage (mesmo padrão de POST /api/deals):
    //    aceita o stage informado se pertencer ao funil e não for protegido;
    //    caso contrário, usa o primeiro stage não-protegido do funil.
    let resolvedStageId: string | null = null;

    if (stageId) {
      const { data: providedStage } = await supabase
        .from("pipeline_stages")
        .select("id")
        .eq("id", stageId)
        .eq("pipeline_id", pipelineId)
        .eq("is_protected", false)
        .maybeSingle();
      if (providedStage) resolvedStageId = providedStage.id;
    }

    if (!resolvedStageId) {
      const { data: firstStage } = await supabase
        .from("pipeline_stages")
        .select("id")
        .eq("pipeline_id", pipelineId)
        .eq("is_protected", false)
        .order("order_index", { ascending: true })
        .limit(1)
        .maybeSingle();
      resolvedStageId = firstStage?.id ?? null;
    }

    // 2. Nome do funil (para o título do card).
    const { data: pipeline } = await supabase
      .from("pipelines")
      .select("name")
      .eq("id", pipelineId)
      .maybeSingle();

    if (resolvedStageId && pipeline) {
      // 3. Buscar todos os leads importados (novos + duplicados existentes) por telefone.
      const { data: importedLeads } = await supabase
        .from("leads")
        .select("id, name, phone")
        .in("phone", phones);

      const leadList: ImportDealLead[] = (importedLeads ?? []).map((l) => ({
        id: l.id,
        name: l.name,
        phone: l.phone,
      }));

      if (leadList.length > 0) {
        // 4. Quais desses leads já têm deal nesse funil? (anti-duplicação)
        const leadIds = leadList.map((l) => l.id);
        const { data: existingDeals } = await supabase
          .from("deals")
          .select("lead_id")
          .eq("pipeline_id", pipelineId)
          .in("lead_id", leadIds);
        const existingDealLeadIds = new Set(
          (existingDeals ?? []).map((d: { lead_id: string }) => d.lead_id)
        );

        // 5. Montar e inserir os deals.
        const dealRows = buildImportDeals({
          leads: leadList,
          pipelineId,
          stageId: resolvedStageId,
          pipelineName: pipeline.name,
          existingDealLeadIds,
        });

        if (dealRows.length > 0) {
          const { error: dealError } = await supabase.from("deals").insert(dealRows);
          if (dealError) {
            return NextResponse.json({ error: dealError.message }, { status: 500 });
          }
          dealsCreated = dealRows.length;
        }
      }
    }
  }

  return NextResponse.json({
    inserted: insertedCount,
    updated: updatedCount,
    skipped: skipped.length,
    dealsCreated,
  });
```

- [ ] **Step 4: Verificar tipos e lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/app/api/leads/import/route.ts`
Expected: sem erros.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/leads/import/route.ts
git commit -m "feat(leads): import cria deals no funil/etapa selecionado (opcional, anti-duplicacao)"
```

---

### Task 3: Seletores de Funil/Etapa no modal + resultado

Adicionar, no passo "Confirmação" do modal, dois selects (Funil e Etapa) reaproveitando o padrão do `deal-create-modal`: lista de funis via `usePipelines()`, stages via `GET /api/pipelines/{id}/stages` filtrando `is_protected`. Enviar `pipelineId`/`stageId` ao importar (só quando selecionados) e exibir "Cards criados" no resultado.

**Files:**
- Modify: `frontend/src/components/leads/lead-import-modal.tsx`

- [ ] **Step 1: Importar o hook e tipos**

No topo de `frontend/src/components/leads/lead-import-modal.tsx`, após `import Papa from "papaparse";`:

```tsx
import { usePipelines } from "@/hooks/use-pipelines";
import type { PipelineStage } from "@/lib/types";
```

- [ ] **Step 2: Adicionar estado de funil/etapa e o efeito de carregar stages**

Dentro do componente `LeadImportModal`, logo após a linha `const fileRef = useRef<HTMLInputElement>(null);`:

```tsx
  const { pipelines } = usePipelines();
  const [selectedPipelineId, setSelectedPipelineId] = useState("");
  const [selectedStageId, setSelectedStageId] = useState("");
  const [stageOptions, setStageOptions] = useState<PipelineStage[]>([]);
  const [stagesLoading, setStagesLoading] = useState(false);

  useEffect(() => {
    if (!selectedPipelineId) { setStageOptions([]); setSelectedStageId(""); return; }
    const controller = new AbortController();
    setStagesLoading(true);
    fetch(`/api/pipelines/${selectedPipelineId}/stages`, { signal: controller.signal })
      .then((r) => r.json())
      .then((data: PipelineStage[]) => {
        const active = Array.isArray(data) ? data.filter((s) => !s.is_protected) : [];
        setStageOptions(active);
        setSelectedStageId(active[0]?.id || "");
      })
      .catch((e) => { if (e?.name !== "AbortError") { setStageOptions([]); setSelectedStageId(""); } })
      .finally(() => setStagesLoading(false));
    return () => controller.abort();
  }, [selectedPipelineId]);
```

E adicionar `useEffect` ao import do React no topo (linha 3), passando de:

```tsx
import { useState, useRef } from "react";
```

para:

```tsx
import { useState, useRef, useEffect } from "react";
```

- [ ] **Step 3: Enviar pipelineId/stageId no payload de importação**

Em `handleImport`, localizar o `fetch` para `/api/leads/import` e substituir o corpo:

```tsx
      body: JSON.stringify({ leads, skipDuplicates }),
```

por:

```tsx
      body: JSON.stringify({
        leads,
        skipDuplicates,
        ...(selectedPipelineId ? { pipelineId: selectedPipelineId, stageId: selectedStageId } : {}),
      }),
```

- [ ] **Step 4: Atualizar o tipo do `result` para incluir `dealsCreated`**

Localizar a declaração do estado `result` (linha ~58):

```tsx
  const [result, setResult] = useState<{ inserted: number; updated: number; skipped: number; invalidPhones?: number } | null>(null);
```

Substituir por:

```tsx
  const [result, setResult] = useState<{ inserted: number; updated: number; skipped: number; invalidPhones?: number; dealsCreated?: number } | null>(null);
```

- [ ] **Step 5: Renderizar os selects no passo "Confirmação"**

No bloco `{step === "confirm" && !result && (...)}`, inserir o seguinte logo **após** o `</div>` que fecha a caixa "Resumo da importacao" (o `div` com classe `bg-[#faf9f6] ...`) e **antes** do `<label>` do checkbox "Pular leads duplicados":

```tsx
              {/* Destino no Kanban (opcional) */}
              <div className="border border-[#dedbd6] rounded-[8px] p-4 mb-4 space-y-3">
                <p className="text-[13px] font-medium text-[#111111]">Adicionar ao Kanban (opcional)</p>

                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Funil</label>
                  <select
                    value={selectedPipelineId}
                    onChange={(e) => setSelectedPipelineId(e.target.value)}
                    className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                  >
                    <option value="">Não adicionar ao Kanban</option>
                    {pipelines.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
                  </select>
                </div>

                {selectedPipelineId && (
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Etapa</label>
                    {stagesLoading ? (
                      <p className="text-[12px] text-[#7b7b78] py-1">Carregando etapas...</p>
                    ) : stageOptions.length === 0 ? (
                      <p className="text-[12px] text-[#7b7b78] py-1">Nenhuma etapa disponível.</p>
                    ) : (
                      <select
                        value={selectedStageId}
                        onChange={(e) => setSelectedStageId(e.target.value)}
                        className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                      >
                        {stageOptions.map((s) => (<option key={s.id} value={s.id}>{s.label}</option>))}
                      </select>
                    )}
                  </div>
                )}
              </div>
```

- [ ] **Step 6: Exibir "Cards criados" no resultado**

No bloco `{result && (...)}`, dentro da `div` com classe `flex justify-center gap-6 mb-5`, adicionar uma 4ª coluna após a coluna "Pulados":

```tsx
                {(result.dealsCreated ?? 0) > 0 && (
                  <div>
                    <p className="text-[24px] font-semibold text-[#111111]">{result.dealsCreated}</p>
                    <p className="text-[12px] text-[#7b7b78]">Cards criados</p>
                  </div>
                )}
```

- [ ] **Step 7: Verificar tipos e lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/leads/lead-import-modal.tsx`
Expected: sem erros.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/leads/lead-import-modal.tsx
git commit -m "feat(leads): modal de import permite escolher funil/etapa e mostra cards criados"
```

---

### Task 4: Verificação manual end-to-end (dev)

A infra de testes (vitest, env node) não cobre componentes React nem o route handler com Supabase real. Validar manualmente no ambiente dev, conforme o golden rule do CLAUDE.md, **antes** de qualquer push.

**Files:** nenhum (verificação).

- [ ] **Step 1: Subir o ambiente dev**

Usar a VS Code task `Run All Dev (CRM & Backend)` (ou `npm run dev` no `frontend`). Abrir a página de Leads.

- [ ] **Step 2: Importar SEM funil (regressão)**

Importar um CSV com a opção "Funil" em "Não adicionar ao Kanban". Confirmar:
- Resultado mostra Inseridos/Atualizados/Pulados como antes.
- **Não** aparece "Cards criados".
- Nenhum card novo no Kanban.

- [ ] **Step 3: Importar COM funil/etapa**

Importar um CSV (ex: funil "leads frio disparos", etapa "frio"). Confirmar:
- Resultado mostra "Cards criados" = nº de leads válidos.
- No Kanban do funil escolhido, os leads aparecem como cards na etapa correta **sem recarregar a página** (realtime via `use-realtime-deals.ts`).

- [ ] **Step 4: Anti-duplicação**

Reimportar o mesmo CSV no mesmo funil. Confirmar que "Cards criados" = 0 (ou só os realmente novos) e que **não** surgem cards duplicados no funil.

- [ ] **Step 5: Rodar a suíte de testes e o type-check completos**

Run: `cd frontend && npm run test && npm run type-check`
Expected: todos os testes passam; sem erros de tipo.

- [ ] **Step 6: PARAR e avisar o usuário**

Conforme o golden rule: **não fazer push**. Avisar que está pronto para teste no dev e aguardar autorização expressa para `git push origin master`.

---

## Self-Review

**Cobertura do spec:**
- "Selecionar Funil e Etapa no modal" → Task 3 (selects no passo Confirmação). ✓
- "Leads salvos já vinculados ao funil/etapa" → Task 2 (criação de `deals` com `pipeline_id`/`stage_id`). ✓
- "Refletir imediatamente nos cards do Kanban" → Kanban usa realtime em `deals` (`use-realtime-deals.ts`); nenhuma wiring extra necessária. Verificado na Task 4 Step 3. ✓
- "Entender a FK Lead→Funil/Stage" → documentado no header; o vínculo é via tabela `deals` (não em `leads`). ✓
- "Reutilizar UI shadcn existente / não criar componentes desnecessários" → reaproveita selects nativos e o padrão do `deal-create-modal`; nenhum componente novo. ✓
- "Integridade dos dados" → stage validado (pertence ao funil, não-protegido) com fallback; anti-duplicação por funil. ✓

**Placeholders:** nenhum TODO/TBD; todo código está completo nos passos.

**Consistência de tipos:** `buildImportDeals` / `ImportDealLead` / `ImportDealRow` usados de forma idêntica em Task 1 (definição), Task 1 (teste) e Task 2 (route). Body `{ pipelineId, stageId }` casa entre Task 2 (leitura) e Task 3 (envio). `result.dealsCreated` casa entre Task 2 (retorno), Task 3 Step 4 (tipo) e Step 6 (render).

---

## ⚠️ Observação de segurança (fora de escopo desta tarefa)

O advisor do Supabase reporta **RLS desabilitado em 30 tabelas** (incl. `leads`, `deals`, `pipelines`, `pipeline_stages`) — qualquer um com a anon key pode ler/alterar todas as linhas. Este plano usa o service role nas rotas (não piora o quadro), mas vale registrar para decisão futura. Não faz parte desta entrega.

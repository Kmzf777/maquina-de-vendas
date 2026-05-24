# CRM: Stage Hierárquico + Modal "Novo Card" — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o select estático "Status CRM" por seletores hierárquicos Funil→Stage no painel de Conversas; reformular o modal de criação de deal em "Novo Card" com Stage selecionável e campo de Observações.

**Architecture:** O backend aceita `stage_id` opcional no POST de deals. No frontend, o `DealCreateModal` é reformulado com novos campos; o `CrmPerfilTab` substitui a seção "Status CRM" por dois selects dependentes que leem e gravam o deal ativo do lead. Observações são salvas em `lead_notes` (tabela existente) — sem migration de banco.

**Tech Stack:** Next.js App Router (Server + Client Components), TypeScript, Supabase (postgres_changes realtime), fetch nativo (sem react-query), shadcn/ui não é usado diretamente — projeto usa classes CSS customizadas seguindo o padrão existente.

**Branch:** `feat/crm-stage-novo-card` (já criada)

**Spec:** `docs/superpowers/specs/2026-05-24-crm-stage-kanban-improvements-design.md`

---

## Mapa de arquivos

| Arquivo | Tipo | O que muda |
|---|---|---|
| `frontend/src/app/api/deals/route.ts` | Modificar | POST aceita `stage_id` opcional; usa se fornecido e pertence ao pipeline |
| `frontend/src/components/deals/deal-create-modal.tsx` | Modificar | Reformulação completa: remove Título/Valor/Categoria/Data; adiciona Stage select + Observações textarea; nota salva em lead_notes |
| `frontend/src/app/(authenticated)/vendas/page.tsx` | Modificar | Texto botão "Nova Oportunidade" → "Novo Card"; passa `stages` carregados ao modal |
| `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx` | Modificar | Remove seção "Status CRM" com AGENT_STAGES; adiciona seção "Estágio" com Funil select + Stage select dependente |
| `frontend/src/components/conversas/contact-detail.tsx` | Modificar | Adiciona prop `onDealStageChange` e implementa PATCH do deal |

---

## Task 1: Backend — POST /api/deals aceita `stage_id` opcional

**Files:**
- Modify: `frontend/src/app/api/deals/route.ts`

- [ ] **Step 1.1: Editar o handler POST para aceitar `stage_id`**

Abrir `frontend/src/app/api/deals/route.ts`. Substituir o bloco completo do handler POST (a partir de `export async function POST`) pelo seguinte:

```typescript
export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  if (!body.pipeline_id) return NextResponse.json({ error: "pipeline_id é obrigatório" }, { status: 400 });
  if (!body.lead_id || !body.title?.trim()) return NextResponse.json({ error: "lead_id e title são obrigatórios" }, { status: 400 });

  let stageId: string | null = null;

  if (body.stage_id) {
    // Validar que o stage pertence ao pipeline informado
    const { data: providedStage } = await supabase
      .from("pipeline_stages")
      .select("id")
      .eq("id", body.stage_id)
      .eq("pipeline_id", body.pipeline_id)
      .eq("is_protected", false)
      .maybeSingle();
    if (providedStage) stageId = providedStage.id;
  }

  if (!stageId) {
    // Fallback: usar o primeiro stage não-protegido do pipeline
    const { data: firstStage, error: stageError } = await supabase
      .from("pipeline_stages")
      .select("id")
      .eq("pipeline_id", body.pipeline_id)
      .eq("is_protected", false)
      .order("order_index", { ascending: true })
      .limit(1)
      .maybeSingle();
    if (stageError) return NextResponse.json({ error: stageError.message }, { status: 500 });
    if (!firstStage) return NextResponse.json({ error: "Funil não tem stages disponíveis." }, { status: 422 });
    stageId = firstStage.id;
  }

  const { data, error } = await supabase
    .from("deals")
    .insert({
      lead_id: body.lead_id,
      title: body.title,
      value: body.value || 0,
      pipeline_id: body.pipeline_id,
      stage_id: stageId,
      stage: "novo",
      category: body.category || null,
      expected_close_date: body.expected_close_date || null,
      assigned_to: body.assigned_to || null,
    })
    .select("*, leads(id, name, company, phone, nome_fantasia), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 1.2: Verificar TypeScript**

```powershell
cd frontend; npx tsc --noEmit 2>&1 | Select-String "deals/route"
```

Expected: sem linhas de erro referentes a `deals/route`.

- [ ] **Step 1.3: Commit**

```powershell
cd ..; git add frontend/src/app/api/deals/route.ts
git commit -m "feat(api): deals POST aceita stage_id opcional para posicionamento inicial"
```

---

## Task 2: Reformular DealCreateModal → "Novo Card"

**Files:**
- Modify: `frontend/src/components/deals/deal-create-modal.tsx`

O modal passará a ter: Lead (combobox existente), Funil (select), Stage (select dependente, carregado via fetch), Observações (textarea). Título é gerado automaticamente. Após criar o deal, se observações preenchidas, POST em `/api/leads/{lead_id}/notes`.

A interface `DealCreateModalProps.onCreate` ganha o campo `stage_id?: string` mas mantém compatibilidade com todos os callers existentes.

- [ ] **Step 2.1: Reescrever `deal-create-modal.tsx`**

Substituir o conteúdo completo de `frontend/src/components/deals/deal-create-modal.tsx` por:

```typescript
"use client";

import { useState, useEffect } from "react";
import type { Lead, Pipeline, PipelineStage } from "@/lib/types";

interface DealCreateModalProps {
  leads: Lead[];
  pipelines?: Pipeline[];
  preselectedLead?: Lead;
  onClose: () => void;
  onCreate: (data: {
    lead_id: string;
    title: string;
    value: number;
    category: string;
    expected_close_date: string;
    pipeline_id?: string;
    stage_id?: string;
  }) => Promise<void>;
}

export function DealCreateModal({ leads, pipelines, preselectedLead, onClose, onCreate }: DealCreateModalProps) {
  const [leadSearch, setLeadSearch] = useState("");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(preselectedLead ?? null);
  const [selectedLeadId, setSelectedLeadId] = useState(preselectedLead?.id || "");
  const [selectedPipelineId, setSelectedPipelineId] = useState(pipelines?.[0]?.id || "");
  const [selectedStageId, setSelectedStageId] = useState("");
  const [stageOptions, setStageOptions] = useState<PipelineStage[]>([]);
  const [notes, setNotes] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Carregar stages quando pipeline muda
  useEffect(() => {
    if (!selectedPipelineId) { setStageOptions([]); setSelectedStageId(""); return; }
    fetch(`/api/pipelines/${selectedPipelineId}/stages`)
      .then((r) => r.json())
      .then((data: PipelineStage[]) => {
        const active = Array.isArray(data) ? data.filter((s) => !s.is_protected) : [];
        setStageOptions(active);
        setSelectedStageId(active[0]?.id || "");
      })
      .catch(() => { setStageOptions([]); setSelectedStageId(""); });
  }, [selectedPipelineId]);

  const filteredLeads = leadSearch.trim()
    ? leads.filter((l) => {
        const q = leadSearch.toLowerCase();
        return (l.name || "").toLowerCase().includes(q) || l.phone.includes(q) || (l.company || "").toLowerCase().includes(q);
      }).slice(0, 30)
    : leads.slice(0, 20);

  function handleSelectLead(l: Lead) {
    setSelectedLead(l);
    setSelectedLeadId(l.id);
    setLeadSearch("");
    setShowDropdown(false);
  }

  function handleClearLead() {
    setSelectedLead(null);
    setSelectedLeadId("");
    setLeadSearch("");
    setShowDropdown(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedLeadId || !selectedPipelineId || !selectedStageId) return;
    setSaving(true);
    setError(null);

    const pipeline = pipelines?.find((p) => p.id === selectedPipelineId);
    const leadName = selectedLead?.name || selectedLead?.phone || "Lead";
    const autoTitle = `${leadName} - ${pipeline?.name || "Funil"}`;

    try {
      await onCreate({
        lead_id: selectedLeadId,
        title: autoTitle,
        value: 0,
        category: "",
        expected_close_date: "",
        pipeline_id: selectedPipelineId,
        stage_id: selectedStageId,
      });

      // Salvar observações em lead_notes (se preenchidas)
      if (notes.trim()) {
        await fetch(`/api/leads/${selectedLeadId}/notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ author: "Usuário", content: notes.trim() }),
        });
      }

      onClose();
    } catch (err) {
      setSaving(false);
      setError(err instanceof Error ? err.message : "Erro ao criar card.");
    }
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-normal text-[#111111] mb-4" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>
          Novo Card
        </h3>
        <form onSubmit={handleSubmit} className="space-y-4">

          {/* Lead */}
          <div className="relative">
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Lead *</label>
            {selectedLead ? (
              <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2.5 flex items-center justify-between">
                <div className="flex flex-col gap-0.5">
                  <span className="text-[14px] font-medium text-[#111111] leading-tight">{selectedLead.name || selectedLead.phone}</span>
                  <span className="text-[12px] text-[#7b7b78] leading-tight">{selectedLead.phone}</span>
                </div>
                {!preselectedLead && (
                  <button type="button" onClick={handleClearLead} className="text-[#7b7b78] hover:text-[#111111] transition-colors text-[18px] leading-none pl-3 flex-shrink-0" title="Remover lead">×</button>
                )}
              </div>
            ) : (
              <>
                <input
                  value={leadSearch}
                  onChange={(e) => { setLeadSearch(e.target.value); setShowDropdown(true); }}
                  onFocus={() => setShowDropdown(true)}
                  onBlur={() => setTimeout(() => setShowDropdown(false), 150)}
                  placeholder="Buscar por nome, telefone ou empresa..."
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  autoComplete="off"
                />
                {showDropdown && (
                  <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-[#dedbd6] rounded-[6px] z-10 max-h-52 overflow-y-auto shadow-sm">
                    {filteredLeads.length === 0 ? (
                      <p className="px-3 py-2.5 text-[13px] text-[#7b7b78]">Nenhum lead encontrado.</p>
                    ) : (
                      <>
                        {!leadSearch.trim() && (
                          <div className="px-3 py-1.5 border-b border-[#f0ede8]">
                            <span className="text-[10px] uppercase tracking-[0.8px] text-[#7b7b78]">Recentes</span>
                          </div>
                        )}
                        {filteredLeads.map((l) => (
                          <button key={l.id} type="button" onMouseDown={() => handleSelectLead(l)}
                            className="w-full text-left px-3 py-2 hover:bg-[#faf9f6] flex items-center justify-between gap-3 transition-colors">
                            <span className="text-[13px] text-[#111111] font-medium truncate">{l.name || l.phone}</span>
                            <span className="text-[12px] text-[#7b7b78] flex-shrink-0">{l.phone}</span>
                          </button>
                        ))}
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Funil */}
          {pipelines && pipelines.length > 0 && (
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Funil *</label>
              <select
                value={selectedPipelineId}
                onChange={(e) => setSelectedPipelineId(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                required
              >
                <option value="">Selecionar funil...</option>
                {pipelines.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
              </select>
            </div>
          )}

          {/* Stage (dependente do funil) */}
          {selectedPipelineId && (
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Stage *</label>
              {stageOptions.length === 0 ? (
                <p className="text-[12px] text-[#7b7b78] py-1">Carregando stages...</p>
              ) : (
                <select
                  value={selectedStageId}
                  onChange={(e) => setSelectedStageId(e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                  required
                >
                  {stageOptions.map((s) => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
              )}
            </div>
          )}

          {/* Observações */}
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Observações</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Anotações sobre este lead ou oportunidade..."
              rows={3}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full resize-none"
            />
          </div>

          {error && (
            <p className="text-[12px] text-red-600 bg-red-50 border border-red-200 rounded-[6px] px-3 py-2">{error}</p>
          )}

          <div className="flex gap-2 justify-end pt-2">
            <button type="button" onClick={onClose} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">Cancelar</button>
            <button
              type="submit"
              disabled={saving || !selectedLeadId || !selectedPipelineId || !selectedStageId}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
            >
              {saving ? "Criando..." : "Criar Card"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2.2: Verificar TypeScript**

```powershell
cd frontend; npx tsc --noEmit 2>&1 | Select-String "deal-create-modal"
```

Expected: sem erros referentes ao arquivo.

- [ ] **Step 2.3: Commit**

```powershell
cd ..; git add frontend/src/components/deals/deal-create-modal.tsx
git commit -m "feat(ui): reformular DealCreateModal como Novo Card com Stage e Observações"
```

---

## Task 3: VendasPage — Renomear botão "Nova Oportunidade" → "Novo Card"

**Files:**
- Modify: `frontend/src/app/(authenticated)/vendas/page.tsx`

- [ ] **Step 3.1: Alterar o texto do botão**

Em `frontend/src/app/(authenticated)/vendas/page.tsx`, localizar a linha (aprox. 294):
```typescript
          Nova Oportunidade
```
Substituir por:
```typescript
          Novo Card
```

Também verificar se `DealCreateModal` recebe `pipelines` — no `vendas/page.tsx` ele é chamado na linha ~346:
```typescript
      {showCreate && selectedPipelineId && (
        <DealCreateModal leads={leads} onClose={() => setShowCreate(false)} onCreate={handleCreateDeal} />
      )}
```

`pipelines` já está em estado local (`pipelines`). Adicionar ao DealCreateModal:
```typescript
      {showCreate && selectedPipelineId && (
        <DealCreateModal leads={leads} pipelines={pipelines} onClose={() => setShowCreate(false)} onCreate={handleCreateDeal} />
      )}
```

- [ ] **Step 3.2: Verificar TypeScript**

```powershell
cd frontend; npx tsc --noEmit 2>&1 | Select-String "vendas"
```

Expected: sem erros.

- [ ] **Step 3.3: Commit**

```powershell
cd ..; git add "frontend/src/app/(authenticated)/vendas/page.tsx"
git commit -m "feat(ui): renomear botão Nova Oportunidade para Novo Card"
```

---

## Task 4: ContactDetail — Adicionar callback `onDealStageChange`

**Files:**
- Modify: `frontend/src/components/conversas/contact-detail.tsx`

O `CrmPerfilTab` precisará chamar `onDealStageChange(dealId, stageId)` para fazer PATCH no deal. Essa callback é implementada em `contact-detail.tsx`.

- [ ] **Step 4.1: Adicionar `onDealStageChange` ao ContactDetail**

Em `frontend/src/components/conversas/contact-detail.tsx`:

**1. Adicionar o tipo `onDealStageChange` na interface `ContactDetailProps` (linha ~36, após `onLeadUpdate`):**
```typescript
  onDealStageChange?: (dealId: string, stageId: string) => Promise<void>;
```

**2. Adicionar o parâmetro na desestruturação da função (linha ~50):**
```typescript
export function ContactDetail({
  conversation,
  tags,
  leadTags,
  onTagToggle,
  onBack,
  aiEnabled,
  togglingAi,
  onToggleAi,
  onLeadUpdate,
  onDealStageChange,
}: ContactDetailProps) {
```

**3. Implementar a função `handleDealStageChange` dentro do componente (após `handleCreateDeal`, aprox. linha ~131):**
```typescript
  async function handleDealStageChange(dealId: string, stageId: string) {
    const res = await fetch(`/api/deals/${dealId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_id: stageId }),
    });
    if (res.ok) await fetchDeals();
  }
```

**4. Passar a callback para `CrmPerfilTab` (dentro do `{activeTab === "perfil" && ...}`, aprox. linha ~216):**

Localizar:
```typescript
              <CrmPerfilTab
                lead={lead}
                onSaveField={updateLeadField}
                deals={deals}
                pipelines={pipelines}
                tags={tags}
                leadTags={leadTags}
                onTagToggle={onTagToggle}
                onCreateDeal={() => setShowCreateDeal(true)}
                sales={sales}
                onCreateSale={() => setShowCreateSale(true)}
              />
```

Substituir por:
```typescript
              <CrmPerfilTab
                lead={lead}
                onSaveField={updateLeadField}
                deals={deals}
                pipelines={pipelines}
                tags={tags}
                leadTags={leadTags}
                onTagToggle={onTagToggle}
                onCreateDeal={() => setShowCreateDeal(true)}
                onDealStageChange={onDealStageChange ?? handleDealStageChange}
                sales={sales}
                onCreateSale={() => setShowCreateSale(true)}
              />
```

- [ ] **Step 4.2: Verificar TypeScript**

```powershell
cd frontend; npx tsc --noEmit 2>&1 | Select-String "contact-detail"
```

Expected: sem erros.

- [ ] **Step 4.3: Commit**

```powershell
cd ..; git add frontend/src/components/conversas/contact-detail.tsx
git commit -m "feat(ui): ContactDetail expõe onDealStageChange para CrmPerfilTab"
```

---

## Task 5: CrmPerfilTab — Substituir "Status CRM" por Funil+Stage hierárquico

**Files:**
- Modify: `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`

Esta é a maior mudança. A seção "Status CRM" (linhas 140–155) é substituída por dois selects dependentes que controlam o deal ativo do lead.

**Lógica chave:**
- `activeDeal` = primeiro elemento de `deals` (sorted by updated_at desc) cujo `pipeline_stages.key` não é `"fechado_ganho"` nem `"fechado_perdido"`
- Funil select: lista `pipelines[]`; pré-selecionado com `activeDeal.pipeline_id`
- Stage select: carregado via fetch ao mudar Funil; pré-selecionado com deal-do-pipeline-selecionado.stage_id ou first stage
- Ao mudar Stage: chama `onDealStageChange(dealId, newStageId)` para PATCH

- [ ] **Step 5.1: Atualizar a interface e imports em `crm-perfil-tab.tsx`**

Localizar no topo do arquivo:
```typescript
import { AGENT_STAGES } from "@/lib/constants";
```
Remover essa linha (já não será usada).

Localizar a interface `CrmPerfilTabProps` e adicionar o novo campo após `onCreateDeal`:
```typescript
  onDealStageChange?: (dealId: string, stageId: string) => Promise<void>;
```

Adicionar `useEffect` ao import do React:
```typescript
import { useState, useEffect } from "react";
```
(verificar se já está — caso `useState` já esteja importado, adicionar `useEffect` à mesma linha)

- [ ] **Step 5.2: Adicionar estado e lógica de stages ao componente**

Logo após a linha `const [showTagDropdown, setShowTagDropdown] = useState(false);` (aprox. linha 52), adicionar:

```typescript
  // --- Lógica Funil+Stage ---
  const CLOSED_KEYS = ["fechado_ganho", "fechado_perdido"];
  const activeDeal = deals.find((d) => !CLOSED_KEYS.includes(d.pipeline_stages?.key ?? "")) ?? null;

  const [selectedPipelineId, setSelectedPipelineId] = useState<string>(activeDeal?.pipeline_id ?? "");
  const [selectedStageId, setSelectedStageId] = useState<string>(activeDeal?.stage_id ?? "");
  const [stageOptions, setStageOptions] = useState<Array<{ id: string; label: string; dot_color: string }>>([]);
  const [stageLoading, setStageLoading] = useState(false);

  // Deal correspondente ao funil selecionado (pode ser null se lead não tem deal ali)
  const dealForSelectedPipeline = deals.find(
    (d) => d.pipeline_id === selectedPipelineId && !CLOSED_KEYS.includes(d.pipeline_stages?.key ?? "")
  ) ?? null;

  useEffect(() => {
    if (!selectedPipelineId) { setStageOptions([]); return; }
    setStageLoading(true);
    fetch(`/api/pipelines/${selectedPipelineId}/stages`)
      .then((r) => r.json())
      .then((data) => {
        const active = Array.isArray(data) ? data.filter((s: { is_protected: boolean }) => !s.is_protected) : [];
        setStageOptions(active);
        // Pré-selecionar: stage do deal neste pipeline (se houver), ou primeiro stage
        const dealStage = deals.find(
          (d) => d.pipeline_id === selectedPipelineId && !CLOSED_KEYS.includes(d.pipeline_stages?.key ?? "")
        )?.stage_id;
        setSelectedStageId(dealStage ?? active[0]?.id ?? "");
      })
      .catch(() => setStageOptions([]))
      .finally(() => setStageLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPipelineId]);

  async function handleStageChange(newStageId: string) {
    setSelectedStageId(newStageId);
    if (!dealForSelectedPipeline) return;
    await onDealStageChange?.(dealForSelectedPipeline.id, newStageId);
  }
  // --- fim Funil+Stage ---
```

- [ ] **Step 5.3: Adicionar `onDealStageChange` na desestruturação da função**

Localizar a linha que começa `export function CrmPerfilTab({` e adicionar `onDealStageChange` junto com os outros parâmetros:

```typescript
export function CrmPerfilTab({
  lead,
  onSaveField,
  deals,
  pipelines,
  tags,
  leadTags,
  onTagToggle,
  onCreateDeal,
  onDealStageChange,
  sales,
  onCreateSale,
}: CrmPerfilTabProps) {
```

- [ ] **Step 5.4: Substituir seção "Status CRM" no JSX**

Localizar o bloco (aprox. linha 140–155):
```tsx
      <div className="border-t border-[#dedbd6] pt-4 space-y-3">
        <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Status CRM</h4>
        <div>
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">Stage</span>
          <select
            value={lead.stage}
            onChange={(e) => onSaveField("stage", e.target.value)}
            className="bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
          >
            {AGENT_STAGES.map((s) => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </select>
        </div>
        <EditableField label="Atribuido a" value={lead.assigned_to} onSave={(v) => onSaveField("assigned_to", v)} placeholder="Ninguem" />
      </div>
```

Substituir por:
```tsx
      <div className="border-t border-[#dedbd6] pt-4 space-y-3">
        <h4 className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Estágio</h4>

        {pipelines.length === 0 ? (
          <p className="text-[12px] text-[#7b7b78]">Nenhum funil configurado.</p>
        ) : activeDeal === null && selectedPipelineId === "" ? (
          <div className="flex flex-col gap-2">
            <p className="text-[12px] text-[#7b7b78]">Sem oportunidade ativa.</p>
            <button
              onClick={onCreateDeal}
              className="text-[12px] text-[#111111] border border-[#dedbd6] rounded-[4px] px-2.5 py-1 hover:border-[#111111] transition-colors w-fit"
            >
              + Criar Card
            </button>
          </div>
        ) : (
          <>
            {/* Funil */}
            <div>
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">Funil</span>
              <select
                value={selectedPipelineId}
                onChange={(e) => setSelectedPipelineId(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              >
                <option value="">Selecionar funil...</option>
                {pipelines.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            {/* Stage */}
            <div>
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1 block">Stage</span>
              {stageLoading ? (
                <p className="text-[12px] text-[#7b7b78] py-1">Carregando...</p>
              ) : stageOptions.length === 0 ? (
                <p className="text-[12px] text-[#7b7b78] py-1">Nenhum stage disponível.</p>
              ) : dealForSelectedPipeline ? (
                <select
                  value={selectedStageId}
                  onChange={(e) => handleStageChange(e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  {stageOptions.map((s) => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <p className="text-[12px] text-[#7b7b78]">Sem deal neste funil.</p>
                  <button
                    onClick={onCreateDeal}
                    className="text-[12px] text-[#111111] border border-[#dedbd6] rounded-[4px] px-2.5 py-1 hover:border-[#111111] transition-colors w-fit"
                  >
                    + Criar Card
                  </button>
                </div>
              )}
            </div>
          </>
        )}

        <EditableField label="Atribuido a" value={lead.assigned_to} onSave={(v) => onSaveField("assigned_to", v)} placeholder="Ninguem" />
      </div>
```

- [ ] **Step 5.5: Verificar TypeScript**

```powershell
cd frontend; npx tsc --noEmit 2>&1
```

Expected: 0 errors. Corrigir qualquer erro antes de continuar.

- [ ] **Step 5.6: Commit**

```powershell
cd ..; git add frontend/src/components/conversas/tabs/crm-perfil-tab.tsx
git commit -m "feat(ui): CrmPerfilTab — substituir Status CRM por seletores Funil+Stage hierárquicos"
```

---

## Task 6: Verificação manual e commit final

- [ ] **Step 6.1: Iniciar o servidor de dev**

```powershell
# Na raiz do projeto, usando a VS Code task ou:
cd frontend; npm run dev
```

- [ ] **Step 6.2: Testar Modal "Novo Card" em `/vendas`**

1. Abrir `http://localhost:3000/vendas`
2. Verificar que o botão diz **"Novo Card"** (não "Nova Oportunidade")
3. Clicar "Novo Card" → modal abre com título "Novo Card"
4. Confirmar que os campos são: Lead (combobox), Funil (select), Stage (select — aparece após selecionar funil), Observações (textarea)
5. Confirmar que Título, Valor, Categoria, Data de previsão **não aparecem**
6. Selecionar um lead, funil e stage → clicar "Criar Card"
7. Verificar que o card aparece na coluna correta do Kanban

- [ ] **Step 6.3: Testar Stage dependente**

1. No modal "Novo Card", selecionar um funil
2. Verificar que o select de Stage carrega as opções do funil
3. Trocar o funil → Stage recarrega com opções do novo funil

- [ ] **Step 6.4: Testar seção "Estágio" em `/conversas`**

1. Abrir `http://localhost:3000/conversas`
2. Selecionar uma conversa com lead que tem deal ativo
3. No painel direito → aba "Perfil"
4. Verificar que **não existe** seção "Status CRM" e que existe seção **"Estágio"**
5. Verificar que o funil pré-selecionado é o funil do deal mais recente
6. Trocar o Stage → verificar que o deal foi atualizado (recarregar a página `/vendas` e confirmar a coluna do card)
7. Trocar o Funil → Stage recarrega com opções do novo funil

- [ ] **Step 6.5: Testar lead sem deal ativo**

1. Abrir uma conversa cujo lead não tem deals
2. Verificar que a seção "Estágio" mostra "Sem oportunidade ativa" + botão "+ Criar Card"
3. Clicar "+ Criar Card" → modal "Novo Card" deve abrir com o lead pré-selecionado

- [ ] **Step 6.6: Commit final**

```powershell
cd "C:\Users\kelwi\Desktop\maquina-de-vendas"
git add -A
git commit -m "chore: verificação manual concluída — CRM Stage + Novo Card"
```

---

## Self-review do plano

**Spec coverage:**
- ✅ Seção "Status CRM" renomeada para "Estágio" → Task 5
- ✅ Dois dropdowns dependentes (Funil → Stage) → Task 5
- ✅ Stage lê e grava deal ativo do lead → Task 5
- ✅ `lead.stage` da IA não é tocado → não há mudança no campo `lead.stage` em nenhuma task
- ✅ Campo "Atribuído a" mantido → Task 5 (EditableField preservado)
- ✅ Botão "Novo Card" → Task 3
- ✅ Stage selecionável no modal → Task 2
- ✅ Observações → lead_notes → Task 2
- ✅ Título auto-gerado → Task 2
- ✅ Backend aceita stage_id → Task 1
- ✅ Kanban já dinâmico → sem task (já funcional)

**Placeholders:** nenhum TBD encontrado.

**Consistência de tipos:**
- `onDealStageChange: (dealId: string, stageId: string) => Promise<void>` — definido em Task 4, consumido em Task 5 ✅
- `DealCreateModalProps.onCreate` — `stage_id?: string` adicionado em Task 2, backend aceita em Task 1 ✅
- `PipelineStage` do fetch em Task 5 usa `{ id, label, dot_color }` — compatível com o que a API `/api/pipelines/{id}/stages` retorna ✅

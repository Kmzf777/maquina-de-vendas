# Melhorias UX Modal Novo Disparo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Melhorar a UX do modal de "Novo Disparo" eliminando campos legados, adicionando filtro em tempo real, Shift+Click na tabela de leads, fechamento via ESC, visibilidade condicional do campo Agente, e um fluxo pós-criação com AlertDialog.

**Architecture:** Edição inline em 4 arquivos existentes (sem nova abstração). O `AlertDialog` é criado como novo componente UI usando `radix-ui` (já instalado). O `LeadFilterPanel` passa a chamar `onApply` automaticamente via `useEffect` + debounce, eliminando o botão "Aplicar". O modal recebe ESC handler, remoção de intervalos, Shift+Click, e fluxo pós-criação com `AlertDialog` + `router.push`.

**Tech Stack:** Next.js 14 (App Router), React, TypeScript, Tailwind CSS, `radix-ui ^1.4.3` (pacote unificado Radix)

**Branch:** `fix/melhorias-modal-disparo` (já criada e ativa)

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `frontend/src/lib/types.ts` | Modify | Adicionar `mode` ao `Channel` interface |
| `frontend/src/components/ui/alert-dialog.tsx` | Create | Componente AlertDialog (shadcn/ui style, Radix primitivo) |
| `frontend/src/components/campaigns/lead-filter-panel.tsx` | Modify | Filtro em tempo real, remover botão "Aplicar" |
| `frontend/src/components/campaigns/create-broadcast-modal.tsx` | Modify | ESC, mode=human, intervalos, Shift+Click, pós-criação |

---

## Task 1: Adicionar `mode` ao tipo `Channel`

**Files:**
- Modify: `frontend/src/lib/types.ts` (linha ~226)

- [ ] **Step 1: Editar o tipo `Channel`**

Localizar a interface `Channel` em `frontend/src/lib/types.ts` (linha 226). Ela está assim:

```ts
export interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud" | "evolution";
  provider_config: Record<string, string>;
  agent_profile_id: string | null;
  agent_profiles?: { id: string; name: string } | null;
  is_active: boolean;
  created_at: string;
}
```

Adicionar `mode` logo após `agent_profiles`:

```ts
export interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud" | "evolution";
  provider_config: Record<string, string>;
  agent_profile_id: string | null;
  agent_profiles?: { id: string; name: string } | null;
  mode?: "ai" | "human";
  is_active: boolean;
  created_at: string;
}
```

- [ ] **Step 2: Verificar que TypeScript não quebra**

```powershell
cd frontend
npx tsc --noEmit 2>&1 | Select-Object -First 20
```

Esperado: sem erros novos relacionados a `Channel.mode`.

- [ ] **Step 3: Commitar**

```powershell
git add frontend/src/lib/types.ts
git commit -m "feat(types): adicionar campo mode ao Channel interface"
```

---

## Task 2: Criar componente `AlertDialog`

**Files:**
- Create: `frontend/src/components/ui/alert-dialog.tsx`

- [ ] **Step 1: Criar o arquivo**

Criar `frontend/src/components/ui/alert-dialog.tsx` com o conteúdo abaixo. O `radix-ui ^1.4.3` (pacote unificado) já está instalado e exporta `AlertDialog` de `radix-ui/alert-dialog`.

```tsx
"use client";

import * as React from "react";
import * as AlertDialogPrimitive from "radix-ui/alert-dialog";

const AlertDialog = AlertDialogPrimitive.Root;
const AlertDialogTrigger = AlertDialogPrimitive.Trigger;
const AlertDialogPortal = AlertDialogPrimitive.Portal;

const AlertDialogOverlay = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Overlay
    ref={ref}
    className={`fixed inset-0 z-50 bg-[#111111]/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 ${className ?? ""}`}
    {...props}
  />
));
AlertDialogOverlay.displayName = "AlertDialogOverlay";

const AlertDialogContent = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <AlertDialogPortal>
    <AlertDialogOverlay />
    <AlertDialogPrimitive.Content
      ref={ref}
      className={`fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-full max-w-[420px] bg-white border border-[#dedbd6] rounded-[8px] p-6 shadow-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 ${className ?? ""}`}
      {...props}
    >
      {children}
    </AlertDialogPrimitive.Content>
  </AlertDialogPortal>
));
AlertDialogContent.displayName = "AlertDialogContent";

const AlertDialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={`flex flex-col gap-2 text-left mb-4 ${className ?? ""}`} {...props} />
);
AlertDialogHeader.displayName = "AlertDialogHeader";

const AlertDialogFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={`flex justify-end gap-3 mt-6 ${className ?? ""}`} {...props} />
);
AlertDialogFooter.displayName = "AlertDialogFooter";

const AlertDialogTitle = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Title
    ref={ref}
    className={`text-[15px] font-medium text-[#111111] ${className ?? ""}`}
    {...props}
  />
));
AlertDialogTitle.displayName = "AlertDialogTitle";

const AlertDialogDescription = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Description
    ref={ref}
    className={`text-[13px] text-[#7b7b78] leading-relaxed ${className ?? ""}`}
    {...props}
  />
));
AlertDialogDescription.displayName = "AlertDialogDescription";

const AlertDialogAction = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Action>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Action>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Action
    ref={ref}
    className={`bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-105 active:scale-[0.95] disabled:opacity-40 ${className ?? ""}`}
    {...props}
  />
));
AlertDialogAction.displayName = "AlertDialogAction";

const AlertDialogCancel = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Cancel>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Cancel>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Cancel
    ref={ref}
    className={`bg-transparent text-[#111111] border border-[#dedbd6] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-105 active:scale-[0.95] hover:border-[#111111] ${className ?? ""}`}
    {...props}
  />
));
AlertDialogCancel.displayName = "AlertDialogCancel";

export {
  AlertDialog,
  AlertDialogPortal,
  AlertDialogOverlay,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
};
```

- [ ] **Step 2: Verificar que `radix-ui/alert-dialog` resolve**

```powershell
cd frontend
node -e "require('radix-ui/alert-dialog'); console.log('ok')"
```

Se falhar com "Cannot find module", verificar se o caminho é `radix-ui` (sem subpath). Alternativa: `import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog"` — mas neste projeto usa-se o pacote unificado `radix-ui`.

> **Nota de fallback:** Se `radix-ui/alert-dialog` não resolver, usar o import de `@radix-ui/react-alert-dialog`. Verificar no `node_modules` quais subpaths o pacote `radix-ui` expõe.

- [ ] **Step 3: Verificar TypeScript**

```powershell
npx tsc --noEmit 2>&1 | Select-Object -First 20
```

Esperado: sem erros no arquivo criado.

- [ ] **Step 4: Commitar**

```powershell
git add frontend/src/components/ui/alert-dialog.tsx
git commit -m "feat(ui): criar componente AlertDialog (Radix/shadcn-style)"
```

---

## Task 3: LeadFilterPanel — filtro em tempo real

**Files:**
- Modify: `frontend/src/components/campaigns/lead-filter-panel.tsx`

O arquivo atual tem 166 linhas. A mudança remove o botão "Aplicar filtros" e adiciona lógica de debounce + `useEffect` para disparar `onApply` automaticamente.

- [ ] **Step 1: Reescrever `lead-filter-panel.tsx`**

Substituir o conteúdo completo do arquivo por:

```tsx
// frontend/src/components/campaigns/lead-filter-panel.tsx
"use client";

import { useState, useEffect, useRef } from "react";
import { DEAL_CATEGORIES } from "@/lib/constants";

interface Pipeline { id: string; name: string; }
interface PipelineStage { id: string; label: string; dot_color: string; }
interface Tag { id: string; name: string; color: string; }

export interface LeadFilters {
  pipelineId: string;
  stageId: string;
  dealCategory: string;
  tagIds: string[];
  noDeal: boolean;
  createdAfter: string;
  createdBefore: string;
  search: string;
}

const EMPTY_FILTERS: LeadFilters = {
  pipelineId: "", stageId: "", dealCategory: "",
  tagIds: [], noDeal: false, createdAfter: "", createdBefore: "", search: "",
};

interface LeadFilterPanelProps {
  onApply: (filters: LeadFilters) => void;
  loading?: boolean;
}

export function LeadFilterPanel({ onApply, loading }: LeadFilterPanelProps) {
  const [filters, setFilters] = useState<LeadFilters>(EMPTY_FILTERS);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    fetch("/api/pipelines").then((r) => r.json()).then((d) => setPipelines(Array.isArray(d) ? d : []));
    fetch("/api/tags").then((r) => r.json()).then((d) => setTags(Array.isArray(d) ? d : []));
  }, []);

  useEffect(() => {
    if (!filters.pipelineId) { setStages([]); setFilters((f) => ({ ...f, stageId: "" })); return; }
    fetch(`/api/pipelines/${filters.pipelineId}/stages`)
      .then((r) => r.json())
      .then((d) => setStages(Array.isArray(d) ? d : []));
  }, [filters.pipelineId]);

  // Selects e checkbox: disparam onApply imediatamente
  useEffect(() => {
    onApply(filters);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.pipelineId, filters.stageId, filters.dealCategory, filters.noDeal, filters.tagIds]);

  // Campos de texto/data: debounce de 400ms
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onApply(filters);
    }, 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.search, filters.createdAfter, filters.createdBefore]);

  const set = (key: keyof LeadFilters, value: unknown) =>
    setFilters((f) => ({ ...f, [key]: value }));

  const toggleTag = (id: string) =>
    setFilters((f) => ({
      ...f,
      tagIds: f.tagIds.includes(id) ? f.tagIds.filter((t) => t !== id) : [...f.tagIds, id],
    }));

  const reset = () => setFilters(EMPTY_FILTERS);

  const labelClass = "block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1";
  const selectClass = "w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none";
  const inputClass = "w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none";

  return (
    <div className="space-y-4">
      <div>
        <label className={labelClass}>Busca</label>
        <input
          value={filters.search}
          onChange={(e) => set("search", e.target.value)}
          placeholder="Nome, telefone ou empresa"
          className={inputClass}
        />
      </div>

      <div>
        <label className={labelClass}>Funil</label>
        <select value={filters.pipelineId} onChange={(e) => set("pipelineId", e.target.value)} className={selectClass}>
          <option value="">Todos os funis</option>
          {pipelines.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>

      {stages.length > 0 && (
        <div>
          <label className={labelClass}>Etapa do deal</label>
          <select value={filters.stageId} onChange={(e) => set("stageId", e.target.value)} className={selectClass}>
            <option value="">Todas as etapas</option>
            {stages.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
      )}

      <div>
        <label className={labelClass}>Categoria do deal</label>
        <select value={filters.dealCategory} onChange={(e) => set("dealCategory", e.target.value)} className={selectClass}>
          <option value="">Todas as categorias</option>
          {DEAL_CATEGORIES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="no-deal"
          checked={filters.noDeal}
          onChange={(e) => {
            set("noDeal", e.target.checked);
            if (e.target.checked) setFilters((f) => ({ ...f, pipelineId: "", stageId: "", dealCategory: "" }));
          }}
          className="w-4 h-4 rounded border-[#dedbd6] accent-[#111111]"
        />
        <label htmlFor="no-deal" className="text-[13px] text-[#111111]">Apenas leads sem deal</label>
      </div>

      {tags.length > 0 && (
        <div>
          <label className={labelClass}>Tags</label>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {tags.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => toggleTag(t.id)}
                className={`text-[12px] px-2 py-0.5 rounded-[4px] border transition-colors ${
                  filters.tagIds.includes(t.id)
                    ? "bg-[#111111] text-white border-[#111111]"
                    : "bg-white text-[#111111] border-[#dedbd6] hover:border-[#111111]"
                }`}
              >
                {t.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <label className={labelClass}>Criado entre</label>
        <div className="flex gap-2">
          <input type="date" value={filters.createdAfter} onChange={(e) => set("createdAfter", e.target.value)} className={inputClass} />
          <input type="date" value={filters.createdBefore} onChange={(e) => set("createdBefore", e.target.value)} className={inputClass} />
        </div>
      </div>

      <div className="pt-1">
        <button
          type="button"
          onClick={reset}
          className="w-full bg-transparent text-[#111111] border border-[#dedbd6] px-3 py-2 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors"
        >
          Limpar filtros
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar TypeScript**

```powershell
cd frontend
npx tsc --noEmit 2>&1 | Select-Object -First 20
```

Esperado: sem erros.

- [ ] **Step 3: Verificar comportamento esperado**

Abrir o modal de Novo Disparo → Step 3 (Leads). Confirmar:
- Ao digitar no campo "Busca", a tabela atualiza após ~400ms sem clicar em nenhum botão
- Ao mudar o select "Funil", a tabela atualiza imediatamente
- O botão "Aplicar filtros" não existe mais; só o botão "Limpar filtros"

- [ ] **Step 4: Commitar**

```powershell
git add frontend/src/components/campaigns/lead-filter-panel.tsx
git commit -m "feat(leads): filtro em tempo real com debounce, remover botão Aplicar"
```

---

## Task 4: Modal — ESC + Remover campos de Intervalo + Visibilidade Agente (mode=human)

**Files:**
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx`

Esta task agrupa 3 mudanças independentes no Step 1 do modal (todas focadas no arquivo, sem afetar outros steps).

### 4.1 — Remover estados e UI de Intervalo

- [ ] **Step 1: Remover estados `intervalMin` e `intervalMax`**

Localizar as linhas (aproximadamente 78-79):
```ts
const [intervalMin, setIntervalMin] = useState(3);
const [intervalMax, setIntervalMax] = useState(8);
```
Deletar ambas as linhas.

- [ ] **Step 2: Remover o bloco UI de Intervalo no Step 1**

Localizar e deletar o bloco abaixo (linhas ~631-656 do arquivo original):
```tsx
{/* Interval */}
<div className="grid grid-cols-2 gap-4">
  <div>
    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
      Intervalo mín. (s)
    </label>
    <input
      type="number"
      min={1}
      value={intervalMin}
      onChange={(e) => setIntervalMin(Number(e.target.value))}
      className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
    />
  </div>
  <div>
    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
      Intervalo máx. (s)
    </label>
    <input
      type="number"
      min={1}
      value={intervalMax}
      onChange={(e) => setIntervalMax(Number(e.target.value))}
      className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
    />
  </div>
</div>
```

- [ ] **Step 3: Remover linha de Intervalo na revisão (Step 6)**

Localizar e deletar o trecho no bloco de revisão:
```tsx
<p>
  <span className="text-[#7b7b78]">Intervalo:</span>{" "}
  <span className="text-[#111111]">
    {intervalMin}–{intervalMax}s
  </span>
</p>
```

- [ ] **Step 4: Remover `send_interval_min` e `send_interval_max` do `handleCreate`**

Localizar no body do fetch POST `/api/broadcasts` (linhas ~384-385):
```ts
send_interval_min: intervalMin,
send_interval_max: intervalMax,
```
Deletar essas duas linhas.

- [ ] **Step 5: Remover `setIntervalMin` e `setIntervalMax` do `resetForm`**

Localizar (linhas ~425-426):
```ts
setIntervalMin(3);
setIntervalMax(8);
```
Deletar essas duas linhas.

### 4.2 — ESC para fechar

- [ ] **Step 6: Adicionar ESC key handler**

No bloco de imports no topo do arquivo, `useEffect` já está importado. Adicionar o `useEffect` logo após os `useEffect` existentes de load inicial (após linha ~145 aproximadamente, antes de `handleApplyLeadFilters`):

```ts
// ESC fecha o modal
useEffect(() => {
  if (!open) return;
  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") { onClose(); resetForm(); }
  };
  window.addEventListener("keydown", handleKeyDown);
  return () => window.removeEventListener("keydown", handleKeyDown);
}, [open]); // eslint-disable-line react-hooks/exhaustive-deps
```

> Nota: `resetForm` e `onClose` são estáveis (definidas no mesmo componente). Usar o eslint-disable apenas nesta linha para evitar ciclo infinito de efeito.

### 4.3 — Ocultar Agente quando canal é `mode=human`

- [ ] **Step 7: Derivar `selectedChannel`**

Após as declarações de estado existentes (antes do primeiro `useEffect`), adicionar:

```ts
const selectedChannel = channels.find((c) => c.id === channelId);
```

- [ ] **Step 8: Resetar `agentMode` quando canal muda para `human`**

Adicionar `useEffect` logo após o efeito de load de templates:

```ts
useEffect(() => {
  if (selectedChannel?.mode === "human") {
    setAgentMode("none");
    setSpecificAgentId("");
  }
}, [channelId]); // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 9: Envolver seção Agente com renderização condicional**

No Step 1, localizar o bloco `{/* Agent */}` (linhas ~587-628). Envolvê-lo:

```tsx
{/* Agent — só exibir quando canal NÃO é mode=human */}
{selectedChannel?.mode !== "human" && (
  <div>
    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
      Agente
    </label>
    {/* ... restante do bloco Agent sem alteração ... */}
  </div>
)}
```

> **Atenção:** Quando `channelId` está vazio (`selectedChannel` é `undefined`), `selectedChannel?.mode !== "human"` retorna `true`, então o campo Agente fica visível por padrão. Isso é o comportamento correto.

- [ ] **Step 10: Verificar TypeScript**

```powershell
cd frontend
npx tsc --noEmit 2>&1 | Select-Object -First 20
```

Esperado: sem erros.

- [ ] **Step 11: Commitar**

```powershell
git add frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(modal): ESC para fechar, remover intervalos, ocultar Agente em canal human"
```

---

## Task 5: Modal — Shift+Click na tabela de leads (Step 3)

**Files:**
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx`

- [ ] **Step 1: Adicionar estado `lastCheckedIndex`**

Nas declarações de estado do Step 3 (logo após `const [selectedLeadIds, setSelectedLeadIds] = useState...`), adicionar:

```ts
const [lastCheckedIndex, setLastCheckedIndex] = useState<number | null>(null);
```

- [ ] **Step 2: Substituir função `toggleLead`**

Localizar a função `toggleLead` atual (linhas ~341-348):
```ts
const toggleLead = (id: string) => {
  setSelectedLeadIds((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
};
```

Substituir por:

```ts
const toggleLead = (id: string, idx: number, shiftKey: boolean) => {
  if (shiftKey && lastCheckedIndex !== null) {
    const from = Math.min(lastCheckedIndex, idx);
    const to = Math.max(lastCheckedIndex, idx);
    const rangeIds = leads.slice(from, to + 1).map((l) => l.id);
    const selecting = !selectedLeadIds.has(id);
    setSelectedLeadIds((prev) => {
      const next = new Set(prev);
      rangeIds.forEach((rid) => (selecting ? next.add(rid) : next.delete(rid)));
      return next;
    });
  } else {
    setSelectedLeadIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }
  setLastCheckedIndex(idx);
};
```

- [ ] **Step 3: Resetar `lastCheckedIndex` em `selectAllLeads` e `deselectAllLeads`**

Localizar `selectAllLeads` e `deselectAllLeads`:

```ts
const selectAllLeads = () => {
  setSelectedLeadIds(new Set(leads.map((l) => l.id)));
};

const deselectAllLeads = () => {
  setSelectedLeadIds(new Set());
};
```

Adicionar `setLastCheckedIndex(null)` em cada uma:

```ts
const selectAllLeads = () => {
  setSelectedLeadIds(new Set(leads.map((l) => l.id)));
  setLastCheckedIndex(null);
};

const deselectAllLeads = () => {
  setSelectedLeadIds(new Set());
  setLastCheckedIndex(null);
};
```

- [ ] **Step 4: Atualizar `<tr>` e `<input checkbox>` na tabela**

Localizar o `leads.map((lead, idx) => (...))` no Step 3. Atualizar o `<tr>` e o `<input>` de checkbox:

**Antes:**
```tsx
<tr
  key={lead.id}
  onClick={() => toggleLead(lead.id)}
  ...
>
  <td className="px-3 py-2">
    <input
      type="checkbox"
      checked={selectedLeadIds.has(lead.id)}
      onChange={() => toggleLead(lead.id)}
      onClick={(e) => e.stopPropagation()}
      className="accent-[#111111]"
    />
  </td>
```

**Depois:**
```tsx
<tr
  key={lead.id}
  onClick={(e) => toggleLead(lead.id, idx, e.shiftKey)}
  ...
>
  <td className="px-3 py-2">
    <input
      type="checkbox"
      checked={selectedLeadIds.has(lead.id)}
      onChange={() => {}}
      onClick={(e) => { e.stopPropagation(); toggleLead(lead.id, idx, e.shiftKey); }}
      className="accent-[#111111]"
    />
  </td>
```

> Nota: `onChange={() => {}}` é necessário para evitar o warning do React de "controlled input sem handler". O click real é tratado pelo `onClick`.

- [ ] **Step 5: Adicionar `resetForm` ao limpar `lastCheckedIndex`**

No `resetForm`, adicionar `setLastCheckedIndex(null)` após `setSelectedLeadIds(new Set())`.

- [ ] **Step 6: Verificar TypeScript**

```powershell
cd frontend
npx tsc --noEmit 2>&1 | Select-Object -First 20
```

Esperado: sem erros.

- [ ] **Step 7: Testar manualmente o Shift+Click**

1. Abrir modal → Step 3 com leads carregados
2. Clicar no checkbox do lead #1
3. Segurar Shift + clicar no lead #5
4. Verificar: leads 1 a 5 ficam todos selecionados
5. Shift + clicar no lead #3
6. Verificar: leads 3 a 5 ficam desselecionados (porque o lead #5 estava selecionado e o clique #3 está desselecionando)

- [ ] **Step 8: Commitar**

```powershell
git add frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(leads): Shift+Click para seleção em range na tabela de leads"
```

---

## Task 6: Modal — Fluxo pós-criação com AlertDialog

**Files:**
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx`

Depende de: **Task 2** (AlertDialog componente criado)

- [ ] **Step 1: Adicionar imports**

No topo do arquivo, adicionar os imports do AlertDialog e do `useRouter`:

```ts
import { useRouter } from "next/navigation";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
```

- [ ] **Step 2: Adicionar hook `useRouter` e novos estados**

Logo após `const [saving, setSaving] = useState(false);`, adicionar:

```ts
const [createdBroadcastId, setCreatedBroadcastId] = useState<string | null>(null);
const [showStartDialog, setShowStartDialog] = useState(false);
const [starting, setStarting] = useState(false);
const router = useRouter();
```

- [ ] **Step 3: Atualizar `handleCreate` para o novo fluxo**

Localizar no `handleCreate` o bloco de sucesso após os fetches de leads/CSV. Atualmente está assim (linhas ~409-414):

```ts
      onCreated();
      onClose();
      resetForm();
    } finally {
      setSaving(false);
    }
```

Substituir por:

```ts
      if (scheduleMode === "immediate") {
        setCreatedBroadcastId(broadcast.id);
        setShowStartDialog(true);
      } else {
        onCreated();
        onClose();
        resetForm();
      }
    } finally {
      setSaving(false);
    }
```

- [ ] **Step 4: Adicionar handler `handleStartNow`**

Após `handleCreate`, adicionar:

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

const handleCancelStart = () => {
  setShowStartDialog(false);
  onCreated();
  onClose();
  resetForm();
};
```

- [ ] **Step 5: Resetar novos estados no `resetForm`**

No `resetForm`, adicionar ao final:

```ts
setCreatedBroadcastId(null);
setShowStartDialog(false);
setStarting(false);
```

- [ ] **Step 6: Adicionar AlertDialog ao JSX**

No JSX, após o bloco `{showCreateTemplate && (...)}` e antes do `</>` final do fragmento, adicionar:

```tsx
{/* ── AlertDialog pós-criação ── */}
<AlertDialog open={showStartDialog}>
  <AlertDialogContent>
    <AlertDialogHeader>
      <AlertDialogTitle>Disparo criado com sucesso</AlertDialogTitle>
      <AlertDialogDescription>
        Deseja iniciar o disparo agora? Os leads selecionados serão contatados em sequência via Meta Cloud.
      </AlertDialogDescription>
    </AlertDialogHeader>
    <AlertDialogFooter>
      <AlertDialogCancel onClick={handleCancelStart}>
        Agora não
      </AlertDialogCancel>
      <AlertDialogAction onClick={handleStartNow} disabled={starting}>
        {starting ? "Iniciando..." : "Iniciar agora"}
      </AlertDialogAction>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

- [ ] **Step 7: Verificar TypeScript**

```powershell
cd frontend
npx tsc --noEmit 2>&1 | Select-Object -First 20
```

Esperado: sem erros.

- [ ] **Step 8: Testar o fluxo manualmente**

1. Abrir modal, preencher todos os steps com `scheduleMode = "immediate"`
2. Clicar "Criar Disparo"
3. Verificar: o wizard não fecha imediatamente — aparece o AlertDialog centralizado
4. Clicar "Agora não" → modal fecha, lista recarrega, sem navegação
5. Repetir e clicar "Iniciar agora" → modal fecha, navega para `/campanhas/disparos/[id]`
6. Repetir com `scheduleMode = "scheduled"` → após criar, o AlertDialog NÃO aparece, wizard fecha normalmente

- [ ] **Step 9: Commitar**

```powershell
git add frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(modal): fluxo pós-criação com AlertDialog e start imediato"
```

---

## Self-Review

### Cobertura do spec:

| Requisito do spec | Task |
|---|---|
| ESC fecha o modal | Task 4 (4.2) |
| Canal mode=human → ocultar Agente | Task 4 (4.3) |
| Remover campos Intervalo | Task 4 (4.1) |
| Filtro em tempo real, sem botão Aplicar | Task 3 |
| Shift+Click range selection | Task 5 |
| AlertDialog pós-criação (immediate only) | Task 6 |
| Confirmar → start + navegar /campanhas/disparos/[id] | Task 6 |
| Cancelar → fechar sem start | Task 6 |
| Disparo agendado → fechar sem dialog | Task 6, step 3 |
| `mode` no tipo Channel | Task 1 |
| AlertDialog componente | Task 2 |

Todos os 11 requisitos cobertos. ✓

### Consistência de tipos:

- `toggleLead(id: string, idx: number, shiftKey: boolean)` — definida na Task 5 Step 2, usada na Task 5 Step 4. ✓
- `AlertDialog` importado de `@/components/ui/alert-dialog` — criado na Task 2, usado na Task 6. ✓
- `selectedChannel` derivado de `channels.find(c => c.id === channelId)` — Task 4, reaproveita `channels` e `channelId` existentes. ✓
- `Channel.mode` — adicionado na Task 1, consumido na Task 4. ✓

### Sem placeholders:

Todos os steps têm código completo. ✓

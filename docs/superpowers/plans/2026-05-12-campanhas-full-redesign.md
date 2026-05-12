# Campanhas — Redesign Completo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **IMPORTANT:** Any agent working on frontend files MUST invoke the `frontend-design` skill before writing any component code.

**Goal:** Redesenhar completamente o painel `/campanhas` — wizard de disparo com 4 etapas, opção "Sem Agente", prévia de template com badge Marketing/Utility, filtro de leads por funil/etapa/categoria/tags/data, página de detalhe de disparo com lista de leads e retentar falhas, e aba Templates com criação via Modal.

**Architecture:** Abordagem B — modais para criação (wizard, template), sub-página `/campanhas/disparos/[id]` para detalhe. Abas client-side na página principal com query string `?tab=`. O `CreateTemplateModal` existente em `frontend/src/components/canais/create-template-modal.tsx` é reutilizado no wizard. APIs de pipelines/stages já existem. O `GET /api/leads` recebe novos query params para filtrar por funil, etapa, categoria de deal, sem deal, e data de criação.

**Tech Stack:** Next.js 15 App Router, React, TypeScript, Tailwind CSS, Supabase (server-side via `getServiceSupabase`), Meta Cloud API (já integrada via `/api/channels/[id]/templates`)

**Branch:** `feature/campanhas-full-redesign`

**Spec:** `docs/superpowers/specs/2026-05-12-campanhas-full-redesign-design.md`

---

## File Map

### Criar (novos)
- `frontend/src/app/api/templates/route.ts` — lista `message_templates` do Supabase (cache local de templates Meta)
- `frontend/src/components/campaigns/template-preview-card.tsx` — card de prévia do template com badge categoria e variáveis inline
- `frontend/src/components/campaigns/lead-filter-panel.tsx` — painel de filtros rico (funil, etapa, categoria deal, tags, sem deal, data criação)
- `frontend/src/app/(authenticated)/campanhas/disparos/[id]/page.tsx` — sub-página de detalhe do disparo
- `frontend/src/components/campaigns/broadcast-detail.tsx` — componente principal da página de detalhe (tabela de leads, métricas, retentar)
- `frontend/src/components/campaigns/templates-tab.tsx` — aba Templates (lista de templates com status de aprovação)

### Modificar (existentes)
- `frontend/src/app/api/leads/route.ts` — adicionar suporte a query params de filtro
- `frontend/src/components/campaigns/create-broadcast-modal.tsx` — reescrever como wizard 4 etapas
- `frontend/src/app/(authenticated)/campanhas/page.tsx` — adicionar aba Templates, atualizar header, conectar tudo

---

## Task 1: API — GET /api/templates (lista do cache local)

**Files:**
- Create: `frontend/src/app/api/templates/route.ts`

Este endpoint lista os templates do cache local (`message_templates` table) que o CRM já sincronizou com a Meta. É usado pela aba Templates. Os templates para o wizard de disparo continuam vindo de `/api/channels/[id]/templates` (direto da Meta).

- [ ] **Step 1: Criar o route handler**

```typescript
// frontend/src/app/api/templates/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");

  const supabase = await getServiceSupabase();
  let query = supabase
    .from("message_templates")
    .select("id, name, language, category, requested_category, status, created_at, channel_id")
    .order("created_at", { ascending: false });

  if (channelId) query = query.eq("channel_id", channelId);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
```

- [ ] **Step 2: Verificar que a tabela existe**

```bash
# No terminal, confirmar que a coluna status existe
# Checar frontend/src/lib/types.ts por MessageTemplate ou message_templates
grep -r "message_templates" frontend/src/lib/types.ts
```

Se o tipo `MessageTemplate` não existir em `types.ts`, adicionar:

```typescript
// Em frontend/src/lib/types.ts, adicionar:
export interface MessageTemplate {
  id: string;
  channel_id: string;
  name: string;
  language: string;
  category: string | null;
  requested_category: string | null;
  status: string; // "pending" | "pending_category_review" | "approved" | "cancelled"
  created_at: string;
}
```

- [ ] **Step 3: Testar o endpoint manualmente**

```bash
curl "http://localhost:3000/api/templates" | head -c 500
```

Esperado: array JSON (pode ser vazio se não há templates no cache).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/api/templates/route.ts frontend/src/lib/types.ts
git commit -m "feat(api): adicionar GET /api/templates para listar cache local de templates Meta"
```

---

## Task 2: API — Atualizar GET /api/leads com filtros avançados

**Files:**
- Modify: `frontend/src/app/api/leads/route.ts`

Adicionar suporte a query params: `pipeline_id`, `stage_id`, `deal_category`, `no_deal`, `created_after`, `created_before`.

- [ ] **Step 1: Ler o arquivo atual**

```bash
cat frontend/src/app/api/leads/route.ts
```

- [ ] **Step 2: Substituir o GET handler**

Substituir a função `GET` existente por:

```typescript
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const pipelineId = searchParams.get("pipeline_id");
  const stageId = searchParams.get("stage_id");
  const dealCategory = searchParams.get("deal_category");
  const noDeal = searchParams.get("no_deal") === "true";
  const createdAfter = searchParams.get("created_after");
  const createdBefore = searchParams.get("created_before");

  const supabase = await getServiceSupabase();

  // Filtro por deal (pipeline, etapa, categoria)
  if (pipelineId || stageId || dealCategory || noDeal) {
    if (noDeal) {
      // Leads sem nenhum deal associado
      const { data: leadsWithDeals } = await supabase
        .from("deals")
        .select("lead_id");
      const excludeIds = (leadsWithDeals ?? []).map((d: { lead_id: string }) => d.lead_id);

      let q = supabase
        .from("leads")
        .select("*, lead_tags(tag_id, tags(*))")
        .order("last_msg_at", { ascending: false, nullsFirst: false });

      if (excludeIds.length > 0) q = q.not("id", "in", `(${excludeIds.join(",")})`);
      if (createdAfter) q = q.gte("created_at", createdAfter);
      if (createdBefore) q = q.lte("created_at", createdBefore);

      const { data, error } = await q;
      if (error) return NextResponse.json({ error: error.message }, { status: 500 });
      return NextResponse.json(data ?? []);
    }

    // Filtrar por deals com pipeline/stage/categoria
    let dealQuery = supabase.from("deals").select("lead_id");
    if (pipelineId) dealQuery = dealQuery.eq("pipeline_id", pipelineId);
    if (stageId) dealQuery = dealQuery.eq("stage_id", stageId);
    if (dealCategory) dealQuery = dealQuery.eq("category", dealCategory);

    const { data: matchingDeals, error: dealError } = await dealQuery;
    if (dealError) return NextResponse.json({ error: dealError.message }, { status: 500 });

    const leadIds = [...new Set((matchingDeals ?? []).map((d: { lead_id: string }) => d.lead_id))];
    if (leadIds.length === 0) return NextResponse.json([]);

    let q = supabase
      .from("leads")
      .select("*, lead_tags(tag_id, tags(*))")
      .in("id", leadIds)
      .order("last_msg_at", { ascending: false, nullsFirst: false });

    if (createdAfter) q = q.gte("created_at", createdAfter);
    if (createdBefore) q = q.lte("created_at", createdBefore);

    const { data, error } = await q;
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    return NextResponse.json(data ?? []);
  }

  // Sem filtro de deal — busca normal
  let q = supabase
    .from("leads")
    .select("*, lead_tags(tag_id, tags(*))")
    .order("last_msg_at", { ascending: false, nullsFirst: false });

  if (createdAfter) q = q.gte("created_at", createdAfter);
  if (createdBefore) q = q.lte("created_at", createdBefore);

  const { data, error } = await q;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
```

Manter a função `POST` existente sem alteração.

- [ ] **Step 3: Testar filtros**

```bash
# Sem filtro — comportamento original
curl "http://localhost:3000/api/leads" | python -m json.tool | head -30

# Filtro por pipeline
curl "http://localhost:3000/api/leads?pipeline_id=<UUID_REAL>" | python -m json.tool | head -10

# Leads sem deal
curl "http://localhost:3000/api/leads?no_deal=true" | python -m json.tool | head -10
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/api/leads/route.ts
git commit -m "feat(api): adicionar filtros por pipeline, etapa, categoria e data em GET /api/leads"
```

---

## Task 3: Componente TemplatePreviewCard

**Files:**
- Create: `frontend/src/components/campaigns/template-preview-card.tsx`

**REQUIRED:** Invocar skill `frontend-design` antes de escrever qualquer código de componente.

Card que renderiza a prévia de um template Meta: badge de categoria, texto completo com variáveis destacadas, campos inline para variáveis manuais.

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Criar o componente**

```typescript
// frontend/src/components/campaigns/template-preview-card.tsx
"use client";

// Variáveis que o backend resolve automaticamente do lead
const AUTO_VARS = new Set(["first_name", "primeiro_nome", "nome", "name", "phone"]);

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: string[];
  buttons?: { type: string; text: string }[];
}

interface TemplatePreviewCardProps {
  template: MetaTemplate;
  varValues: Record<string, string>;
  onVarChange: (paramName: string, value: string) => void;
}

export function TemplatePreviewCard({ template, varValues, onVarChange }: TemplatePreviewCardProps) {
  const cat = CATEGORY_CONFIG[template.category?.toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const manualParams = template.params.filter((p) => !AUTO_VARS.has(p.toLowerCase()));
  const autoParams = template.params.filter((p) => AUTO_VARS.has(p.toLowerCase()));

  // Renderiza o body substituindo {{N}} pelo valor ou placeholder
  const renderBody = () => {
    let idx = 0;
    const parts: React.ReactNode[] = [];
    const raw = template.body ?? "";
    const segments = raw.split(/(\{\{\d+\}\})/g);

    for (const seg of segments) {
      if (/^\{\{\d+\}\}$/.test(seg)) {
        const param = template.params[idx] ?? `var${idx + 1}`;
        const isAuto = AUTO_VARS.has(param.toLowerCase());
        const val = varValues[param];
        if (isAuto) {
          parts.push(
            <span key={idx} className="inline-flex items-center gap-0.5 px-1 rounded text-[12px] font-medium text-[#1a7a3a] bg-[#e6faf0]">
              ⚡ {param}
            </span>
          );
        } else {
          parts.push(
            <span key={idx} className={`inline-flex items-center px-1 rounded text-[12px] font-medium ${val ? "text-[#7a5a00] bg-[#fff8e0]" : "text-[#c41c1c] bg-[#fef0f0]"}`}>
              {val || `[${param}]`}
            </span>
          );
        }
        idx++;
      } else {
        parts.push(seg);
      }
    }
    return parts;
  };

  return (
    <div className="border border-[#dedbd6] rounded-[8px] overflow-hidden">
      {/* Header do card */}
      <div className="flex items-center gap-2 px-4 py-2 bg-[#faf9f6] border-b border-[#dedbd6]">
        <span
          className="text-[10px] font-semibold uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]"
          style={{ color: cat.color, backgroundColor: cat.bg }}
        >
          {cat.label}
        </span>
        <span className="text-[12px] text-[#7b7b78] truncate">{template.name}</span>
        <span className="text-[10px] text-[#b0aca6] ml-auto">{template.language}</span>
      </div>

      {/* Prévia do body */}
      <div className="px-4 py-3 bg-white">
        <p className="text-[14px] text-[#111111] leading-relaxed whitespace-pre-wrap">
          {renderBody()}
        </p>
      </div>

      {/* Botões do template */}
      {template.buttons && template.buttons.length > 0 && (
        <div className="px-4 pb-3 flex flex-wrap gap-1.5">
          {template.buttons.map((btn, i) => (
            <span
              key={i}
              className="text-[12px] text-[#7b7b78] border border-[#dedbd6] px-2 py-0.5 rounded-[4px] bg-[#faf9f6]"
            >
              {btn.text}
            </span>
          ))}
        </div>
      )}

      {/* Variáveis automáticas */}
      {autoParams.length > 0 && (
        <div className="px-4 pb-2 flex flex-wrap gap-1.5">
          {autoParams.map((p) => (
            <span key={p} className="text-[11px] text-[#1a7a3a] bg-[#e6faf0] px-2 py-0.5 rounded-[4px] flex items-center gap-1">
              ⚡ <strong>{p}</strong> preenchido automaticamente do lead
            </span>
          ))}
        </div>
      )}

      {/* Variáveis manuais */}
      {manualParams.length > 0 && (
        <div className="px-4 pb-3 pt-1 border-t border-[#f0ede8] space-y-2">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Preencher manualmente</p>
          {manualParams.map((p) => (
            <div key={p} className="flex items-center gap-2">
              <label className="text-[12px] text-[#111111] w-28 flex-shrink-0">{p}</label>
              <input
                value={varValues[p] ?? ""}
                onChange={(e) => onVarChange(p, e.target.value)}
                placeholder={`Valor de ${p}`}
                className="flex-1 bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1 text-[13px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/campaigns/template-preview-card.tsx
git commit -m "feat(campaigns): criar TemplatePreviewCard com badge categoria e variáveis inline"
```

---

## Task 4: Componente LeadFilterPanel

**Files:**
- Create: `frontend/src/components/campaigns/lead-filter-panel.tsx`

**REQUIRED:** Invocar skill `frontend-design` antes de escrever qualquer código de componente.

Painel de filtros que carrega pipelines, etapas, e tags dinamicamente. Emite um objeto de filtro que o wizard usa para chamar `/api/leads`.

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Criar o componente**

```typescript
// frontend/src/components/campaigns/lead-filter-panel.tsx
"use client";

import { useState, useEffect } from "react";
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
      {/* Busca */}
      <div>
        <label className={labelClass}>Busca</label>
        <input
          value={filters.search}
          onChange={(e) => set("search", e.target.value)}
          placeholder="Nome, telefone ou empresa"
          className={inputClass}
        />
      </div>

      {/* Funil */}
      <div>
        <label className={labelClass}>Funil</label>
        <select value={filters.pipelineId} onChange={(e) => set("pipelineId", e.target.value)} className={selectClass}>
          <option value="">Todos os funis</option>
          {pipelines.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>

      {/* Etapa do deal */}
      {stages.length > 0 && (
        <div>
          <label className={labelClass}>Etapa do deal</label>
          <select value={filters.stageId} onChange={(e) => set("stageId", e.target.value)} className={selectClass}>
            <option value="">Todas as etapas</option>
            {stages.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
      )}

      {/* Categoria do deal */}
      <div>
        <label className={labelClass}>Categoria do deal</label>
        <select value={filters.dealCategory} onChange={(e) => set("dealCategory", e.target.value)} className={selectClass}>
          <option value="">Todas as categorias</option>
          {DEAL_CATEGORIES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
      </div>

      {/* Sem deal */}
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

      {/* Tags */}
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

      {/* Data de criação */}
      <div>
        <label className={labelClass}>Criado entre</label>
        <div className="flex gap-2">
          <input type="date" value={filters.createdAfter} onChange={(e) => set("createdAfter", e.target.value)} className={inputClass} />
          <input type="date" value={filters.createdBefore} onChange={(e) => set("createdBefore", e.target.value)} className={inputClass} />
        </div>
      </div>

      {/* Ações */}
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          onClick={reset}
          className="flex-1 bg-transparent text-[#111111] border border-[#dedbd6] px-3 py-2 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors"
        >
          Limpar
        </button>
        <button
          type="button"
          onClick={() => onApply(filters)}
          disabled={loading}
          className="flex-1 bg-[#111111] text-white px-3 py-2 rounded-[4px] text-[13px] disabled:opacity-50 transition-transform hover:scale-105 active:scale-[0.95]"
        >
          {loading ? "Buscando..." : "Aplicar filtros"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verificar que DEAL_CATEGORIES existe em constants.ts**

```bash
grep "DEAL_CATEGORIES" frontend/src/lib/constants.ts
```

Se não existir, adicionar em `frontend/src/lib/constants.ts`:

```typescript
export const DEAL_CATEGORIES = [
  { key: "atacado",       label: "Atacado" },
  { key: "private_label", label: "Private Label" },
  { key: "exportacao",    label: "Exportação" },
  { key: "consumo",       label: "Consumo" },
];
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/campaigns/lead-filter-panel.tsx frontend/src/lib/constants.ts
git commit -m "feat(campaigns): criar LeadFilterPanel com filtros por funil, etapa, categoria, tags e data"
```

---

## Task 5: Reescrever CreateBroadcastModal (wizard 4 etapas)

**Files:**
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx`

**REQUIRED:** Invocar skill `frontend-design` antes de escrever qualquer código de componente.

Reescrever completamente o modal como wizard linear de 4 etapas. Usa `TemplatePreviewCard`, `LeadFilterPanel`, e `CreateTemplateModal` (de canais).

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Reescrever o arquivo**

```typescript
// frontend/src/components/campaigns/create-broadcast-modal.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import type { Channel, AgentProfile } from "@/lib/types";
import { TemplatePreviewCard } from "./template-preview-card";
import { LeadFilterPanel, type LeadFilters } from "./lead-filter-panel";
import { CreateTemplateModal } from "@/components/canais/create-template-modal";

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: string[];
  buttons?: { type: string; text: string }[];
}

interface Lead {
  id: string;
  name: string | null;
  phone: string;
  company: string | null;
  nome_fantasia: string | null;
  lead_tags?: { tag_id: string; tags: { name: string; color: string } | null }[];
}

const AUTO_VARS = new Set(["first_name", "primeiro_nome", "nome", "name", "phone"]);

const STEPS = ["Configuração", "Template", "Leads", "Revisão"] as const;

interface CreateBroadcastModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  /** Pré-preencher com dados de um disparo anterior (para retentar falhas) */
  prefill?: {
    channelId: string;
    template: MetaTemplate;
    templateVarValues: Record<string, string>;
    leadIds: string[];
  };
}

export function CreateBroadcastModal({ open, onClose, onCreated, prefill }: CreateBroadcastModalProps) {
  const [step, setStep] = useState(1);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [agentProfiles, setAgentProfiles] = useState<AgentProfile[]>([]);
  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showCreateTemplate, setShowCreateTemplate] = useState(false);

  // Step 1
  const [name, setName] = useState("");
  const [channelId, setChannelId] = useState("");
  const [agentMode, setAgentMode] = useState<"none" | "channel" | "specific">("none");
  const [agentProfileId, setAgentProfileId] = useState("");
  const [intervalMin, setIntervalMin] = useState(3);
  const [intervalMax, setIntervalMax] = useState(8);

  // Step 2
  const [selectedTemplate, setSelectedTemplate] = useState<MetaTemplate | null>(null);
  const [templateVarValues, setTemplateVarValues] = useState<Record<string, string>>({});

  // Step 3
  const [leadTab, setLeadTab] = useState<"crm" | "csv">("crm");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [selectedLeadIds, setSelectedLeadIds] = useState<Set<string>>(new Set());
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const reset = useCallback(() => {
    setStep(1); setName(""); setChannelId(""); setAgentMode("none");
    setAgentProfileId(""); setIntervalMin(3); setIntervalMax(8);
    setSelectedTemplate(null); setTemplateVarValues({});
    setLeads([]); setSelectedLeadIds(new Set()); setCsvFile(null);
    setLeadTab("crm");
  }, []);

  useEffect(() => {
    if (!open) return;
    fetch("/api/channels").then((r) => r.json()).then((d) => {
      const meta = (Array.isArray(d) ? d : d.data ?? []).filter(
        (c: Channel) => c.provider === "meta_cloud" && c.is_active
      );
      setChannels(meta);
      if (meta.length === 1 && !channelId) setChannelId(meta[0].id);
    });
    fetch("/api/agent-profiles").then((r) => r.json()).then((d) =>
      setAgentProfiles(Array.isArray(d) ? d : d.data ?? [])
    );
    // Aplicar prefill se houver
    if (prefill) {
      setChannelId(prefill.channelId);
      setSelectedTemplate(prefill.template);
      setTemplateVarValues(prefill.templateVarValues);
      setSelectedLeadIds(new Set(prefill.leadIds));
      setStep(3); // Pula direto para leads
    }
  }, [open]);

  useEffect(() => {
    if (!channelId) { setTemplates([]); setSelectedTemplate(null); return; }
    setLoadingTemplates(true);
    fetch(`/api/channels/${channelId}/templates`)
      .then((r) => r.json())
      .then((d) => setTemplates(Array.isArray(d) ? d : []))
      .finally(() => setLoadingTemplates(false));
  }, [channelId]);

  const applyLeadFilters = useCallback(async (filters: LeadFilters) => {
    setLoadingLeads(true);
    try {
      const params = new URLSearchParams();
      if (filters.pipelineId) params.set("pipeline_id", filters.pipelineId);
      if (filters.stageId) params.set("stage_id", filters.stageId);
      if (filters.dealCategory) params.set("deal_category", filters.dealCategory);
      if (filters.noDeal) params.set("no_deal", "true");
      if (filters.createdAfter) params.set("created_after", filters.createdAfter);
      if (filters.createdBefore) params.set("created_before", filters.createdBefore);

      const data = await fetch(`/api/leads?${params}`).then((r) => r.json());
      let result = Array.isArray(data) ? data : [];

      if (filters.search) {
        const q = filters.search.toLowerCase();
        result = result.filter((l: Lead) =>
          l.name?.toLowerCase().includes(q) ||
          l.phone.includes(q) ||
          l.company?.toLowerCase().includes(q) ||
          l.nome_fantasia?.toLowerCase().includes(q)
        );
      }

      if (filters.tagIds.length > 0) {
        result = result.filter((l: Lead) =>
          l.lead_tags?.some((lt) => filters.tagIds.includes(lt.tag_id))
        );
      }

      setLeads(result);
    } finally {
      setLoadingLeads(false);
    }
  }, []);

  const handleSelectTemplate = (nameAndLang: string) => {
    if (!nameAndLang) { setSelectedTemplate(null); setTemplateVarValues({}); return; }
    const [tname, lang] = nameAndLang.split("|");
    const tpl = templates.find((t) => t.name === tname && t.language === lang) ?? null;
    setSelectedTemplate(tpl);
    if (tpl) {
      const initial: Record<string, string> = {};
      tpl.params.forEach((p) => {
        if (!AUTO_VARS.has(p.toLowerCase())) initial[p] = "";
      });
      setTemplateVarValues(initial);
    } else {
      setTemplateVarValues({});
    }
  };

  const toggleLead = (id: string) =>
    setSelectedLeadIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelectedLeadIds((prev) =>
      prev.size === leads.length ? new Set() : new Set(leads.map((l) => l.id))
    );

  const handleCreate = async () => {
    if (!name.trim() || !channelId || !selectedTemplate) return;
    setSaving(true);
    try {
      const broadcastRes = await fetch("/api/broadcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          channel_id: channelId,
          template_name: selectedTemplate.name,
          template_language_code: selectedTemplate.language,
          template_variables: templateVarValues,
          agent_profile_id: agentMode === "specific" ? agentProfileId || null : agentMode === "channel" ? undefined : null,
          send_interval_min: intervalMin,
          send_interval_max: intervalMax,
        }),
      });
      if (!broadcastRes.ok) throw new Error(await broadcastRes.text());
      const broadcast = await broadcastRes.json();

      if (leadTab === "crm" && selectedLeadIds.size > 0) {
        await fetch(`/api/broadcasts/${broadcast.id}/leads`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lead_ids: [...selectedLeadIds] }),
        });
      } else if (leadTab === "csv" && csvFile) {
        const fd = new FormData();
        fd.append("file", csvFile);
        await fetch(`${process.env.NEXT_PUBLIC_FASTAPI_URL}/api/broadcasts/${broadcast.id}/import`, {
          method: "POST",
          body: fd,
        });
      }

      onCreated();
      onClose();
      reset();
    } catch (e) {
      alert(`Erro ao criar disparo: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  const canNextStep1 = name.trim() && channelId && (agentMode !== "specific" || agentProfileId);
  const canNextStep2 = !!selectedTemplate;
  const canNextStep3 = leadTab === "crm" ? selectedLeadIds.size > 0 : !!csvFile;

  const inputClass = "w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none";
  const labelClass = "block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1";

  return (
    <>
      <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4">
        <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-2xl flex flex-col max-h-[90vh]">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-[#dedbd6] flex-shrink-0">
            <h2 className="text-[16px] font-medium text-[#111111]">Novo Disparo</h2>
            <button onClick={() => { onClose(); reset(); }} className="text-[#7b7b78] hover:text-[#111111] text-xl leading-none">&times;</button>
          </div>

          {/* Progress bar */}
          <div className="px-6 py-3 border-b border-[#f0ede8] flex-shrink-0">
            <div className="flex items-center gap-0">
              {STEPS.map((label, i) => {
                const n = i + 1;
                const active = step === n;
                const done = step > n;
                return (
                  <div key={n} className="flex items-center flex-1">
                    <div className="flex items-center gap-1.5">
                      <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-semibold flex-shrink-0 ${
                        done ? "bg-[#111111] text-white" : active ? "bg-[#111111] text-white" : "bg-[#f0ede8] text-[#7b7b78]"
                      }`}>
                        {done ? "✓" : n}
                      </div>
                      <span className={`text-[12px] ${active ? "text-[#111111] font-medium" : "text-[#7b7b78]"}`}>{label}</span>
                    </div>
                    {i < STEPS.length - 1 && <div className="flex-1 h-px bg-[#dedbd6] mx-2" />}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {/* STEP 1 */}
            {step === 1 && (
              <div className="space-y-4">
                <div>
                  <label className={labelClass}>Nome do disparo *</label>
                  <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex: Reativação Atacado Maio" className={inputClass} autoFocus />
                </div>
                <div>
                  <label className={labelClass}>Canal *</label>
                  <select value={channelId} onChange={(e) => setChannelId(e.target.value)} className={inputClass}>
                    <option value="">Selecionar canal</option>
                    {channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className={labelClass}>Agente de AI</label>
                  <div className="space-y-2 mt-1">
                    {(["none", "channel", "specific"] as const).map((mode) => (
                      <label key={mode} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="radio"
                          name="agentMode"
                          value={mode}
                          checked={agentMode === mode}
                          onChange={() => setAgentMode(mode)}
                          className="accent-[#111111]"
                        />
                        <span className="text-[14px] text-[#111111]">
                          {mode === "none" && "Sem Agente"}
                          {mode === "channel" && "Agente padrão do canal"}
                          {mode === "specific" && "Escolher agente específico"}
                        </span>
                      </label>
                    ))}
                  </div>
                  {agentMode === "specific" && (
                    <select value={agentProfileId} onChange={(e) => setAgentProfileId(e.target.value)} className={`${inputClass} mt-2`}>
                      <option value="">Selecionar agente</option>
                      {agentProfiles.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </select>
                  )}
                </div>
                <div>
                  <label className={labelClass}>Intervalo entre envios (segundos)</label>
                  <div className="flex gap-2 items-center">
                    <input type="number" value={intervalMin} min={1} onChange={(e) => setIntervalMin(Number(e.target.value))} className={`${inputClass} w-24`} />
                    <span className="text-[13px] text-[#7b7b78]">até</span>
                    <input type="number" value={intervalMax} min={intervalMin} onChange={(e) => setIntervalMax(Number(e.target.value))} className={`${inputClass} w-24`} />
                  </div>
                  <p className="text-[11px] text-[#7b7b78] mt-1">Intervalo aleatório entre mensagens para evitar bloqueio do WhatsApp</p>
                </div>
              </div>
            )}

            {/* STEP 2 */}
            {step === 2 && (
              <div className="space-y-4">
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className={labelClass}>Template *</label>
                    <select
                      value={selectedTemplate ? `${selectedTemplate.name}|${selectedTemplate.language}` : ""}
                      onChange={(e) => handleSelectTemplate(e.target.value)}
                      className={inputClass}
                      disabled={loadingTemplates}
                    >
                      <option value="">{loadingTemplates ? "Carregando templates..." : "Selecionar template"}</option>
                      {templates.map((t) => (
                        <option key={`${t.name}|${t.language}`} value={`${t.name}|${t.language}`}>{t.name} ({t.language})</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex-shrink-0 flex items-end">
                    <button
                      type="button"
                      onClick={() => setShowCreateTemplate(true)}
                      className="bg-transparent text-[#111111] border border-[#111111] px-3 py-2 rounded-[4px] text-[13px] whitespace-nowrap transition-transform hover:scale-105 active:scale-[0.95]"
                    >
                      + Novo template
                    </button>
                  </div>
                </div>
                {selectedTemplate && (
                  <TemplatePreviewCard
                    template={selectedTemplate}
                    varValues={templateVarValues}
                    onVarChange={(p, v) => setTemplateVarValues((prev) => ({ ...prev, [p]: v }))}
                  />
                )}
              </div>
            )}

            {/* STEP 3 */}
            {step === 3 && (
              <div className="space-y-4">
                <div className="flex gap-3 border-b border-[#dedbd6]">
                  {(["crm", "csv"] as const).map((tab) => (
                    <button
                      key={tab}
                      type="button"
                      onClick={() => setLeadTab(tab)}
                      className={`px-1 pb-2 text-[14px] border-b-2 transition-colors ${leadTab === tab ? "border-[#111111] text-[#111111]" : "border-transparent text-[#7b7b78]"}`}
                    >
                      {tab === "crm" ? "Do CRM" : "Importar CSV"}
                    </button>
                  ))}
                </div>

                {leadTab === "crm" && (
                  <div className="grid grid-cols-[220px,1fr] gap-4">
                    <div className="border-r border-[#f0ede8] pr-4">
                      <LeadFilterPanel onApply={applyLeadFilters} loading={loadingLeads} />
                    </div>
                    <div>
                      {leads.length > 0 && (
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-[13px] text-[#7b7b78]">{leads.length} leads encontrados</span>
                          <button type="button" onClick={toggleAll} className="text-[12px] text-[#111111] underline">
                            {selectedLeadIds.size === leads.length ? "Desmarcar todos" : `Selecionar todos (${leads.length})`}
                          </button>
                        </div>
                      )}
                      <div className="space-y-1 max-h-64 overflow-y-auto">
                        {leads.length === 0 && !loadingLeads && (
                          <p className="text-[13px] text-[#7b7b78] py-4 text-center">Aplique filtros para ver leads</p>
                        )}
                        {loadingLeads && <p className="text-[13px] text-[#7b7b78] py-4 text-center">Buscando leads...</p>}
                        {leads.map((l) => (
                          <label key={l.id} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-[#faf9f6] cursor-pointer">
                            <input
                              type="checkbox"
                              checked={selectedLeadIds.has(l.id)}
                              onChange={() => toggleLead(l.id)}
                              className="accent-[#111111]"
                            />
                            <div className="flex-1 min-w-0">
                              <p className="text-[13px] text-[#111111] truncate">{l.name ?? l.phone}</p>
                              {l.company && <p className="text-[11px] text-[#7b7b78] truncate">{l.company}</p>}
                            </div>
                            <span className="text-[11px] text-[#b0aca6] flex-shrink-0">{l.phone}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {leadTab === "csv" && (
                  <div>
                    <label className={labelClass}>Arquivo CSV</label>
                    <input
                      type="file"
                      accept=".csv"
                      onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                      className="w-full text-[13px] text-[#111111]"
                    />
                    <p className="text-[11px] text-[#7b7b78] mt-1">Coluna obrigatória: <code>phone</code>. Opcional: <code>name</code></p>
                  </div>
                )}

                <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2">
                  <span className="text-[13px] font-medium text-[#111111]">
                    {leadTab === "crm" ? `${selectedLeadIds.size} leads selecionados` : csvFile ? `Arquivo: ${csvFile.name}` : "Nenhum arquivo"}
                  </span>
                </div>
              </div>
            )}

            {/* STEP 4 */}
            {step === 4 && (
              <div className="space-y-4">
                <h3 className="text-[14px] font-medium text-[#111111]">Resumo do disparo</h3>
                <div className="space-y-2">
                  {[
                    ["Nome", name],
                    ["Canal", channels.find((c) => c.id === channelId)?.name ?? channelId],
                    ["Agente", agentMode === "none" ? "Sem Agente" : agentMode === "channel" ? "Agente do canal" : agentProfiles.find((a) => a.id === agentProfileId)?.name ?? "—"],
                    ["Template", selectedTemplate?.name ?? "—"],
                    ["Categoria", selectedTemplate?.category ?? "—"],
                    ["Intervalo", `${intervalMin}s – ${intervalMax}s`],
                    ["Leads", leadTab === "crm" ? `${selectedLeadIds.size} leads selecionados` : csvFile?.name ?? "CSV"],
                  ].map(([k, v]) => (
                    <div key={k} className="flex gap-3 text-[13px]">
                      <span className="text-[#7b7b78] w-24 flex-shrink-0">{k}</span>
                      <span className="text-[#111111] font-medium">{v}</span>
                    </div>
                  ))}
                </div>
                {selectedTemplate && Object.keys(templateVarValues).length > 0 && (
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Variáveis</p>
                    {Object.entries(templateVarValues).map(([k, v]) => (
                      <div key={k} className="flex gap-3 text-[13px] mb-1">
                        <span className="text-[#7b7b78] w-24 flex-shrink-0">{k}</span>
                        <span className="text-[#111111]">{v || <em className="text-[#c41c1c]">vazio</em>}</span>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-[12px] text-[#7b7b78] bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2">
                  O disparo será criado como <strong>Rascunho</strong>. Você poderá revisá-lo e clicar em Iniciar quando estiver pronto.
                </p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-[#dedbd6] flex items-center justify-between flex-shrink-0">
            <button
              type="button"
              onClick={() => step > 1 ? setStep(step - 1) : (onClose(), reset())}
              className="bg-transparent text-[#111111] border border-[#dedbd6] px-4 py-2 rounded-[4px] text-[14px] hover:border-[#111111] transition-colors"
            >
              {step === 1 ? "Cancelar" : "← Voltar"}
            </button>
            {step < 4 ? (
              <button
                type="button"
                onClick={() => setStep(step + 1)}
                disabled={
                  (step === 1 && !canNextStep1) ||
                  (step === 2 && !canNextStep2) ||
                  (step === 3 && !canNextStep3)
                }
                className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] disabled:opacity-40 transition-transform hover:scale-105 active:scale-[0.95]"
              >
                Próximo →
              </button>
            ) : (
              <button
                type="button"
                onClick={handleCreate}
                disabled={saving}
                className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] disabled:opacity-40 transition-transform hover:scale-105 active:scale-[0.95]"
              >
                {saving ? "Criando..." : "Criar Disparo"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Modal de criação de template (por cima do wizard) */}
      <CreateTemplateModal
        open={showCreateTemplate}
        channelId={channelId || undefined}
        onClose={() => setShowCreateTemplate(false)}
        onCreated={() => {
          setShowCreateTemplate(false);
          // Recarregar templates do canal para incluir o novo (se aprovado)
          if (channelId) {
            fetch(`/api/channels/${channelId}/templates`)
              .then((r) => r.json())
              .then((d) => setTemplates(Array.isArray(d) ? d : []));
          }
        }}
      />
    </>
  );
}
```

- [ ] **Step 3: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "create-broadcast-modal" | head -20
```

Corrigir quaisquer erros de tipo antes de continuar.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(campaigns): reescrever CreateBroadcastModal como wizard 4 etapas com Sem Agente e prévia de template"
```

---

## Task 6: Componente BroadcastDetail + sub-página

**Files:**
- Create: `frontend/src/components/campaigns/broadcast-detail.tsx`
- Create: `frontend/src/app/(authenticated)/campanhas/disparos/[id]/page.tsx`

**REQUIRED:** Invocar skill `frontend-design` antes de escrever qualquer código de componente.

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Criar o componente BroadcastDetail**

```typescript
// frontend/src/components/campaigns/broadcast-detail.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import type { Broadcast, BroadcastLead } from "@/lib/types";

type LeadStatusFilter = "all" | "pending" | "sent" | "delivered" | "failed";

const STATUS_CONFIG: Record<string, { label: string; style: string }> = {
  pending:   { label: "Pendente",  style: "text-[#7b7b78] bg-[#f0ede8]" },
  sent:      { label: "Enviado",   style: "text-[#1d5fa8] bg-[#e8f1fc]" },
  delivered: { label: "Entregue",  style: "text-[#1a7a3a] bg-[#e6faf0]" },
  failed:    { label: "Falhou",    style: "text-[#c41c1c] bg-[#fef0f0]" },
};

const BROADCAST_STATUS_CONFIG: Record<string, { label: string; style: string }> = {
  draft:     { label: "Rascunho",  style: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]" },
  running:   { label: "Rodando",   style: "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20" },
  paused:    { label: "Pausado",   style: "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20" },
  completed: { label: "Concluído", style: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20" },
  scheduled: { label: "Agendado",  style: "bg-[#65b5ff]/10 text-[#65b5ff] border-[#65b5ff]/20" },
  failed:    { label: "Falhou",    style: "bg-[#c41c1c]/10 text-[#c41c1c] border-[#c41c1c]/20" },
};

interface BroadcastDetailProps {
  broadcastId: string;
}

export function BroadcastDetail({ broadcastId }: BroadcastDetailProps) {
  const router = useRouter();
  const [broadcast, setBroadcast] = useState<Broadcast | null>(null);
  const [broadcastLeads, setBroadcastLeads] = useState<BroadcastLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<LeadStatusFilter>("all");

  const fetchBroadcast = useCallback(async () => {
    const [bRes, lRes] = await Promise.all([
      fetch(`/api/broadcasts/${broadcastId}`),
      fetch(`/api/broadcasts/${broadcastId}/leads`),
    ]);
    if (bRes.ok) setBroadcast(await bRes.json());
    if (lRes.ok) setBroadcastLeads(await lRes.json());
    setLoading(false);
  }, [broadcastId]);

  useEffect(() => { fetchBroadcast(); }, [fetchBroadcast]);

  const handleAction = async (action: "start" | "pause" | "resume") => {
    setActionLoading(true);
    try {
      if (action === "start" || action === "resume") {
        await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
      } else {
        await fetch(`/api/broadcasts/${broadcastId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "paused" }),
        });
      }
      await fetchBroadcast();
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Excluir o disparo "${broadcast?.name}"? Esta ação não pode ser desfeita.`)) return;
    await fetch(`/api/broadcasts/${broadcastId}`, { method: "DELETE" });
    router.push("/campanhas?tab=disparos");
  };

  const filteredLeads = statusFilter === "all"
    ? broadcastLeads
    : broadcastLeads.filter((l) => l.status === statusFilter);

  const counts = {
    all: broadcastLeads.length,
    pending: broadcastLeads.filter((l) => l.status === "pending").length,
    sent: broadcastLeads.filter((l) => l.status === "sent").length,
    delivered: broadcastLeads.filter((l) => l.status === "delivered").length,
    failed: broadcastLeads.filter((l) => l.status === "failed").length,
  };

  const failedLeads = broadcastLeads.filter((l) => l.status === "failed");

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-8 w-64 bg-[#dedbd6] rounded" />
        <div className="grid grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-16 bg-[#dedbd6] rounded" />)}
        </div>
        <div className="h-64 bg-[#dedbd6] rounded" />
      </div>
    );
  }

  if (!broadcast) {
    return (
      <div className="text-center py-12">
        <p className="text-[14px] text-[#7b7b78]">Disparo não encontrado.</p>
        <button onClick={() => router.push("/campanhas?tab=disparos")} className="mt-4 text-[13px] text-[#111111] underline">
          Voltar para disparos
        </button>
      </div>
    );
  }

  const bStatusConf = BROADCAST_STATUS_CONFIG[broadcast.status] ?? BROADCAST_STATUS_CONFIG.draft;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3 flex-wrap">
          <button onClick={() => router.push("/campanhas?tab=disparos")} className="text-[#7b7b78] hover:text-[#111111] text-[13px] transition-colors">
            ← Disparos
          </button>
          <h1 style={{ letterSpacing: "-0.5px" }} className="text-[24px] font-normal text-[#111111]">{broadcast.name}</h1>
          <span className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border ${bStatusConf.style}`}>
            {bStatusConf.label}
          </span>
        </div>
        <div className="flex gap-2 flex-shrink-0">
          {broadcast.status === "draft" && (
            <>
              <button
                onClick={() => handleAction("start")}
                disabled={actionLoading}
                className="bg-[#111111] text-white px-3 py-1.5 rounded-[4px] text-[13px] disabled:opacity-50 transition-transform hover:scale-105"
              >
                ▶ Iniciar
              </button>
              <button onClick={handleDelete} className="text-[#c41c1c] border border-[#c41c1c]/30 px-3 py-1.5 rounded-[4px] text-[13px] hover:bg-[#fef0f0] transition-colors">
                Excluir
              </button>
            </>
          )}
          {broadcast.status === "running" && (
            <button onClick={() => handleAction("pause")} disabled={actionLoading} className="border border-[#111111] text-[#111111] px-3 py-1.5 rounded-[4px] text-[13px] disabled:opacity-50 transition-transform hover:scale-105">
              ⏸ Pausar
            </button>
          )}
          {broadcast.status === "paused" && (
            <>
              <button onClick={() => handleAction("resume")} disabled={actionLoading} className="bg-[#111111] text-white px-3 py-1.5 rounded-[4px] text-[13px] disabled:opacity-50 transition-transform hover:scale-105">
                ▶ Retomar
              </button>
              <button onClick={handleDelete} className="text-[#c41c1c] border border-[#c41c1c]/30 px-3 py-1.5 rounded-[4px] text-[13px] hover:bg-[#fef0f0] transition-colors">
                Excluir
              </button>
            </>
          )}
        </div>
      </div>

      {/* Métricas */}
      <div className="grid grid-cols-5 gap-3">
        {([
          ["Total", broadcast.total_leads, "text-[#111111]"],
          ["Enviado", broadcast.sent, "text-[#1d5fa8]"],
          ["Entregue", broadcast.delivered, "text-[#1a7a3a]"],
          ["Falhou", broadcast.failed, "text-[#c41c1c]"],
          ["Pendente", broadcast.total_leads - broadcast.sent - broadcast.failed, "text-[#7b7b78]"],
        ] as [string, number, string][]).map(([label, val, color]) => (
          <div key={label} className="bg-white border border-[#dedbd6] rounded-[8px] p-4 text-center">
            <p className={`text-[28px] font-light ${color}`}>{Math.max(0, val)}</p>
            <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Retentar falhas */}
      {failedLeads.length > 0 && (
        <div className="bg-[#fef0f0] border border-[#c41c1c]/20 rounded-[8px] px-4 py-3 flex items-center justify-between">
          <p className="text-[13px] text-[#c41c1c]">
            <strong>{failedLeads.length} envios falharam.</strong> Crie um novo disparo para retentar automaticamente.
          </p>
          <a
            href={`/campanhas?tab=disparos&retry=${broadcastId}`}
            className="text-[13px] font-medium text-[#c41c1c] border border-[#c41c1c]/40 px-3 py-1.5 rounded-[4px] hover:bg-[#fef0f0] transition-colors whitespace-nowrap"
          >
            ↩ Retentar Falhas
          </a>
        </div>
      )}

      {/* Tabela de leads */}
      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
        {/* Filtros por status */}
        <div className="flex border-b border-[#dedbd6] overflow-x-auto">
          {(["all", "sent", "delivered", "failed", "pending"] as LeadStatusFilter[]).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-4 py-3 text-[13px] whitespace-nowrap border-b-2 transition-colors ${
                statusFilter === s ? "border-[#111111] text-[#111111]" : "border-transparent text-[#7b7b78] hover:text-[#111111]"
              }`}
            >
              {s === "all" ? "Todos" : STATUS_CONFIG[s]?.label} ({counts[s]})
            </button>
          ))}
        </div>

        {/* Tabela */}
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#f0ede8]">
                {["Nome", "Telefone", "Status", "Enviado em", "Erro"].map((h) => (
                  <th key={h} className="text-left text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] px-4 py-3 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredLeads.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-center text-[13px] text-[#7b7b78] py-8">Nenhum lead neste status.</td>
                </tr>
              )}
              {filteredLeads.map((bl) => {
                const sc = STATUS_CONFIG[bl.status] ?? STATUS_CONFIG.pending;
                return (
                  <tr key={bl.id} className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6]">
                    <td className="px-4 py-3 text-[13px] text-[#111111]">{bl.leads?.name ?? "—"}</td>
                    <td className="px-4 py-3 text-[13px] text-[#7b7b78]">{bl.leads?.phone ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`text-[11px] font-medium px-2 py-0.5 rounded-[4px] ${sc.style}`}>{sc.label}</span>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#7b7b78]">
                      {bl.sent_at ? new Date(bl.sent_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#c41c1c] max-w-xs truncate">{bl.error_message ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Criar a sub-página**

```typescript
// frontend/src/app/(authenticated)/campanhas/disparos/[id]/page.tsx
import { BroadcastDetail } from "@/components/campaigns/broadcast-detail";

export default async function BroadcastDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto px-4 md:px-8 py-4 md:py-8 bg-[#faf9f6]">
        <BroadcastDetail broadcastId={id} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verificar que BroadcastLead tem o campo `leads` no tipo**

```bash
grep -A 10 "BroadcastLead" frontend/src/lib/types.ts
```

Se o campo `leads` não existir no tipo `BroadcastLead`, adicionar:

```typescript
// Em frontend/src/lib/types.ts, no interface BroadcastLead:
leads?: { id: string; name: string | null; phone: string };
```

- [ ] **Step 5: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "broadcast-detail\|disparos" | head -20
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/campaigns/broadcast-detail.tsx
git add "frontend/src/app/(authenticated)/campanhas/disparos/[id]/page.tsx"
git commit -m "feat(campaigns): criar página de detalhe do disparo com tabela de leads e retentar falhas"
```

---

## Task 7: Componente TemplatesTab

**Files:**
- Create: `frontend/src/components/campaigns/templates-tab.tsx`

**REQUIRED:** Invocar skill `frontend-design` antes de escrever qualquer código de componente.

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Criar o componente**

```typescript
// frontend/src/components/campaigns/templates-tab.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import type { MessageTemplate } from "@/lib/types";
import { CreateTemplateModal } from "@/components/canais/create-template-modal";

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

const STATUS_CONFIG: Record<string, { label: string; style: string }> = {
  approved:                 { label: "Aprovado",          style: "text-[#1a7a3a] bg-[#e6faf0]" },
  pending:                  { label: "Pendente",          style: "text-[#7a5a00] bg-[#fff8e0]" },
  pending_category_review:  { label: "Rev. categoria",    style: "text-[#7a5a00] bg-[#fff8e0]" },
  cancelled:                { label: "Cancelado",         style: "text-[#7b7b78] bg-[#f0ede8]" },
  rejected:                 { label: "Rejeitado",         style: "text-[#c41c1c] bg-[#fef0f0]" },
};

export function TemplatesTab() {
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const fetch_ = useCallback(async () => {
    setLoading(true);
    const res = await fetch("/api/templates");
    if (res.ok) setTemplates(await res.json());
    setLoading(false);
  }, []);

  useEffect(() => { fetch_(); }, [fetch_]);

  // Polling para templates pendentes
  useEffect(() => {
    const hasPending = templates.some((t) => t.status === "pending" || t.status === "pending_category_review");
    if (!hasPending) return;
    const id = setInterval(fetch_, 30_000);
    return () => clearInterval(id);
  }, [templates, fetch_]);

  const cat = (c: string | null) => CATEGORY_CONFIG[(c ?? "").toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const st = (s: string) => STATUS_CONFIG[s] ?? STATUS_CONFIG.pending;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 style={{ letterSpacing: "-0.3px" }} className="text-[20px] font-normal text-[#111111]">Templates</h2>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
        >
          + Novo Template
        </button>
      </div>

      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 bg-[#dedbd6] rounded-[8px] animate-pulse" />
          ))}
        </div>
      )}

      {!loading && templates.length === 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] py-12 text-center">
          <p className="text-[14px] text-[#7b7b78]">Nenhum template cadastrado.</p>
          <button onClick={() => setShowCreate(true)} className="mt-3 text-[13px] text-[#111111] underline">
            Criar primeiro template
          </button>
        </div>
      )}

      {!loading && templates.length > 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#f0ede8]">
                {["Nome", "Categoria", "Status", "Idioma", "Criado em"].map((h) => (
                  <th key={h} className="text-left text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] px-4 py-3 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => {
                const c = cat(t.category);
                const s = st(t.status);
                return (
                  <tr key={t.id} className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6]">
                    <td className="px-4 py-3">
                      <p className="text-[13px] text-[#111111] font-medium">{t.name}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-[11px] font-medium px-2 py-0.5 rounded-[4px]" style={{ color: c.color, backgroundColor: c.bg }}>
                        {c.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[11px] font-medium px-2 py-0.5 rounded-[4px] ${s.style}`}>{s.label}</span>
                    </td>
                    <td className="px-4 py-3 text-[12px] text-[#7b7b78]">{t.language}</td>
                    <td className="px-4 py-3 text-[12px] text-[#7b7b78]">
                      {new Date(t.created_at).toLocaleDateString("pt-BR")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <CreateTemplateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => { setShowCreate(false); fetch_(); }}
      />
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/campaigns/templates-tab.tsx
git commit -m "feat(campaigns): criar TemplatesTab com lista de templates, status de aprovação e polling"
```

---

## Task 8: Atualizar campanhas/page.tsx

**Files:**
- Modify: `frontend/src/app/(authenticated)/campanhas/page.tsx`

**REQUIRED:** Invocar skill `frontend-design` antes de escrever qualquer código de componente.

Adicionar aba Templates, conectar `retry` via query string, atualizar botões do header.

- [ ] **Step 1: Invocar skill frontend-design**

- [ ] **Step 2: Atualizar o arquivo**

Modificar o arquivo existente em `frontend/src/app/(authenticated)/campanhas/page.tsx`:

1. Adicionar import de `TemplatesTab` e `useSearchParams` e `useRouter`:
```typescript
import { useSearchParams, useRouter } from "next/navigation";
import { TemplatesTab } from "@/components/campaigns/templates-tab";
```

2. Mudar o tipo do `activeTab`:
```typescript
const [activeTab, setActiveTab] = useState<"visao-geral" | "disparos" | "cadencias" | "templates">("visao-geral");
```

3. Adicionar leitura de query string logo após os estados (para deep link `?tab=`):
```typescript
const searchParams = useSearchParams();
const router = useRouter();

useEffect(() => {
  const tab = searchParams.get("tab") as typeof activeTab | null;
  if (tab && ["visao-geral", "disparos", "cadencias", "templates"].includes(tab)) {
    setActiveTab(tab);
  }
}, [searchParams]);
```

4. Atualizar o array de tabs no render:
```typescript
{(["visao-geral", "disparos", "cadencias", "templates"] as const).map((tab) => (
  <button
    key={tab}
    onClick={() => setActiveTab(tab)}
    className={...}
  >
    {tab === "visao-geral" ? "Visão Geral"
      : tab === "disparos" ? "Disparos"
      : tab === "cadencias" ? "Cadências"
      : "Templates"}
  </button>
))}
```

5. Adicionar conteúdo da aba Templates:
```typescript
{activeTab === "templates" && <TemplatesTab />}
```

6. Remover o botão `+ Template` do header (agora fica dentro da aba Templates):
```typescript
// Remover este bloco do header:
<button onClick={() => setShowTemplateModal(true)} ...>
  + Template
</button>
```

7. Remover `showTemplateModal`, `setShowTemplateModal` e o `<CreateTemplateModal>` do header (já está dentro de `TemplatesTab`).

8. Atualizar `BroadcastCard` / `BroadcastList` para que o clique navegue para `/campanhas/disparos/[id]`:
   - Em `broadcast-list.tsx`, verificar se `onClick` já navega. Se não, usar `useRouter` e passar `onClick={() => router.push(`/campanhas/disparos/${b.id}`)}`

- [ ] **Step 3: Verificar que a navegação do BroadcastCard funciona**

```bash
# Verificar broadcast-list.tsx
grep -n "onClick\|router\|href" frontend/src/components/campaigns/broadcast-list.tsx | head -20
```

Se `broadcast-list.tsx` passa `onClick` para `BroadcastCard` mas não navega, adicionar `useRouter` e fazer `router.push`:

```typescript
// Em broadcast-list.tsx, adicionar:
import { useRouter } from "next/navigation";

// Dentro do componente:
const router = useRouter();

// No render do BroadcastCard:
<BroadcastCard
  key={b.id}
  broadcast={b}
  onClick={() => router.push(`/campanhas/disparos/${b.id}`)}
  onStart={...}
  onPause={...}
/>
```

- [ ] **Step 4: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "campanhas" | head -20
```

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/app/(authenticated)/campanhas/page.tsx"
git add frontend/src/components/campaigns/broadcast-list.tsx
git commit -m "feat(campanhas): adicionar aba Templates, conectar navegação de cards e suporte a query string"
```

---

## Task 9: Verificação final e TypeScript

**Files:**
- Verify: todos os arquivos novos e modificados

- [ ] **Step 1: Checar TypeScript global**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -50
```

Corrigir todos os erros antes de continuar.

- [ ] **Step 2: Verificar que os imports estão corretos**

```bash
grep -rn "from.*template-preview-card\|from.*lead-filter-panel\|from.*broadcast-detail\|from.*templates-tab" frontend/src/components/campaigns/
```

- [ ] **Step 3: Testar o fluxo completo manualmente**

Com o servidor dev rodando (task `Run All Dev` no VS Code):

1. Abrir `/campanhas` → verificar 4 abas no topo
2. Clicar em `+ Disparo` → wizard abre com barra de progresso
3. Etapa 1: selecionar canal, verificar que "Sem Agente" está pré-selecionado
4. Etapa 2: selecionar template → card de prévia aparece com badge de categoria
5. Etapa 3: aplicar filtros → leads aparecem na tabela
6. Etapa 4: revisão → criar disparo
7. Na lista, clicar no card novo → navega para `/campanhas/disparos/[id]`
8. Verificar tabela de leads com abas de status
9. Aba Templates → verificar listagem com badges

- [ ] **Step 4: Commit final**

```bash
git add -A
git commit -m "feat(campanhas): redesign completo — wizard 4 etapas, detalhe de disparo, aba templates"
```

---

## Notas de Implementação

- **Sem Agente:** ao criar broadcast com `agentMode === "none"`, enviar `agent_profile_id: null` no payload. O backend já suporta null.
- **Retry de falhas:** o link `↩ Retentar Falhas` em `BroadcastDetail` usa `?retry=<broadcastId>`. A página de campanhas precisa ler esse param e abrir o wizard pré-preenchido. Isso requer buscar o broadcast original e os leads com status `failed`. Implementar no `useEffect` que lê `searchParams` em `campanhas/page.tsx`:
  ```typescript
  if (searchParams.get("retry")) {
    const retryId = searchParams.get("retry")!;
    // Buscar broadcast + leads failed + abrir modal pré-preenchido
    // ... (implementar conforme necessidade)
  }
  ```
- **Tag filter preciso:** o filtro de tags no `LeadFilterPanel` emite `tagIds[]`. O frontend filtra client-side após receber os leads. Para volume grande, considerar mover o filtro de tags para o servidor.
- **Polling de templates:** `TemplatesTab` faz polling a cada 30s somente quando há templates pendentes. Parar quando não há mais pendentes.

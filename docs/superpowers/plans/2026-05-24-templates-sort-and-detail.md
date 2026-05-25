# Templates — Ordenação e Visualização de Detalhes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar ordenação client-side por 5 colunas e um Sheet de visualização de detalhes (body, header, variáveis, botões) na tabela de templates em `/campanhas`.

**Architecture:** Extrair lógica de parsing de `components` JSON para `lib/template-parser.ts` compartilhado; enriquecer `/api/templates` para retornar campos parseados sem chamadas extras; adicionar estado de sort local + Sheet shadcn/ui no componente `TemplatesTab`.

**Tech Stack:** Next.js App Router, TypeScript, shadcn/ui (Sheet), lucide-react (ArrowUpDown, ArrowUp, ArrowDown, X), Tailwind CSS, Supabase (query existente)

---

## Mapa de Arquivos

| Arquivo | Ação |
|---|---|
| `frontend/src/lib/template-parser.ts` | **CRIAR** — funções de parsing extraídas |
| `frontend/src/lib/types.ts` | **MODIFICAR** — `MessageTemplate` com campos enriquecidos opcionais |
| `frontend/src/app/api/templates/route.ts` | **MODIFICAR** — SELECT com `components`, parsear antes de retornar |
| `frontend/src/app/api/channels/[id]/templates/route.ts` | **MODIFICAR** — importar de `template-parser.ts` |
| `frontend/src/components/campaigns/template-detail-sheet.tsx` | **CRIAR** — componente Sheet de detalhes |
| `frontend/src/components/campaigns/templates-tab.tsx` | **MODIFICAR** — sort state + clique na linha + Sheet |

---

### Task 1: Extrair lógica de parsing para módulo compartilhado

**Files:**
- Create: `frontend/src/lib/template-parser.ts`

- [ ] **Step 1: Criar `frontend/src/lib/template-parser.ts`**

```typescript
// frontend/src/lib/template-parser.ts

export interface TemplateParam {
  index: number;
  paramName: string;
  example: string;
}

export interface TemplateHeader {
  type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";
  text?: string;
  example?: string;
}

export interface ParsedTemplateComponents {
  body: string;
  header: TemplateHeader | null;
  footer: string | null;
  buttons: { type: string; text: string }[];
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
}

interface MetaApiParam {
  param_name: string;
  example: string;
}

interface MetaApiComponent {
  type: string;
  text?: string;
  format?: string;
  example?: {
    body_text?: string[][];
    body_text_named_params?: MetaApiParam[];
    header_url?: string[];
  };
  buttons?: Array<{ type: string; text: string }>;
}

export function parseTemplateComponents(
  components: unknown[]
): ParsedTemplateComponents {
  const comps = components as MetaApiComponent[];

  return {
    body: parseBody(comps),
    header: parseHeader(comps),
    footer: parseFooter(comps),
    buttons: parseButtons(comps),
    ...parseParamsAndType(comps),
  };
}

function parseParamsAndType(components: MetaApiComponent[]): {
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
} {
  const body = components.find((c) => c.type === "BODY");
  if (!body) return { params: [], paramsType: "none" };

  if (body.example?.body_text_named_params?.length) {
    return {
      params: body.example.body_text_named_params.map((p, i) => ({
        index: i + 1,
        paramName: p.param_name,
        example: p.example,
      })),
      paramsType: "named",
    };
  }

  if (body.example?.body_text?.[0]?.length) {
    return {
      params: body.example.body_text[0].map((ex, i) => ({
        index: i + 1,
        paramName: String(i + 1),
        example: ex,
      })),
      paramsType: "positional",
    };
  }

  const matches = [...(body.text ?? "").matchAll(/\{\{([\w]+)\}\}/g)];
  if (matches.length) {
    const unique = [...new Map(matches.map((m) => [m[1], m])).values()];
    const allNumeric = unique.every((m) => /^\d+$/.test(m[1]));
    return {
      params: unique.map((m, i) => ({
        index: i + 1,
        paramName: m[1],
        example: "",
      })),
      paramsType: allNumeric ? "positional" : "named",
    };
  }

  return { params: [], paramsType: "none" };
}

function parseHeader(components: MetaApiComponent[]): TemplateHeader | null {
  const header = components.find((c) => c.type === "HEADER");
  if (!header) return null;
  const fmt = header.format?.toUpperCase();
  if (fmt === "TEXT") return { type: "TEXT", text: header.text ?? "" };
  if (fmt === "IMAGE") return { type: "IMAGE", example: header.example?.header_url?.[0] };
  if (fmt === "VIDEO") return { type: "VIDEO", example: header.example?.header_url?.[0] };
  if (fmt === "DOCUMENT") return { type: "DOCUMENT", example: header.example?.header_url?.[0] };
  return null;
}

function parseBody(components: MetaApiComponent[]): string {
  return components.find((c) => c.type === "BODY")?.text ?? "";
}

function parseFooter(components: MetaApiComponent[]): string | null {
  return components.find((c) => c.type === "FOOTER")?.text ?? null;
}

function parseButtons(components: MetaApiComponent[]): { type: string; text: string }[] {
  return components.find((c) => c.type === "BUTTONS")?.buttons ?? [];
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/template-parser.ts
git commit -m "feat(templates): extrair lógica de parsing de components para módulo compartilhado"
```

---

### Task 2: Atualizar o tipo `MessageTemplate` em `lib/types.ts`

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Substituir a interface `MessageTemplate`**

Abrir `frontend/src/lib/types.ts`. Localizar a interface `MessageTemplate` (atualmente nas linhas ~181-190). Substituí-la por:

```typescript
export interface MessageTemplate {
  id: string;
  channel_id: string;
  name: string;
  language: string;
  category: string | null;
  requested_category: string | null;
  status: string;
  created_at: string;
  // Campos enriquecidos (parseados de components — presentes quando retornados por /api/templates)
  body?: string;
  header?: { type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT"; text?: string; example?: string } | null;
  footer?: string | null;
  buttons?: { type: string; text: string }[];
  params?: { index: number; paramName: string; example: string }[];
  paramsType?: "positional" | "named" | "none";
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(templates): enriquecer tipo MessageTemplate com campos de conteúdo opcionais"
```

---

### Task 3: Enriquecer `/api/templates` para retornar campos parseados

**Files:**
- Modify: `frontend/src/app/api/templates/route.ts`

- [ ] **Step 1: Substituir o conteúdo completo do arquivo**

```typescript
// frontend/src/app/api/templates/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { parseTemplateComponents } from "@/lib/template-parser";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");

  const supabase = await getServiceSupabase();
  let query = supabase
    .from("message_templates")
    .select("id, name, language, category, requested_category, status, created_at, channel_id, components")
    .order("created_at", { ascending: false });

  if (channelId) query = query.eq("channel_id", channelId);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const enriched = (data ?? []).map((t) => {
    const components = Array.isArray(t.components) ? t.components : [];
    const parsed = parseTemplateComponents(components);
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { components: _components, ...rest } = t as typeof t & { components: unknown[] };
    return { ...rest, ...parsed };
  });

  return NextResponse.json(enriched);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/api/templates/route.ts
git commit -m "feat(templates): incluir components no SELECT e retornar campos parseados na API"
```

---

### Task 4: Simplificar `/api/channels/[id]/templates` para usar o parser compartilhado

**Files:**
- Modify: `frontend/src/app/api/channels/[id]/templates/route.ts`

- [ ] **Step 1: Adicionar import e usar `parseTemplateComponents`**

No topo do arquivo `frontend/src/app/api/channels/[id]/templates/route.ts`, substituir o bloco completo de interfaces e funções de parsing internas (as interfaces `MetaApiParam`, `MetaApiComponent`, as funções `parseParamsAndType`, `parseHeader`, `parseBody`, `parseFooter`, `parseButtons`, e os tipos locais `TemplateParam`, `TemplateHeader`) pelo seguinte import:

```typescript
import { parseTemplateComponents, type TemplateParam, type TemplateHeader } from "@/lib/template-parser";
```

Manter as interfaces `MetaApiTemplate` e `MetaTemplate` (que são específicas desta rota pois lidam com o formato bruto da Meta API diretamente), e a interface `MetaApiComponent` que é usada em `MetaApiTemplate`.

Dentro do handler `GET`, substituir o bloco do `.map()` que chama `parseBody`, `parseHeader`, etc. por:

```typescript
const templates: MetaTemplate[] = ((json.data ?? []) as MetaApiTemplate[])
  .filter((t) => t.status === "APPROVED")
  .map((t) => {
    const parsed = parseTemplateComponents(t.components ?? []);
    return {
      name: t.name,
      language: t.language,
      category: (t.category ?? "").toLowerCase(),
      body: parsed.body,
      params: parsed.params,
      paramsType: parsed.paramsType,
      header: parsed.header,
      footer: parsed.footer,
      buttons: parsed.buttons,
    };
  })
  .sort((a, b) => a.name.localeCompare(b.name));
```

Remover as funções `parseParamsAndType`, `parseHeader`, `parseBody`, `parseFooter`, `parseButtons` e os tipos `TemplateParam`, `TemplateHeader` que eram definidos localmente neste arquivo (agora vêm do módulo compartilhado). Manter `MetaTemplate`, `MetaApiTemplate`, `MetaApiComponent`, `MetaApiParam` apenas se não exportados do parser — `MetaApiParam` e `MetaApiComponent` são detalhes internos de parse, podem ficar apenas em `template-parser.ts`. Remova-os deste arquivo.

- [ ] **Step 2: Verificar que o arquivo compila**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Esperado: sem erros relacionados a `channels/[id]/templates/route.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/channels/[id]/templates/route.ts
git commit -m "refactor(templates): usar template-parser compartilhado em channels/[id]/templates"
```

---

### Task 5: Instalar o componente Sheet do shadcn/ui

**Files:**
- Creates: `frontend/src/components/ui/sheet.tsx` (gerado pelo shadcn)

- [ ] **Step 1: Instalar Sheet**

```bash
cd frontend && npx shadcn@latest add sheet --yes
```

Esperado: arquivo `frontend/src/components/ui/sheet.tsx` criado.

- [ ] **Step 2: Confirmar que o arquivo foi criado**

```bash
ls frontend/src/components/ui/sheet.tsx
```

Esperado: path exibido sem erro.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/sheet.tsx
git commit -m "chore(deps): instalar componente Sheet do shadcn/ui"
```

---

### Task 6: Criar o componente `TemplateDetailSheet`

**Files:**
- Create: `frontend/src/components/campaigns/template-detail-sheet.tsx`

- [ ] **Step 1: Criar o arquivo**

```typescript
// frontend/src/components/campaigns/template-detail-sheet.tsx
"use client";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import type { MessageTemplate } from "@/lib/types";

// ─── Config ────────────────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

const STATUS_CONFIG: Record<string, { label: string; colorClass: string }> = {
  approved:                { label: "Aprovado",       colorClass: "bg-[#e6faf0] text-[#1a7a3a]" },
  pending:                 { label: "Pendente",       colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  pending_category_review: { label: "Rev. categoria", colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  cancelled:               { label: "Cancelado",      colorClass: "bg-[#f0ede8] text-[#7b7b78]" },
  rejected:                { label: "Rejeitado",      colorClass: "bg-[#fef0f0] text-[#c41c1c]" },
};

const HEADER_TYPE_LABEL: Record<string, string> = {
  TEXT: "Texto",
  IMAGE: "Imagem",
  VIDEO: "Vídeo",
  DOCUMENT: "Documento",
};

// ─── Body renderer ──────────────────────────────────────────────────────────────

function BodyWithVars({ body }: { body: string }) {
  const segments = body.split(/(\{\{[\w]+\}\})/g);
  return (
    <p className="text-[14px] text-[#111111] leading-relaxed whitespace-pre-wrap">
      {segments.map((seg, i) =>
        /^\{\{[\w]+\}\}$/.test(seg) ? (
          <span
            key={i}
            className="inline-flex items-center px-1 rounded text-[12px] font-mono font-medium text-[#7a5a00] bg-[#fff8e0]"
          >
            {seg}
          </span>
        ) : (
          seg
        )
      )}
    </p>
  );
}

// ─── Props ─────────────────────────────────────────────────────────────────────

interface TemplateDetailSheetProps {
  template: MessageTemplate | null;
  onClose: () => void;
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function TemplateDetailSheet({ template, onClose }: TemplateDetailSheetProps) {
  const cat = CATEGORY_CONFIG[(template?.category ?? "").toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const st = STATUS_CONFIG[template?.status ?? ""] ?? STATUS_CONFIG.cancelled;

  return (
    <Sheet open={template !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent className="w-[420px] sm:w-[480px] overflow-y-auto">
        {template && (
          <>
            <SheetHeader className="pb-4 border-b border-[#dedbd6]">
              <SheetTitle className="text-[16px] font-medium text-[#111111] leading-tight break-all">
                {template.name}
              </SheetTitle>
              <div className="flex flex-wrap gap-1.5 pt-1">
                <Badge
                  className="rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5"
                  style={{ color: cat.color, backgroundColor: cat.bg }}
                >
                  {cat.label}
                </Badge>
                <Badge className={`rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5 ${st.colorClass}`}>
                  {st.label}
                </Badge>
                <Badge
                  variant="outline"
                  className="rounded-[4px] h-auto text-[11px] font-normal px-2 py-0.5 text-[#7b7b78]"
                >
                  {template.language}
                </Badge>
              </div>
            </SheetHeader>

            <div className="py-4 space-y-5">

              {/* Header */}
              {template.header && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                    Cabeçalho · {HEADER_TYPE_LABEL[template.header.type] ?? template.header.type}
                  </p>
                  {template.header.type === "TEXT" && template.header.text ? (
                    <p className="text-[14px] font-semibold text-[#111111]">{template.header.text}</p>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-[13px] text-[#7b7b78] border border-[#dedbd6] px-2.5 py-1 rounded-[4px] bg-[#faf9f6]">
                      {template.header.type === "IMAGE" && "🖼"}
                      {template.header.type === "VIDEO" && "🎥"}
                      {template.header.type === "DOCUMENT" && "📄"}
                      Mídia {HEADER_TYPE_LABEL[template.header.type]?.toLowerCase()}
                    </span>
                  )}
                  <div className="mt-4 border-t border-[#f0ede8]" />
                </section>
              )}

              {/* Body */}
              {template.body && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Corpo</p>
                  <BodyWithVars body={template.body} />
                  <div className="mt-4 border-t border-[#f0ede8]" />
                </section>
              )}

              {/* Footer */}
              {template.footer && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Rodapé</p>
                  <p className="text-[13px] text-[#7b7b78] italic">{template.footer}</p>
                  <div className="mt-4 border-t border-[#f0ede8]" />
                </section>
              )}

              {/* Variables */}
              {template.params && template.params.length > 0 && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                    Variáveis ({template.params.length})
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {template.params.map((p) => (
                      <div key={p.paramName} className="border border-[#dedbd6] rounded-[4px] px-2.5 py-1.5 bg-[#faf9f6]">
                        <span className="text-[12px] font-mono text-[#7a5a00]">
                          {template.paramsType === "positional" ? `{{${p.index}}}` : `{{${p.paramName}}}`}
                        </span>
                        {p.example && (
                          <span className="text-[11px] text-[#7b7b78] ml-2">ex: {p.example}</span>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 border-t border-[#f0ede8]" />
                </section>
              )}

              {/* Buttons */}
              {template.buttons && template.buttons.length > 0 && (
                <section>
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                    Botões ({template.buttons.length})
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {template.buttons.map((btn, i) => (
                      <div key={i} className="border border-[#dedbd6] rounded-[4px] px-2.5 py-1.5 bg-[#faf9f6] flex items-center gap-1.5">
                        <span className="text-[10px] uppercase tracking-[0.5px] text-[#b0aca6]">{btn.type}</span>
                        <span className="text-[13px] text-[#111111]">{btn.text}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Empty content fallback */}
              {!template.body && !template.header && (!template.buttons || template.buttons.length === 0) && (
                <p className="text-[13px] text-[#7b7b78] text-center py-4">
                  Conteúdo não disponível para este template.
                </p>
              )}

            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/campaigns/template-detail-sheet.tsx
git commit -m "feat(templates): criar componente TemplateDetailSheet para visualização de detalhes"
```

---

### Task 7: Atualizar `TemplatesTab` — ordenação + abertura do Sheet

**Files:**
- Modify: `frontend/src/components/campaigns/templates-tab.tsx`

- [ ] **Step 1: Substituir o conteúdo completo do arquivo**

```typescript
// frontend/src/components/campaigns/templates-tab.tsx
"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import type { MessageTemplate, Channel } from "@/lib/types";
import { CreateTemplateModal } from "@/components/canais/create-template-modal";
import { TemplateDetailSheet } from "@/components/campaigns/template-detail-sheet";

// ─── Config ────────────────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

const STATUS_CONFIG: Record<string, { label: string; colorClass: string }> = {
  approved:                { label: "Aprovado",       colorClass: "bg-[#e6faf0] text-[#1a7a3a]" },
  pending:                 { label: "Pendente",       colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  pending_category_review: { label: "Rev. categoria", colorClass: "bg-[#fff8e0] text-[#7a5a00]" },
  cancelled:               { label: "Cancelado",      colorClass: "bg-[#f0ede8] text-[#7b7b78]" },
  rejected:                { label: "Rejeitado",      colorClass: "bg-[#fef0f0] text-[#c41c1c]" },
};

// ─── Sort ──────────────────────────────────────────────────────────────────────

type SortKey = "name" | "category" | "status" | "language" | "created_at";
type SortDirection = "asc" | "desc";

interface SortConfig {
  key: SortKey;
  direction: SortDirection;
}

function sortTemplates(templates: MessageTemplate[], config: SortConfig | null): MessageTemplate[] {
  if (!config) return templates;
  return [...templates].sort((a, b) => {
    let aVal: string;
    let bVal: string;
    if (config.key === "category") {
      aVal = (a.category ?? "").toLowerCase();
      bVal = (b.category ?? "").toLowerCase();
    } else if (config.key === "created_at") {
      aVal = a.created_at;
      bVal = b.created_at;
    } else {
      aVal = (a[config.key] ?? "").toString().toLowerCase();
      bVal = (b[config.key] ?? "").toString().toLowerCase();
    }
    const cmp = aVal.localeCompare(bVal);
    return config.direction === "asc" ? cmp : -cmp;
  });
}

// ─── SortableHeader ────────────────────────────────────────────────────────────

interface SortableHeaderProps {
  label: string;
  sortKey: SortKey;
  sortConfig: SortConfig | null;
  onSort: (key: SortKey) => void;
}

function SortableHeader({ label, sortKey, sortConfig, onSort }: SortableHeaderProps) {
  const isActive = sortConfig?.key === sortKey;
  const direction = isActive ? sortConfig!.direction : null;
  return (
    <th className="text-left px-4 py-3 font-normal">
      <button
        onClick={() => onSort(sortKey)}
        className="flex items-center gap-1 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] hover:text-[#111111] transition-colors"
      >
        {label}
        {!isActive && <ArrowUpDown size={12} className="opacity-40" />}
        {direction === "asc" && <ArrowUp size={12} />}
        {direction === "desc" && <ArrowDown size={12} />}
      </button>
    </th>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function TemplatesTab() {
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncToast, setSyncToast] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [sortConfig, setSortConfig] = useState<SortConfig | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<MessageTemplate | null>(null);
  const hasSyncedOnMount = useRef(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    const res = await fetch("/api/templates");
    if (res.ok) setTemplates(await res.json());
    setLoading(false);
  }, []);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const syncTemplates = useCallback(async () => {
    setSyncing(true);
    try {
      const channelsRes = await fetch("/api/channels");
      if (!channelsRes.ok) throw new Error("Falha ao carregar canais");
      const channelsData: Channel[] = await channelsRes.json();
      const metaChannels = (Array.isArray(channelsData) ? channelsData : []).filter(
        (c) =>
          c.provider === "meta_cloud" &&
          c.is_active &&
          c.provider_config?.waba_id &&
          c.provider_config?.access_token
      );

      let errors = 0;
      for (const channel of metaChannels) {
        const res = await fetch(`/api/templates/sync?channel_id=${channel.id}`, { method: "POST" });
        if (!res.ok) errors++;
      }

      await loadTemplates();
      setSyncToast(
        errors === 0
          ? { type: "success", message: "Templates sincronizados com sucesso." }
          : { type: "error", message: `Sincronização concluída com ${errors} erro(s).` }
      );
    } catch {
      setSyncToast({ type: "error", message: "Erro ao sincronizar templates." });
    } finally {
      setSyncing(false);
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      toastTimerRef.current = setTimeout(() => setSyncToast(null), 5000);
    }
  }, [loadTemplates]);

  useEffect(() => {
    if (hasSyncedOnMount.current) return;
    hasSyncedOnMount.current = true;
    syncTemplates();
  }, [syncTemplates]);

  useEffect(() => {
    return () => { if (toastTimerRef.current) clearTimeout(toastTimerRef.current); };
  }, []);

  const handleSort = (key: SortKey) => {
    setSortConfig((prev) => {
      if (!prev || prev.key !== key) return { key, direction: "asc" };
      if (prev.direction === "asc") return { key, direction: "desc" };
      return null;
    });
  };

  const cat = (c: string | null) => CATEGORY_CONFIG[(c ?? "").toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const st = (s: string) => STATUS_CONFIG[s] ?? STATUS_CONFIG.cancelled;

  const sorted = sortTemplates(templates, sortConfig);

  const SORT_COLUMNS: { label: string; key: SortKey }[] = [
    { label: "Nome", key: "name" },
    { label: "Categoria", key: "category" },
    { label: "Status", key: "status" },
    { label: "Idioma", key: "language" },
    { label: "Criado em", key: "created_at" },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 style={{ letterSpacing: "-0.3px" }} className="text-[20px] font-normal text-[#111111]">
          Templates
        </h2>
        <div className="flex gap-2">
          <button
            onClick={syncTemplates}
            disabled={syncing}
            className="flex items-center gap-2 bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14" height="14" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round"
              className={syncing ? "animate-spin" : ""}
            >
              <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
              <path d="M21 3v5h-5" />
              <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
              <path d="M8 16H3v5" />
            </svg>
            {syncing ? "Sincronizando..." : "Sincronizar"}
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
          >
            + Novo Template
          </button>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 bg-[#dedbd6] rounded-[8px] animate-pulse" />
          ))}
        </div>
      )}

      {/* Empty */}
      {!loading && templates.length === 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] py-12 text-center">
          <p className="text-[14px] text-[#7b7b78]">Nenhum template cadastrado.</p>
          <button onClick={() => setShowCreate(true)} className="mt-3 text-[13px] text-[#111111] underline">
            Criar primeiro template
          </button>
        </div>
      )}

      {/* Table */}
      {!loading && templates.length > 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#f0ede8]">
                {SORT_COLUMNS.map((col) => (
                  <SortableHeader
                    key={col.key}
                    label={col.label}
                    sortKey={col.key}
                    sortConfig={sortConfig}
                    onSort={handleSort}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((t) => {
                const c = cat(t.category);
                const s = st(t.status);
                return (
                  <tr
                    key={t.id}
                    onClick={() => setSelectedTemplate(t)}
                    className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6] cursor-pointer"
                  >
                    <td className="px-4 py-3">
                      <p className="text-[13px] text-[#111111] font-medium">{t.name}</p>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        className="rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5"
                        style={{ color: c.color, backgroundColor: c.bg }}
                      >
                        {c.label}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge className={`rounded-[4px] border-0 h-auto text-[11px] font-medium px-2 py-0.5 ${s.colorClass}`}>
                        {s.label}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        variant="outline"
                        className="rounded-[4px] h-auto text-[11px] font-normal px-2 py-0.5 text-[#7b7b78]"
                      >
                        {t.language}
                      </Badge>
                    </td>
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

      {/* Sync toast */}
      {syncToast && (
        <div className={`fixed bottom-6 right-6 z-50 text-white text-[14px] px-4 py-3 rounded-[6px] shadow-lg flex items-center gap-3 ${syncToast.type === "success" ? "bg-[#111111]" : "bg-[#c41c1c]"}`}>
          <span>{syncToast.message}</span>
          <button onClick={() => setSyncToast(null)} className="text-white/60 hover:text-white transition-colors leading-none text-lg">&times;</button>
        </div>
      )}

      {/* Detail Sheet */}
      <TemplateDetailSheet
        template={selectedTemplate}
        onClose={() => setSelectedTemplate(null)}
      />

      <CreateTemplateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => { setShowCreate(false); loadTemplates(); }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verificar que não há erros de TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Esperado: sem erros nos arquivos modificados.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/campaigns/templates-tab.tsx
git commit -m "feat(templates): adicionar ordenação por coluna e Sheet de detalhes"
```

---

### Task 8: Verificação final e commit de documentação

- [ ] **Step 1: Verificar TypeScript geral**

```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -5
```

Esperado: `0 errors` ou somente erros pré-existentes não relacionados a esta feature.

- [ ] **Step 2: Confirmar arquivos criados**

```bash
ls frontend/src/lib/template-parser.ts frontend/src/components/campaigns/template-detail-sheet.tsx frontend/src/components/ui/sheet.tsx
```

Esperado: todos os três paths exibidos sem erro.

- [ ] **Step 3: Commit da spec e plano**

```bash
git add docs/superpowers/
git commit -m "docs: adicionar spec e plano de implementação para templates sort e detail"
```

---

## Self-Review

**Spec coverage:**
- ✅ Ordenação por Nome, Categoria, Status, Idioma, Criado em → Task 7 (`SortableHeader`, `sortTemplates`, `handleSort`)
- ✅ Clique na linha abre Sheet → Task 7 (`onClick={() => setSelectedTemplate(t)}`)
- ✅ Sheet com Header, Body, Variáveis, Botões → Task 6 (`TemplateDetailSheet`)
- ✅ Dados enriquecidos sem chamada extra → Task 3 (`/api/templates` com `components`)
- ✅ Parser compartilhado → Task 1 + Task 4
- ✅ Sheet shadcn instalado → Task 5
- ✅ Tipo `MessageTemplate` atualizado → Task 2
- ✅ Nova branch criada → feito antes da Task 1

**Placeholders:** nenhum encontrado.

**Type consistency:**
- `MessageTemplate` enriquecido na Task 2 com campos opcionais `body?`, `header?`, `footer?`, `buttons?`, `params?`, `paramsType?`
- `TemplateDetailSheet` usa `template.body`, `template.header`, `template.buttons`, `template.params`, `template.paramsType`, `template.footer` — todos presentes no tipo da Task 2 ✅
- `parseTemplateComponents` definida na Task 1, importada nas Tasks 3 e 4 ✅
- `SortKey` referencia campos de `MessageTemplate` que existem: `name`, `category`, `status`, `language`, `created_at` ✅

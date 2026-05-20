# Broadcast Modal — Smart Template Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Frontend agents:** REQUIRED SUB-SKILL: Use superpowers:frontend-design for every task that touches frontend files.

**Goal:** Make the broadcast wizard handle any Meta template type correctly — positional params, named params, media headers (IMAGE/VIDEO/DOCUMENT) — with a token-picker UI that auto-suggests lead field mappings and blocks advancement until all variables are filled.

**Architecture:** The template parsing route gains full component extraction (positional param detection, header type, footer). `TemplatePreviewCard` is rebuilt with a per-variable token picker (dropdown → lead field tokens or static text). The backend worker gains media header component building and new lead tokens. No DB migration needed — metadata stored in existing `template_variables` JSONB via `__key__` prefixes.

**Tech Stack:** Next.js 15 App Router, React (client), Supabase JS, FastAPI Python, Meta Graph API v25.0.

---

## File Map

| File | What changes |
|------|-------------|
| `frontend/src/app/api/channels/[id]/templates/route.ts` | Full rewrite of parsing: positional param detection, header, footer, paramsType |
| `frontend/src/components/campaigns/template-preview-card.tsx` | Full rebuild: media header URL input, token picker per slot, footer, buttons |
| `frontend/src/components/campaigns/create-broadcast-modal.tsx` | Update MetaTemplate type, canGoToStep3, handleSelectTemplate, prefill effect |
| `backend/app/broadcast/worker.py` | Add 4 new tokens, rewrite _build_template_components for positional + media header |

---

## Task 1: Enhance template parsing route

**Files:**
- Modify: `frontend/src/app/api/channels/[id]/templates/route.ts`

Read the current file first — it's at lines 1–109.

- [ ] **Step 1: Replace the entire file with the new implementation**

```typescript
import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

// ─── Internal Meta API types ──────────────────────────────────────────────────

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

interface MetaApiTemplate {
  name: string;
  status: string;
  language: string;
  category: string;
  components: MetaApiComponent[];
}

// ─── Public types (consumed by frontend components) ───────────────────────────

export interface TemplateParam {
  index: number;      // 1-based
  paramName: string;  // "first_name" (named) | "1" "2" "3" (positional)
  example: string;
}

export interface TemplateHeader {
  type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";
  text?: string;
  example?: string;
}

export interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
  header: TemplateHeader | null;
  footer: string | null;
  buttons: { type: string; text: string }[];
}

// ─── Parsers ──────────────────────────────────────────────────────────────────

function parseParamsAndType(components: MetaApiComponent[]): {
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
} {
  const body = components.find((c) => c.type === "BODY");
  if (!body) return { params: [], paramsType: "none" };

  // Named params (newer Meta format)
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

  // Positional params via body_text examples
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

  // Fallback: count {{N}} occurrences in body text
  const matches = [...(body.text ?? "").matchAll(/\{\{(\d+)\}\}/g)];
  if (matches.length) {
    return {
      params: matches.map((m, i) => ({
        index: i + 1,
        paramName: m[1],
        example: "",
      })),
      paramsType: "positional",
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

// ─── Route handlers ───────────────────────────────────────────────────────────

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data: channel, error } = await supabase
    .from("channels")
    .select("provider_config")
    .eq("id", id)
    .single();

  if (error || !channel) {
    return NextResponse.json({ error: "Canal não encontrado" }, { status: 404 });
  }

  const config = channel.provider_config as Record<string, string>;
  const { access_token, waba_id, api_version } = config;

  if (!access_token || !waba_id) {
    return NextResponse.json(
      { error: "Canal sem access_token ou waba_id configurado" },
      { status: 400 }
    );
  }

  const version = api_version || "v20.0";
  const url = `https://graph.facebook.com/${version}/${waba_id}/message_templates?fields=name,status,language,category,components&limit=200`;

  const metaRes = await fetch(url, {
    headers: { Authorization: `Bearer ${access_token}` },
  });

  if (!metaRes.ok) {
    const err = await metaRes.text();
    return NextResponse.json({ error: `Meta API error: ${err}` }, { status: metaRes.status });
  }

  const json = await metaRes.json();
  const templates: MetaTemplate[] = (json.data as MetaApiTemplate[])
    .filter((t) => t.status === "APPROVED")
    .map((t) => {
      const { params, paramsType } = parseParamsAndType(t.components ?? []);
      return {
        name: t.name,
        language: t.language,
        category: (t.category ?? "").toLowerCase(),
        body: parseBody(t.components ?? []),
        params,
        paramsType,
        header: parseHeader(t.components ?? []),
        footer: parseFooter(t.components ?? []),
        buttons: parseButtons(t.components ?? []),
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));

  return NextResponse.json(templates);
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

  const res = await fetch(`${backendUrl}/api/channels/${id}/templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
```

- [ ] **Step 2: Verify TypeScript compiles (run from frontend/)**

```bash
cd frontend && npm run type-check 2>&1 | head -30
```

Expected: no errors related to this file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/channels/\[id\]/templates/route.ts
git commit -m "feat(templates): detectar params posicionais, header, footer no parser"
```

---

## Task 2: Rebuild TemplatePreviewCard

**Files:**
- Modify: `frontend/src/components/campaigns/template-preview-card.tsx`

> **REQUIRED:** Use superpowers:frontend-design skill before making any changes.

Read the current file first (126 lines). This task replaces it entirely.

Key design decisions:
- Token picker: dropdown per variable slot with ⚡ lead tokens + ✏ Texto fixo option
- Texto fixo reveals an `<input>` below the dropdown
- Auto-suggest: phone-like example → `{{telefone}}`, single word → `{{primeiro_nome}}`, 2–3 words → `{{nome_completo}}`, anything else → empty (texto fixo)
- Media header URL input (required when header.type is IMAGE/VIDEO/DOCUMENT)
- Preview renders the body with current values substituted inline
- Footer and buttons displayed at bottom

- [ ] **Step 1: Replace the entire file**

```tsx
"use client";

import React from "react";

// ─── Types (must match route.ts output) ───────────────────────────────────────

interface TemplateParam {
  index: number;
  paramName: string;
  example: string;
}

interface TemplateHeader {
  type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";
  text?: string;
  example?: string;
}

export interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
  header: TemplateHeader | null;
  footer: string | null;
  buttons: { type: string; text: string }[];
}

// ─── Token options ────────────────────────────────────────────────────────────

const LEAD_TOKENS = [
  { value: "{{primeiro_nome}}", label: "Primeiro nome" },
  { value: "{{nome_completo}}", label: "Nome completo" },
  { value: "{{telefone}}", label: "Telefone" },
  { value: "{{empresa}}", label: "Empresa" },
] as const;

type TokenValue = (typeof LEAD_TOKENS)[number]["value"];
const KNOWN_TOKENS = new Set<string>(LEAD_TOKENS.map((t) => t.value));

// ─── Category config ──────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utility",        color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Authentication", color: "#6b27a8", bg: "#f2eafc" },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function autoSuggestToken(example: string): string {
  if (!example) return "";
  if (/^[\d\s\-\(\)\+]+$/.test(example) && example.replace(/\D/g, "").length >= 8) {
    return "{{telefone}}";
  }
  if (!example.includes(" ")) return "{{primeiro_nome}}";
  if (example.trim().split(/\s+/).length <= 3) return "{{nome_completo}}";
  return "";
}

function resolvePreview(value: string): string {
  const token = LEAD_TOKENS.find((t) => t.value === value);
  if (token) return `[${token.label}]`;
  return value || "…";
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface TemplatePreviewCardProps {
  template: MetaTemplate;
  varValues: Record<string, string>;
  onVarChange: (paramName: string, value: string) => void;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function TemplatePreviewCard({
  template,
  varValues,
  onVarChange,
}: TemplatePreviewCardProps) {
  const cat =
    CATEGORY_CONFIG[template.category?.toLowerCase()] ?? CATEGORY_CONFIG.utility;
  const hasMediaHeader =
    template.header !== null && template.header.type !== "TEXT";
  const headerUrl = varValues["__header_url__"] ?? "";

  // ── Body preview with inline variable substitution ─────────────────────────
  const renderBody = () => {
    const parts: React.ReactNode[] = [];
    const raw = template.body ?? "";
    // Split on {{word}} or {{N}} patterns
    const segments = raw.split(/(\{\{[\w]+\}\})/g);
    let paramIdx = 0;

    for (const seg of segments) {
      if (/^\{\{[\w]+\}\}$/.test(seg)) {
        const param = template.params[paramIdx];
        const paramName = param?.paramName ?? seg.slice(2, -2);
        const val = varValues[paramName] ?? "";
        const preview = resolvePreview(val);
        parts.push(
          <span
            key={`p-${paramIdx}`}
            className={`inline-flex items-center px-1 rounded text-[12px] font-medium ${
              val
                ? "text-[#7a5a00] bg-[#fff8e0]"
                : "text-[#c41c1c] bg-[#fef0f0]"
            }`}
          >
            {preview}
          </span>
        );
        paramIdx++;
      } else {
        parts.push(seg);
      }
    }
    return parts;
  };

  // ── Token picker per variable slot ─────────────────────────────────────────
  const renderSlot = (param: TemplateParam) => {
    const val = varValues[param.paramName] ?? "";
    const isToken = KNOWN_TOKENS.has(val);
    const selectVal: string = isToken ? val : "texto_fixo";
    const slotLabel =
      template.paramsType === "positional"
        ? `{{${param.index}}}`
        : `{{${param.paramName}}}`;

    return (
      <div key={param.paramName} className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-[#7b7b78] font-mono w-20 flex-shrink-0 truncate">
            {slotLabel}
          </span>
          <select
            value={selectVal}
            onChange={(e) => {
              const mode = e.target.value;
              if (mode !== "texto_fixo") {
                onVarChange(param.paramName, mode as TokenValue);
              } else {
                onVarChange(param.paramName, "");
              }
            }}
            className="flex-1 bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
          >
            {LEAD_TOKENS.map((t) => (
              <option key={t.value} value={t.value}>
                ⚡ {t.label}
              </option>
            ))}
            <option value="texto_fixo">✏ Texto fixo</option>
          </select>
        </div>

        {selectVal === "texto_fixo" && (
          <div className="pl-[88px]">
            <input
              value={val}
              onChange={(e) => onVarChange(param.paramName, e.target.value)}
              placeholder={
                param.example ? `Ex: ${param.example}` : "Digite o texto..."
              }
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1 text-[13px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none"
            />
          </div>
        )}
      </div>
    );
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="border border-[#dedbd6] rounded-[8px] overflow-hidden">
      {/* Header bar */}
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

      {/* Media header URL input */}
      {hasMediaHeader && (
        <div className="px-4 pt-3 pb-2 border-b border-[#f0ede8]">
          <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
            URL da mídia ({template.header!.type.toLowerCase()}){" "}
            <span className="text-[#c41c1c]">*</span>
          </label>
          <input
            value={headerUrl}
            onChange={(e) => onVarChange("__header_url__", e.target.value)}
            placeholder={template.header!.example ?? "https://..."}
            className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1.5 text-[13px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none"
          />
          {headerUrl && template.header!.type === "IMAGE" && (
            <div className="mt-2 rounded-[4px] overflow-hidden bg-[#f0ede8] h-20 flex items-center justify-center">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={headerUrl}
                alt="preview"
                className="h-full w-full object-cover"
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).style.display = "none";
                }}
              />
            </div>
          )}
          {headerUrl && template.header!.type !== "IMAGE" && (
            <p className="mt-1 text-[12px] text-[#1a7a3a]">
              {template.header!.type === "VIDEO" ? "🎥" : "📄"} URL de{" "}
              {template.header!.type.toLowerCase()} configurada.
            </p>
          )}
        </div>
      )}

      {/* TEXT header */}
      {template.header?.type === "TEXT" && template.header.text && (
        <div className="px-4 pt-3 pb-1">
          <p className="text-[14px] font-semibold text-[#111111]">
            {template.header.text}
          </p>
        </div>
      )}

      {/* Body preview */}
      <div className="px-4 py-3 bg-white">
        <p className="text-[14px] text-[#111111] leading-relaxed whitespace-pre-wrap">
          {renderBody()}
        </p>
      </div>

      {/* Footer */}
      {template.footer && (
        <div className="px-4 pb-2">
          <p className="text-[12px] text-[#7b7b78] italic">{template.footer}</p>
        </div>
      )}

      {/* Buttons */}
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

      {/* Variable slots */}
      {template.params.length > 0 && (
        <div className="px-4 pb-3 pt-2 border-t border-[#f0ede8] space-y-2">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Variáveis da mensagem
          </p>
          {template.params.map(renderSlot)}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Run type-check**

```bash
cd frontend && npm run type-check 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/campaigns/template-preview-card.tsx
git commit -m "feat(template-card): token picker, media header, footer, params posicionais"
```

---

## Task 3: Update create-broadcast-modal.tsx

**Files:**
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx`

> **REQUIRED:** Use superpowers:frontend-design skill before making any changes.

Read the current file first (1090 lines). Make the following targeted edits.

The goal is to update the modal to use the new `MetaTemplate` shape from Task 1, compute `canGoToStep3` correctly, and initialize `templateVarValues` with `__params_type__` and `__header_type__` metadata on template selection.

- [ ] **Step 1: Replace the `MetaTemplate` interface and remove old helpers**

Find and replace this block (lines 11–45 approximately):

```typescript
// OLD — remove this entire block
interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: string[];
  buttons?: { type: string; text: string }[];
}

// Variables auto-resolved from the lead record at send time.
const AUTO_VARS = new Set(["first_name", "primeiro_nome", "nome", "name", "phone"]);

function defaultVarValue(paramName: string): string {
  return AUTO_VARS.has(paramName.toLowerCase()) ? `{{${paramName}}}` : "";
}
```

Replace with:

```typescript
import type { MetaTemplate } from "@/components/campaigns/template-preview-card";
import { autoSuggestToken } from "@/components/campaigns/template-preview-card";
```

Note: `MetaTemplate` and `autoSuggestToken` are now exported from `template-preview-card.tsx` (Task 2 exported them).

- [ ] **Step 2: Update `handleSelectTemplate` to initialize metadata keys**

Find the current `handleSelectTemplate` function (~lines 201–219):

```typescript
// OLD
const handleSelectTemplate = (key: string) => {
  if (!key) {
    setSelectedTemplate(null);
    setTemplateVarValues({});
    return;
  }
  const [tname, lang] = key.split("|");
  const tpl = templates.find((t) => t.name === tname && t.language === lang) ?? null;
  setSelectedTemplate(tpl);
  if (tpl) {
    const defaults: Record<string, string> = {};
    tpl.params.forEach((p) => {
      defaults[p] = defaultVarValue(p);
    });
    setTemplateVarValues(defaults);
  } else {
    setTemplateVarValues({});
  }
};
```

Replace with:

```typescript
const handleSelectTemplate = (key: string) => {
  if (!key) {
    setSelectedTemplate(null);
    setTemplateVarValues({});
    return;
  }
  const [tname, lang] = key.split("|");
  const tpl = templates.find((t) => t.name === tname && t.language === lang) ?? null;
  setSelectedTemplate(tpl);
  if (tpl) {
    const defaults: Record<string, string> = {};
    if (tpl.paramsType !== "none") defaults["__params_type__"] = tpl.paramsType;
    if (tpl.header) defaults["__header_type__"] = tpl.header.type;
    tpl.params.forEach((p) => {
      defaults[p.paramName] = autoSuggestToken(p.example);
    });
    setTemplateVarValues(defaults);
  } else {
    setTemplateVarValues({});
  }
};
```

- [ ] **Step 3: Update the prefill effect**

Find the current effect (~lines 173–186):

```typescript
// OLD
useEffect(() => {
  if (!prefill?.templateName || templates.length === 0) return;
  const tpl = templates.find(
    (t) => t.name === prefill.templateName && t.language === prefill.templateLanguage
  );
  if (tpl) {
    setSelectedTemplate(tpl);
    const defaults: Record<string, string> = {};
    tpl.params.forEach((p) => {
      defaults[p] = prefill.varValues?.[p] ?? defaultVarValue(p);
    });
    setTemplateVarValues(defaults);
  }
}, [prefill, templates]);
```

Replace with:

```typescript
useEffect(() => {
  if (!prefill?.templateName || templates.length === 0) return;
  const tpl = templates.find(
    (t) => t.name === prefill.templateName && t.language === prefill.templateLanguage
  );
  if (tpl) {
    setSelectedTemplate(tpl);
    const defaults: Record<string, string> = {};
    if (tpl.paramsType !== "none") defaults["__params_type__"] = tpl.paramsType;
    if (tpl.header) defaults["__header_type__"] = tpl.header.type;
    tpl.params.forEach((p) => {
      defaults[p.paramName] =
        prefill.varValues?.[p.paramName] ?? autoSuggestToken(p.example);
    });
    setTemplateVarValues(defaults);
  }
}, [prefill, templates]);
```

- [ ] **Step 4: Update `canGoToStep3`**

Find the current line (~line 427):

```typescript
// OLD
const canGoToStep3 = selectedTemplate !== null;
```

Replace with:

```typescript
const canGoToStep3 =
  selectedTemplate !== null &&
  selectedTemplate.params.every(
    (p) => (templateVarValues[p.paramName] ?? "").trim() !== ""
  ) &&
  (
    !selectedTemplate.header ||
    selectedTemplate.header.type === "TEXT" ||
    (templateVarValues["__header_url__"] ?? "").trim() !== ""
  );
```

- [ ] **Step 5: Update the Revisão block to display variables correctly**

Find the variables section in the Revisão step (~line 989):

```typescript
// OLD
{Object.keys(templateVarValues).length > 0 && (
  <div>
    <span className="text-[#7b7b78]">Variáveis:</span>
    <ul className="ml-3 mt-1 space-y-0.5">
      {Object.entries(templateVarValues).map(([k, v]) => (
        <li key={k} className="text-[12px]">
          <span className="text-[#7b7b78]">{k}:</span>{" "}
          {v ? (
            <span className="text-[#111111]">{v}</span>
          ) : (
            <em className="text-[#b0aca6]">vazio</em>
          )}
        </li>
      ))}
    </ul>
  </div>
)}
```

Replace with (filters out `__key__` metadata from display):

```typescript
{selectedTemplate && selectedTemplate.params.length > 0 && (
  <div>
    <span className="text-[#7b7b78]">Variáveis:</span>
    <ul className="ml-3 mt-1 space-y-0.5">
      {selectedTemplate.params.map((p) => {
        const v = templateVarValues[p.paramName] ?? "";
        return (
          <li key={p.paramName} className="text-[12px]">
            <span className="text-[#7b7b78]">
              {selectedTemplate.paramsType === "positional"
                ? `{{${p.index}}}`
                : `{{${p.paramName}}}`}
              :
            </span>{" "}
            {v ? (
              <span className="text-[#111111]">{v}</span>
            ) : (
              <em className="text-[#b0aca6]">vazio</em>
            )}
          </li>
        );
      })}
      {(templateVarValues["__header_url__"] ?? "") && (
        <li className="text-[12px]">
          <span className="text-[#7b7b78]">mídia:</span>{" "}
          <span className="text-[#111111] truncate">{templateVarValues["__header_url__"]}</span>
        </li>
      )}
    </ul>
  </div>
)}
```

- [ ] **Step 6: Run type-check**

```bash
cd frontend && npm run type-check 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(broadcast-modal): canGoToStep3 inteligente, init vars com sugestão automática"
```

---

## Task 4: Update backend worker

**Files:**
- Modify: `backend/app/broadcast/worker.py` (lines 35–39 and lines 115–130)

Read the current file before editing. The two changes are:
1. `_LEAD_FIELD_TOKENS` dict — add 4 new tokens
2. `_build_template_components` function — support positional params + media header

- [ ] **Step 1: Replace `_LEAD_FIELD_TOKENS` (lines 35–39)**

Find:

```python
_LEAD_FIELD_TOKENS = {
    "{{first_name}}": lambda lead: (lead.get("name") or "").split()[0] if lead.get("name") else "",
    "{{lead_name}}":  lambda lead: lead.get("name") or "",
    "{{phone}}":      lambda lead: lead.get("phone") or "",
}
```

Replace with:

```python
_LEAD_FIELD_TOKENS = {
    # New tokens (used by smart broadcast modal)
    "{{primeiro_nome}}": lambda lead: (lead.get("name") or "").split()[0] if lead.get("name") else "",
    "{{nome_completo}}": lambda lead: lead.get("name") or "",
    "{{telefone}}":      lambda lead: lead.get("phone") or "",
    "{{empresa}}":       lambda lead: lead.get("company") or lead.get("nome_fantasia") or "",
    # Legacy tokens kept for backward compatibility
    "{{first_name}}":    lambda lead: (lead.get("name") or "").split()[0] if lead.get("name") else "",
    "{{lead_name}}":     lambda lead: lead.get("name") or "",
    "{{phone}}":         lambda lead: lead.get("phone") or "",
}
```

- [ ] **Step 2: Replace `_build_template_components` (lines ~115–130)**

Find the entire function:

```python
def _build_template_components(template_variables: dict, lead: dict) -> list | None:
    """Convert {param_name: value} dict into Meta named-parameter components array."""
    if not template_variables:
        return None
    parameters = [
        {
            "type": "text",
            "parameter_name": k,
            "text": _resolve_value(str(v), lead),
        }
        for k, v in template_variables.items()
        if k != "components"  # skip legacy raw-components key
    ]
    if not parameters:
        return None
    return [{"type": "body", "parameters": parameters}]
```

Replace with:

```python
def _build_template_components(template_variables: dict, lead: dict) -> list | None:
    """Build Meta template components from stored variable mappings.

    Supports:
    - Named params: {param_name: token_or_text, ...}
    - Positional params: {"1": token, "2": token, ...} with __params_type__="positional"
    - Media headers: __header_type__ = IMAGE|VIDEO|DOCUMENT, __header_url__ = url
    Reserved keys starting with __ control behaviour and are excluded from body params.
    Old broadcasts without __params_type__ default to named (backward compat).
    """
    if not template_variables:
        return None

    params_type = template_variables.get("__params_type__", "named")
    header_type = template_variables.get("__header_type__")
    header_url = template_variables.get("__header_url__")

    # Exclude reserved keys and legacy "components" key from body variables
    body_vars = {
        k: v for k, v in template_variables.items()
        if not str(k).startswith("__") and k != "components"
    }

    components: list = []

    # Header component — media types only (TEXT header has no parameters)
    if header_type in ("IMAGE", "VIDEO", "DOCUMENT") and header_url:
        media_key = header_type.lower()
        components.append({
            "type": "header",
            "parameters": [{"type": media_key, media_key: {"link": header_url}}],
        })

    # Body component
    if params_type == "positional":
        # Sort by numeric key (1, 2, 3…); non-numeric keys sort last
        ordered = sorted(
            body_vars.items(),
            key=lambda x: int(x[0]) if str(x[0]).isdigit() else 999,
        )
        parameters = [
            {"type": "text", "text": _resolve_value(str(v), lead)}
            for _, v in ordered
        ]
    else:
        # Named params (default — also handles legacy broadcasts)
        parameters = [
            {
                "type": "text",
                "parameter_name": k,
                "text": _resolve_value(str(v), lead),
            }
            for k, v in body_vars.items()
        ]

    if parameters:
        components.append({"type": "body", "parameters": parameters})

    return components if components else None
```

- [ ] **Step 3: Verify Python syntax**

```bash
cd backend && python -c "import app.broadcast.worker; print('OK')"
```

Expected: `OK` (no import errors).

- [ ] **Step 4: Commit**

```bash
git add backend/app/broadcast/worker.py
git commit -m "feat(worker): suporte a params posicionais, header de mídia e novos tokens de lead"
```

---

## Task 5: Final verification

**Files:** none (manual + build checks)

- [ ] **Step 1: Run frontend type-check**

```bash
cd frontend && npm run type-check 2>&1
```

Expected: exit 0, no errors.

- [ ] **Step 2: Manual test — template com params posicionais**

1. Abrir modal "Novo Disparo"
2. Passo 1: preencher nome + canal → Próximo
3. Passo 2: selecionar `template_utility_oficial_reativacao`
4. Confirmar que o card mostra 3 slots: `{{1}}`, `{{2}}`, `{{3}}`
5. Confirmar que cada slot tem dropdown pré-selecionado (sugestão automática)
6. Confirmar que "Próximo" está **bloqueado** enquanto algum slot estiver em "Texto fixo" com campo vazio
7. Preencher todos os slots → "Próximo" desbloqueia
8. Avançar até Revisão e confirmar que as variáveis aparecem com labels corretos

- [ ] **Step 3: Manual test — template sem variáveis**

1. Selecionar um template sem params (ex: `reativar_atendimento_errado` se não tiver `{{1}}`)
2. Confirmar que "Próximo" está imediatamente disponível (nenhum slot para preencher)

- [ ] **Step 4: Manual test — canGoToStep3 com media header**

1. Se houver um template com IMAGE header disponível no canal:
   - Selecionar o template
   - Confirmar que campo "URL da mídia (image) *" aparece
   - Confirmar que "Próximo" está bloqueado até preencher a URL
   - Preencher URL → desbloqueia

- [ ] **Step 5: Test backward compat — criar disparo e verificar no Supabase**

1. Criar um disparo com `template_utility_oficial_reativacao`, mapear `{{1}}` → Primeiro nome, `{{2}}` → Nome completo, `{{3}}` → Texto fixo "Canastra"
2. Verificar no Supabase → tabela `broadcasts` → coluna `template_variables`:

```json
{
  "__params_type__": "positional",
  "1": "{{primeiro_nome}}",
  "2": "{{nome_completo}}",
  "3": "Canastra"
}
```

3. Iniciar o disparo e confirmar que o lead recebe a mensagem com os valores corretos substituídos

- [ ] **Step 6: Push para master (com autorização do usuário)**

```bash
git push origin master
```

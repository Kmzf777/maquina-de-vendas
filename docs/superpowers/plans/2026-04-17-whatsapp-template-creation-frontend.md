# WhatsApp Template Creation — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar botão "Criar Template" na página de Canais (somente para canais `meta_cloud`) e o modal correspondente para criar templates WhatsApp via backend FastAPI, incluindo o fluxo de divergência de categoria (exibir step de confirmação quando Meta muda a categoria).

**Architecture:** Três novas Next.js API routes proxiam para o FastAPI backend (`POST /create`, `DELETE /cancel`, `POST /confirm`). Um componente modal gerencia o fluxo em dois passos: formulário de criação → passo de revisão de categoria (se `status === pending_category_review`). O botão "Criar Template" aparece apenas na coluna de ações de canais `meta_cloud`.

**Tech Stack:** Next.js 15 App Router, React (hooks), Tailwind CSS (mesma paleta existente), fetch API para proxy ao FastAPI.

---

## Mapa de arquivos

| Arquivo | Ação |
|---|---|
| `frontend/src/app/api/channels/[id]/templates/route.ts` | Modificar — adicionar `POST` handler |
| `frontend/src/app/api/channels/[id]/templates/[templateId]/route.ts` | Criar — `DELETE` handler |
| `frontend/src/app/api/channels/[id]/templates/[templateId]/confirm/route.ts` | Criar — `POST` handler |
| `frontend/src/components/canais/create-template-modal.tsx` | Criar — modal de criação com fluxo de revisão |
| `frontend/src/app/(authenticated)/canais/page.tsx` | Modificar — botão + estado do modal |

---

## Task 1: POST /api/channels/[id]/templates

**Files:**
- Modify: `frontend/src/app/api/channels/[id]/templates/route.ts`

- [ ] **Step 1: Adicionar `POST` handler ao route.ts existente**

Abra `frontend/src/app/api/channels/[id]/templates/route.ts` e adicione após o `export async function GET(...)` existente:

```typescript
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

Certifique-se de que `NextResponse` já está importado no topo do arquivo (já está pelo GET).

- [ ] **Step 2: Commit**

```bash
git add "frontend/src/app/api/channels/[id]/templates/route.ts"
git commit -m "feat: add POST proxy route for template creation"
```

---

## Task 2: DELETE e POST /confirm para template individual

**Files:**
- Create: `frontend/src/app/api/channels/[id]/templates/[templateId]/route.ts`
- Create: `frontend/src/app/api/channels/[id]/templates/[templateId]/confirm/route.ts`

- [ ] **Step 1: Criar `[templateId]/route.ts` com `DELETE`**

```typescript
// frontend/src/app/api/channels/[id]/templates/[templateId]/route.ts
import { NextResponse } from "next/server";

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string; templateId: string }> }
) {
  const { id, templateId } = await params;
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

  const res = await fetch(`${backendUrl}/api/channels/${id}/templates/${templateId}`, {
    method: "DELETE",
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
```

- [ ] **Step 2: Criar `[templateId]/confirm/route.ts` com `POST`**

```typescript
// frontend/src/app/api/channels/[id]/templates/[templateId]/confirm/route.ts
import { NextResponse } from "next/server";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string; templateId: string }> }
) {
  const { id, templateId } = await params;
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

  const res = await fetch(`${backendUrl}/api/channels/${id}/templates/${templateId}/confirm`, {
    method: "POST",
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
```

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/channels/[id]/templates/[templateId]/route.ts" \
        "frontend/src/app/api/channels/[id]/templates/[templateId]/confirm/route.ts"
git commit -m "feat: add DELETE and confirm proxy routes for templates"
```

---

## Task 3: CreateTemplateModal component

**Files:**
- Create: `frontend/src/components/canais/create-template-modal.tsx`

O modal tem dois steps:
- **Step 1 (`form`):** campos name, language, category, body text → submete ao backend
- **Step 2 (`review`):** exibido quando o backend retorna `202` (Meta mudou categoria) → botões Confirmar / Cancelar

- [ ] **Step 1: Criar o componente**

```typescript
// frontend/src/components/canais/create-template-modal.tsx
"use client";

import { useState } from "react";

interface CreateTemplateModalProps {
  channelId: string;
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

type ModalStep = "form" | "review";

const EMPTY_FORM = {
  name: "",
  language: "pt_BR",
  category: "UTILITY" as "UTILITY" | "MARKETING",
  bodyText: "",
};

export function CreateTemplateModal({ channelId, open, onClose, onCreated }: CreateTemplateModalProps) {
  const [step, setStep] = useState<ModalStep>("form");
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stored after 202 response to use in confirm/cancel
  const [pendingTemplateId, setPendingTemplateId] = useState<string | null>(null);
  const [suggestedCategory, setSuggestedCategory] = useState<string | null>(null);

  if (!open) return null;

  const resetAndClose = () => {
    setStep("form");
    setForm(EMPTY_FORM);
    setError(null);
    setPendingTemplateId(null);
    setSuggestedCategory(null);
    onClose();
  };

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.bodyText.trim()) {
      setError("Nome e texto do corpo são obrigatórios.");
      return;
    }
    setSaving(true);
    setError(null);

    const body = {
      name: form.name.trim(),
      language: form.language,
      category: form.category,
      components: [{ type: "BODY", text: form.bodyText.trim() }],
    };

    try {
      const res = await fetch(`/api/channels/${channelId}/templates`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await res.json();

      if (res.status === 201) {
        onCreated();
        resetAndClose();
        return;
      }

      if (res.status === 202) {
        // Category divergence — show review step
        setPendingTemplateId(data.template?.id ?? null);
        setSuggestedCategory(data.suggested_category ?? null);
        setStep("review");
        return;
      }

      setError(data?.detail || data?.error || "Erro ao criar template.");
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSaving(false);
    }
  };

  const handleConfirm = async () => {
    if (!pendingTemplateId) return;
    setSaving(true);
    setError(null);

    try {
      const res = await fetch(`/api/channels/${channelId}/templates/${pendingTemplateId}/confirm`, {
        method: "POST",
      });

      if (res.ok) {
        onCreated();
        resetAndClose();
        return;
      }

      const data = await res.json();
      setError(data?.detail || data?.error || "Erro ao confirmar template.");
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = async () => {
    if (!pendingTemplateId) { resetAndClose(); return; }
    setSaving(true);
    setError(null);

    try {
      await fetch(`/api/channels/${channelId}/templates/${pendingTemplateId}`, {
        method: "DELETE",
      });
    } catch { /* ignore — template will remain in pending_category_review */ }

    setSaving(false);
    resetAndClose();
  };

  return (
    <div
      className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
      onClick={resetAndClose}
    >
      <div
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg max-h-[90vh] overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-[14px] font-normal text-[#111111]">
            {step === "form" ? "Criar Template WhatsApp" : "Revisão de Categoria"}
          </h2>
          <button
            onClick={resetAndClose}
            className="text-[#7b7b78] hover:text-[#111111] text-xl transition-colors"
          >
            &times;
          </button>
        </div>

        {/* Step: form */}
        {step === "form" && (
          <div className="space-y-4">
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Nome do Template
              </label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value.toLowerCase().replace(/\s/g, "_") })}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                placeholder="ex: order_update_v1"
              />
              <p className="text-[11px] text-[#7b7b78] mt-1">Apenas letras minúsculas, números e underscores.</p>
            </div>

            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Idioma
              </label>
              <select
                value={form.language}
                onChange={(e) => setForm({ ...form, language: e.target.value })}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              >
                <option value="pt_BR">Português (Brasil)</option>
                <option value="en_US">English (US)</option>
                <option value="es">Español</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Categoria
              </label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as "UTILITY" | "MARKETING" })}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              >
                <option value="UTILITY">UTILITY — Atualizações transacionais</option>
                <option value="MARKETING">MARKETING — Promoções e ofertas</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Texto do Corpo (BODY)
              </label>
              <textarea
                value={form.bodyText}
                onChange={(e) => setForm({ ...form, bodyText: e.target.value })}
                rows={4}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full resize-none"
                placeholder="Olá {{1}}, seu pedido foi atualizado."
              />
              <p className="text-[11px] text-[#7b7b78] mt-1">Use &#123;&#123;1&#125;&#125;, &#123;&#123;2&#125;&#125;, etc. para variáveis.</p>
            </div>

            {error && (
              <p className="text-[12px] text-[#c41c1c]">{error}</p>
            )}

            <div className="flex justify-end gap-3 mt-2">
              <button
                onClick={resetAndClose}
                className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
              >
                Cancelar
              </button>
              <button
                onClick={handleSubmit}
                disabled={saving || !form.name.trim() || !form.bodyText.trim()}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
              >
                {saving ? "Enviando..." : "Criar Template"}
              </button>
            </div>
          </div>
        )}

        {/* Step: review (category divergence) */}
        {step === "review" && (
          <div className="space-y-4">
            <div className="p-4 bg-[#faf9f6] border border-[#dedbd6] rounded-[8px]">
              <p className="text-[14px] text-[#111111] mb-2">
                A Meta reclassificou seu template.
              </p>
              <p className="text-[14px] text-[#7b7b78]">
                Categoria solicitada: <span className="text-[#111111]">{form.category}</span>
              </p>
              <p className="text-[14px] text-[#7b7b78]">
                Categoria sugerida pela Meta: <span className="text-[#111111] font-medium">{suggestedCategory}</span>
              </p>
              <p className="text-[13px] text-[#7b7b78] mt-3">
                Confirmar aceita a nova categoria. Cancelar descarta o template.
              </p>
            </div>

            {error && (
              <p className="text-[12px] text-[#c41c1c]">{error}</p>
            )}

            <div className="flex justify-end gap-3">
              <button
                onClick={handleCancel}
                disabled={saving}
                className="bg-[#c41c1c]/10 text-[#c41c1c] border border-[#c41c1c]/20 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                {saving ? "..." : "Cancelar Template"}
              </button>
              <button
                onClick={handleConfirm}
                disabled={saving}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
              >
                {saving ? "Confirmando..." : "Confirmar Categoria"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/canais/create-template-modal.tsx
git commit -m "feat: add CreateTemplateModal component with category review step"
```

---

## Task 4: Botão e integração em canais/page.tsx

**Files:**
- Modify: `frontend/src/app/(authenticated)/canais/page.tsx`

- [ ] **Step 1: Adicionar import e estado do modal**

No topo do arquivo, após os imports de `useState`, `useEffect`, `useRef`, `useCallback`, adicione:

```typescript
import { CreateTemplateModal } from "@/components/canais/create-template-modal";
```

Dentro do componente `CanaisPage`, após a linha `const [saving, setSaving] = useState(false);`, adicione:

```typescript
const [templateChannelId, setTemplateChannelId] = useState<string | null>(null);
```

- [ ] **Step 2: Adicionar botão "Criar Template" na coluna de ações**

Dentro de `<td className="px-4 py-3 text-right">` → `<div className="flex items-center justify-end gap-2">`, adicione o botão para canais meta_cloud, antes do botão "Editar":

```tsx
{ch.provider === "meta_cloud" && (
  <button
    onClick={() => setTemplateChannelId(ch.id)}
    className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
  >
    Criar Template
  </button>
)}
```

- [ ] **Step 3: Adicionar o modal no JSX**

Antes do fechamento `</div>` final do componente (após o bloco `{/* QR Code Modal */}`), adicione:

```tsx
{/* Create Template Modal */}
{templateChannelId && (
  <CreateTemplateModal
    channelId={templateChannelId}
    open={true}
    onClose={() => setTemplateChannelId(null)}
    onCreated={() => setTemplateChannelId(null)}
  />
)}
```

- [ ] **Step 4: Verificar TypeScript**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/frontend" && npx tsc --noEmit
```

Esperado: sem erros de tipo.

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/app/(authenticated)/canais/page.tsx"
git commit -m "feat: add Criar Template button and wire CreateTemplateModal in canais page"
```

---

## Verificação manual pós-implementação

1. Acesse a página `/canais`
2. Um canal `meta_cloud` deve exibir o botão **Criar Template** na coluna de ações
3. Clicar no botão abre o modal com os campos: Nome, Idioma, Categoria, Texto do Corpo
4. Submeter com dados válidos:
   - Se o backend retornar `201` → modal fecha, template criado
   - Se o backend retornar `202` → modal exibe o step de revisão com a categoria sugerida pela Meta
5. No step de revisão:
   - "Confirmar Categoria" → chama `/confirm` → modal fecha
   - "Cancelar Template" → chama `DELETE` → modal fecha, template descartado
6. Canais `evolution` **não** exibem o botão "Criar Template"

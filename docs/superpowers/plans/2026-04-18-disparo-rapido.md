# Disparo Rápido — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar botão "Disparo Rápido" na aba /campanhas que envia um template Meta aprovado para um ou mais números diretamente, criando um broadcast no banco e disparando imediatamente.

**Architecture:** Fluxo puramente frontend (Next.js) sem mudanças no backend Python. O modal faz 4 chamadas em sequência: criar broadcast → resolver leads (get-or-create) → associar leads → iniciar disparo. Números de destino são normalizados (sem `+`) e podem ser salvos numa nova tabela `quick_send_phones`.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS v4, Supabase (via `getServiceSupabase()`), TypeScript.

---

## File Map

| Ação | Arquivo |
|------|---------|
| Criar | `backend/migrations/20260418_quick_send_phones.sql` |
| Criar | `frontend/src/app/api/leads/resolve/route.ts` |
| Criar | `frontend/src/app/api/quick-send-phones/route.ts` |
| Criar | `frontend/src/app/api/quick-send-phones/[phone]/route.ts` |
| Criar | `frontend/src/components/campaigns/quick-send-modal.tsx` |
| Modificar | `frontend/src/app/(authenticated)/campanhas/page.tsx` |

---

## Task 1: Migration — tabela `quick_send_phones`

**Files:**
- Create: `backend/migrations/20260418_quick_send_phones.sql`

- [ ] **Step 1: Criar o arquivo de migration**

```sql
-- backend/migrations/20260418_quick_send_phones.sql
CREATE TABLE IF NOT EXISTS quick_send_phones (
  id         uuid primary key default gen_random_uuid(),
  phone      text not null unique,
  label      text,
  created_at timestamptz default now()
);
```

- [ ] **Step 2: Executar no Supabase**

Abrir o Supabase Dashboard → SQL Editor → colar e executar o SQL acima.

Verificar que a tabela aparece em Table Editor com as colunas `id`, `phone`, `label`, `created_at`.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/20260418_quick_send_phones.sql
git commit -m "feat(db): cria tabela quick_send_phones para disparo rápido"
```

---

## Task 2: API Route — `POST /api/leads/resolve`

Get-or-create de lead por phone. Necessário porque `POST /api/leads` retorna 409 sem o `lead_id` quando o número já existe.

**Files:**
- Create: `frontend/src/app/api/leads/resolve/route.ts`

- [ ] **Step 1: Criar o arquivo**

```typescript
// frontend/src/app/api/leads/resolve/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(request: NextRequest) {
  const { phone } = await request.json();

  if (!phone || typeof phone !== "string") {
    return NextResponse.json({ error: "phone é obrigatório" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  const { data: existing } = await supabase
    .from("leads")
    .select("id")
    .eq("phone", phone)
    .maybeSingle();

  if (existing) {
    return NextResponse.json({ id: existing.id, created: false });
  }

  const { data, error } = await supabase
    .from("leads")
    .insert({ phone, status: "imported", stage: "pending" })
    .select("id")
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ id: data.id, created: true }, { status: 201 });
}
```

- [ ] **Step 2: Verificar tipos**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "leads/resolve" || echo "OK"
```

Esperado: nenhum erro relacionado ao arquivo.

- [ ] **Step 3: Testar manualmente**

Com o servidor rodando (`npm run dev`), abrir o terminal e executar:

```bash
curl -X POST http://localhost:3000/api/leads/resolve \
  -H "Content-Type: application/json" \
  -d '{"phone":"5511999000001"}'
```

Primeira chamada: resposta `{"id":"<uuid>","created":true}` com status 201.  
Segunda chamada com mesmo phone: resposta `{"id":"<mesmo-uuid>","created":false}` com status 200.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/api/leads/resolve/route.ts
git commit -m "feat(api): adiciona route leads/resolve para get-or-create por phone"
```

---

## Task 3: API Routes — `quick-send-phones`

**Files:**
- Create: `frontend/src/app/api/quick-send-phones/route.ts`
- Create: `frontend/src/app/api/quick-send-phones/[phone]/route.ts`

- [ ] **Step 1: Criar route GET + POST**

```typescript
// frontend/src/app/api/quick-send-phones/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("quick_send_phones")
    .select("id, phone, label")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const { phone, label } = await request.json();

  if (!phone || typeof phone !== "string") {
    return NextResponse.json({ error: "phone é obrigatório" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("quick_send_phones")
    .insert({ phone, label: label ?? null })
    .select("id, phone, label")
    .single();

  if (error) {
    // Unique constraint violation — phone já salvo
    if (error.code === "23505") {
      return NextResponse.json({ error: "Número já salvo" }, { status: 409 });
    }
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Criar route DELETE**

```typescript
// frontend/src/app/api/quick-send-phones/[phone]/route.ts
import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ phone: string }> }
) {
  const { phone } = await params;
  const supabase = await getServiceSupabase();

  const { error } = await supabase
    .from("quick_send_phones")
    .delete()
    .eq("phone", decodeURIComponent(phone));

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 3: Verificar tipos**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "quick-send-phones" || echo "OK"
```

Esperado: sem erros.

- [ ] **Step 4: Testar manualmente**

```bash
# Salvar um número
curl -X POST http://localhost:3000/api/quick-send-phones \
  -H "Content-Type: application/json" \
  -d '{"phone":"5511988887777"}'
# Esperado: {"id":"<uuid>","phone":"5511988887777","label":null}

# Listar
curl http://localhost:3000/api/quick-send-phones
# Esperado: [{"id":"...","phone":"5511988887777","label":null}]

# Deletar
curl -X DELETE http://localhost:3000/api/quick-send-phones/5511988887777
# Esperado: {"ok":true}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/quick-send-phones/route.ts \
        frontend/src/app/api/quick-send-phones/[phone]/route.ts
git commit -m "feat(api): adiciona routes quick-send-phones (GET, POST, DELETE)"
```

---

## Task 4: Componente `QuickSendModal`

**Files:**
- Create: `frontend/src/components/campaigns/quick-send-modal.tsx`

- [ ] **Step 1: Criar o componente**

```typescript
// frontend/src/components/campaigns/quick-send-modal.tsx
"use client";

import { useState, useEffect } from "react";
import type { Channel } from "@/lib/types";

interface MetaTemplate {
  name: string;
  language: string;
  params: string[];
}

interface SavedPhone {
  id: string;
  phone: string;
  label: string | null;
}

interface QuickSendModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: (count: number) => void;
}

const DYNAMIC_VARS: Record<string, string> = {
  primeiro_nome: "{{first_name}}",
  first_name: "{{first_name}}",
  nome: "{{first_name}}",
  name: "{{first_name}}",
};

function defaultValue(paramName: string): string {
  return DYNAMIC_VARS[paramName.toLowerCase()] ?? "";
}

function normalizePhone(raw: string): string {
  return raw.replace(/\D/g, "");
}

function isValidPhone(normalized: string): boolean {
  return normalized.length >= 12 && normalized.length <= 13;
}

export function QuickSendModal({ open, onClose, onSuccess }: QuickSendModalProps) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState("");
  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<MetaTemplate | null>(null);
  const [templateVarValues, setTemplateVarValues] = useState<Record<string, string>>({});
  const [phones, setPhones] = useState<string[]>([""]);
  const [savedPhones, setSavedPhones] = useState<SavedPhone[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    fetch("/api/channels")
      .then((r) => r.json())
      .then((d) => {
        const metaChannels = (Array.isArray(d) ? d : d.data || []).filter(
          (c: Channel) => c.provider === "meta_cloud" && c.is_active
        );
        setChannels(metaChannels);
      });
    fetch("/api/quick-send-phones")
      .then((r) => r.json())
      .then((d) => setSavedPhones(Array.isArray(d) ? d : []));
  }, [open]);

  useEffect(() => {
    if (!channelId) {
      setTemplates([]);
      setSelectedTemplate(null);
      return;
    }
    setLoadingTemplates(true);
    setSelectedTemplate(null);
    setTemplateVarValues({});
    fetch(`/api/channels/${channelId}/templates`)
      .then((r) => r.json())
      .then((d) => setTemplates(Array.isArray(d) ? d : []))
      .catch(() => setTemplates([]))
      .finally(() => setLoadingTemplates(false));
  }, [channelId]);

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
        defaults[p] = defaultValue(p);
      });
      setTemplateVarValues(defaults);
    }
  };

  const updatePhone = (i: number, val: string) =>
    setPhones((prev) => prev.map((p, idx) => (idx === i ? val : p)));

  const removePhone = (i: number) =>
    setPhones((prev) => prev.filter((_, idx) => idx !== i));

  const addSavedPhone = (phone: string) => {
    const emptyIdx = phones.findIndex((p) => p === "");
    if (phones.includes(phone)) return;
    if (emptyIdx >= 0) {
      updatePhone(emptyIdx, phone);
    } else {
      setPhones((prev) => [...prev, phone]);
    }
  };

  const savePhone = async (raw: string) => {
    const phone = normalizePhone(raw);
    if (!isValidPhone(phone)) return;
    if (savedPhones.some((s) => s.phone === phone)) return;
    const res = await fetch("/api/quick-send-phones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone }),
    });
    if (res.ok) {
      const saved: SavedPhone = await res.json();
      setSavedPhones((prev) => [saved, ...prev]);
    }
  };

  const validPhones = phones
    .map(normalizePhone)
    .filter(isValidPhone)
    .filter((p, i, arr) => arr.indexOf(p) === i);

  const canSend = channelId !== "" && selectedTemplate !== null && validPhones.length > 0;

  const handleSend = async () => {
    if (!selectedTemplate || !canSend) return;
    setSending(true);
    setError(null);

    try {
      const now = new Date();
      const dateStr =
        now.toLocaleDateString("pt-BR") +
        " " +
        now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      const broadcastName = `Disparo Rápido — ${selectedTemplate.name} — ${dateStr}`;

      // 1. Criar broadcast
      const bRes = await fetch("/api/broadcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: broadcastName,
          channel_id: channelId,
          template_name: selectedTemplate.name,
          template_language_code: selectedTemplate.language,
          template_variables: Object.keys(templateVarValues).length
            ? templateVarValues
            : null,
          send_interval_min: 0,
          send_interval_max: 0,
        }),
      });
      if (!bRes.ok) throw new Error("Erro ao criar disparo");
      const broadcast: { id: string } = await bRes.json();

      // 2. Resolver lead_ids
      const leadIds: string[] = [];
      for (const phone of validPhones) {
        const lRes = await fetch("/api/leads/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phone }),
        });
        if (!lRes.ok) throw new Error(`Erro ao resolver lead para ${phone}`);
        const lead: { id: string } = await lRes.json();
        leadIds.push(lead.id);
      }

      // 3. Associar leads
      await fetch(`/api/broadcasts/${broadcast.id}/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lead_ids: leadIds }),
      });

      // 4. Iniciar
      await fetch(`/api/broadcasts/${broadcast.id}/start`, { method: "POST" });

      onSuccess(validPhones.length);
      handleClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado");
    } finally {
      setSending(false);
    }
  };

  const handleClose = () => {
    setChannelId("");
    setTemplates([]);
    setSelectedTemplate(null);
    setTemplateVarValues({});
    setPhones([""]);
    setError(null);
    onClose();
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg max-h-[85vh] overflow-y-auto">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#dedbd6] flex items-center justify-between">
          <h2 className="text-[14px] font-normal text-[#111111]">Disparo Rápido</h2>
          <button
            onClick={handleClose}
            className="text-[#7b7b78] hover:text-[#111111] text-xl transition-colors"
          >
            &times;
          </button>
        </div>

        <div className="p-6 space-y-4">
          {/* Instância */}
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
              Instância
            </label>
            <select
              value={channelId}
              onChange={(e) => setChannelId(e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
            >
              <option value="">Selecionar instância...</option>
              {channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.phone})
                </option>
              ))}
            </select>
          </div>

          {/* Template */}
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
              Template
              {loadingTemplates && (
                <span className="ml-2 text-[#7b7b78] normal-case font-normal">
                  carregando...
                </span>
              )}
            </label>
            {!channelId ? (
              <p className="text-[12px] text-[#7b7b78] italic">
                Selecione uma instância para ver os templates disponíveis
              </p>
            ) : loadingTemplates ? (
              <div className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#7b7b78]">
                Buscando templates...
              </div>
            ) : templates.length === 0 ? (
              <p className="text-[12px] text-[#c41c1c]">
                Nenhum template aprovado encontrado para esta instância
              </p>
            ) : (
              <select
                value={
                  selectedTemplate
                    ? `${selectedTemplate.name}|${selectedTemplate.language}`
                    : ""
                }
                onChange={(e) => handleSelectTemplate(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              >
                <option value="">Selecionar template...</option>
                {templates.map((t) => (
                  <option
                    key={`${t.name}|${t.language}`}
                    value={`${t.name}|${t.language}`}
                  >
                    {t.name} ({t.language})
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Variáveis */}
          {selectedTemplate && selectedTemplate.params.length > 0 && (
            <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 space-y-3">
              <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
                Variáveis do template
              </p>
              {selectedTemplate.params.map((param) => (
                <div key={param}>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                    {param}
                  </label>
                  <input
                    value={templateVarValues[param] ?? ""}
                    onChange={(e) =>
                      setTemplateVarValues((prev) => ({
                        ...prev,
                        [param]: e.target.value,
                      }))
                    }
                    className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                    placeholder={`Valor para ${param}`}
                  />
                </div>
              ))}
            </div>
          )}

          {/* Números de destino */}
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
              Números de Destino
            </label>
            <div className="space-y-2">
              {phones.map((phone, i) => {
                const normalized = normalizePhone(phone);
                const alreadySaved = savedPhones.some((s) => s.phone === normalized);
                return (
                  <div key={i} className="flex gap-2 items-center">
                    <input
                      value={phone}
                      onChange={(e) => updatePhone(i, e.target.value)}
                      placeholder="+5511999999999"
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none flex-1"
                    />
                    <button
                      onClick={() => savePhone(phone)}
                      disabled={!isValidPhone(normalized) || alreadySaved}
                      className="text-[12px] text-[#7b7b78] border border-[#dedbd6] rounded-[4px] px-2 py-1.5 hover:border-[#111111] hover:text-[#111111] disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
                    >
                      {alreadySaved ? "Salvo" : "Salvar"}
                    </button>
                    {phones.length > 1 && (
                      <button
                        onClick={() => removePhone(i)}
                        className="text-[#7b7b78] hover:text-[#c41c1c] transition-colors flex-shrink-0 text-lg leading-none"
                      >
                        &times;
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            <button
              onClick={() => setPhones((prev) => [...prev, ""])}
              className="mt-2 text-[13px] text-[#7b7b78] hover:text-[#111111] transition-colors"
            >
              + Adicionar número
            </button>
          </div>

          {/* Números salvos */}
          {savedPhones.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                Números salvos
              </p>
              <div className="flex flex-wrap gap-2">
                {savedPhones.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => addSavedPhone(s.phone)}
                    className="text-[12px] bg-[#faf9f6] border border-[#dedbd6] rounded-[4px] px-2 py-1 hover:border-[#111111] transition-colors"
                  >
                    {s.phone}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Erro */}
          {error && (
            <p className="text-[13px] text-[#c41c1c] bg-[#c41c1c]/5 border border-[#c41c1c]/20 rounded-[6px] px-3 py-2">
              {error}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#dedbd6] flex justify-end gap-2">
          <button
            onClick={handleClose}
            className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
          >
            Cancelar
          </button>
          <button
            onClick={handleSend}
            disabled={!canSend || sending}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
          >
            {sending ? "Enviando..." : "Enviar →"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "quick-send-modal" || echo "OK"
```

Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/campaigns/quick-send-modal.tsx
git commit -m "feat(ui): cria QuickSendModal para disparo rápido de templates"
```

---

## Task 5: Wiring em `campanhas/page.tsx`

Adiciona o botão, importa o modal e exibe o toast de sucesso.

**Files:**
- Modify: `frontend/src/app/(authenticated)/campanhas/page.tsx`

- [ ] **Step 1: Adicionar import do modal**

No topo do arquivo, adicionar após o import existente de `CreateBroadcastModal`:

```typescript
import { QuickSendModal } from "@/components/campaigns/quick-send-modal";
```

- [ ] **Step 2: Adicionar estados**

Dentro do componente `CampanhasPage`, após o estado `showTemplateModal`:

```typescript
const [showQuickSendModal, setShowQuickSendModal] = useState(false);
const [quickSendToast, setQuickSendToast] = useState<string | null>(null);
```

- [ ] **Step 3: Adicionar handler de sucesso**

Após o `handleCreateCadence`, adicionar:

```typescript
const handleQuickSendSuccess = (count: number) => {
  setQuickSendToast(`Disparo Rápido enviado para ${count} número${count > 1 ? "s" : ""}!`);
  setTimeout(() => setQuickSendToast(null), 3000);
};
```

- [ ] **Step 4: Adicionar o botão no header**

Na `div className="flex gap-2"` do header (onde ficam `+ Disparo`, `+ Cadencia`, `+ Template`), adicionar **antes** do `+ Disparo`:

```tsx
<button
  onClick={() => setShowQuickSendModal(true)}
  className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
>
  + Disparo Rápido
</button>
```

- [ ] **Step 5: Adicionar o modal e o toast no final do JSX**

Logo após o `<CreateBroadcastModal ... />`, adicionar:

```tsx
<QuickSendModal
  open={showQuickSendModal}
  onClose={() => setShowQuickSendModal(false)}
  onSuccess={handleQuickSendSuccess}
/>

{quickSendToast && (
  <div className="fixed bottom-6 right-6 z-50 bg-[#111111] text-white text-[14px] px-4 py-3 rounded-[6px] shadow-lg">
    {quickSendToast}
  </div>
)}
```

- [ ] **Step 6: Verificar build**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Esperado: `✓ Compiled successfully` ou `Route (app)` sem erros.

- [ ] **Step 7: Testar no browser**

1. Abrir `/campanhas`
2. Confirmar que o botão `+ Disparo Rápido` aparece no header
3. Clicar no botão — modal abre
4. Selecionar instância → templates carregam
5. Selecionar template com variáveis → campos aparecem
6. Digitar `+5511999999999` → botão "Salvar" habilita
7. Clicar "Salvar" → botão muda para "Salvo", número aparece nos chips
8. Clicar "Enviar →" → botão muda para "Enviando...", modal fecha, toast verde aparece
9. Ir para aba "Disparos" → broadcast com nome "Disparo Rápido — ..." aparece com status `running` ou `completed`
10. Reabrir modal → chip do número salvo aparece; clicar no chip adiciona à lista

- [ ] **Step 8: Commit final**

```bash
git add frontend/src/app/(authenticated)/campanhas/page.tsx
git commit -m "feat(campanhas): adiciona botão e modal de Disparo Rápido"
```

---

## Task 6: Push para master

- [ ] **Step 1: Verificar que tudo compila**

```bash
cd frontend && npm run build 2>&1 | tail -5
```

Esperado: sem erros de compilação.

- [ ] **Step 2: Push para produção**

```bash
git push origin HEAD:master
```

Esperado: GitHub Actions aciona o deploy.

---

## Self-Review

**Spec coverage:**
- [x] Botão `+ Disparo Rápido` no header → Task 5 Step 4
- [x] Modal único com instância, template, variáveis, números → Task 4
- [x] Normalização de phones (sem `+`) → `normalizePhone()` no modal
- [x] Get-or-create lead por phone → Task 2 (`/api/leads/resolve`)
- [x] Fluxo broadcast: criar → resolver leads → associar → iniciar → Task 4 `handleSend`
- [x] Salvar números no banco → Task 3 + botão "Salvar" no modal
- [x] Chips de números salvos clicáveis → `addSavedPhone` no modal
- [x] Toast de sucesso por 3s → Task 5 Steps 3+5
- [x] Toast de erro inline no modal → `error` state no modal
- [x] Broadcast aparece na aba Disparos → sem código extra (usa fluxo existente)
- [x] Migration da tabela → Task 1

**Placeholders:** Nenhum encontrado.

**Type consistency:** `broadcast.id` (string), `lead.id` (string), `SavedPhone.phone` (string normalizado) — consistente em todos os tasks.

# Broadcast History & Anti-Spam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **IMPORTANT:** Any agent that touches frontend files MUST invoke the `superpowers:frontend-design` skill before writing code.

**Goal:** Exibir histórico de disparos por lead na sidebar e modal; verificar spam de 48h antes de iniciar um disparo, removendo conflitos para um rascunho.

**Architecture:** Três API routes Next.js novas (`GET /api/leads/[id]/broadcasts`, `GET /api/broadcasts/[id]/spam-check`, `POST /api/broadcasts/[id]/resolve-spam`) + um componente reutilizável `LeadBroadcastHistory` + modal de aviso inline em `broadcast-detail.tsx`.

**Tech Stack:** Next.js 15 App Router, Supabase JS v2, TypeScript, Tailwind CSS

---

## File Map

| Ação | Arquivo |
|------|---------|
| Create | `frontend/src/app/api/leads/[id]/broadcasts/route.ts` |
| Create | `frontend/src/app/api/broadcasts/[id]/spam-check/route.ts` |
| Create | `frontend/src/app/api/broadcasts/[id]/resolve-spam/route.ts` |
| Create | `frontend/src/components/leads/lead-broadcast-history.tsx` |
| Modify | `frontend/src/lib/types.ts` |
| Modify | `frontend/src/components/lead-detail-sidebar.tsx` |
| Modify | `frontend/src/components/leads/lead-detail-modal.tsx` |
| Modify | `frontend/src/components/campaigns/broadcast-detail.tsx` |

---

### Task 1: Tipos TypeScript — LeadBroadcastEntry + SpamConflict

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Adicionar interfaces ao final de types.ts**

Abrir `frontend/src/lib/types.ts` e adicionar ao final:

```typescript
export interface LeadBroadcastEntry {
  id: string;
  broadcast_id: string;
  broadcast_name: string;
  broadcast_status: string;
  message_status: string; // pending | sent | delivered | failed
  sent_at: string | null;
  first_replied_at: string | null;
}

export interface SpamConflict {
  lead_id: string;
  lead_name: string | null;
  lead_phone: string;
  last_broadcast_id: string;
  last_broadcast_name: string;
  last_sent_at: string;
}
```

- [ ] **Step 2: Verificar que não há conflito de nomes**

```bash
grep -n "LeadBroadcastEntry\|SpamConflict" frontend/src/lib/types.ts
```

Esperado: 2 declarações de interface, nada mais.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(types): adicionar LeadBroadcastEntry e SpamConflict"
```

---

### Task 2: API — GET /api/leads/[id]/broadcasts

**Files:**
- Create: `frontend/src/app/api/leads/[id]/broadcasts/route.ts`

- [ ] **Step 1: Criar rota**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("broadcast_leads")
    .select(`
      id,
      broadcast_id,
      status,
      sent_at,
      first_replied_at,
      broadcasts!inner(name, status)
    `)
    .eq("lead_id", id)
    .order("sent_at", { ascending: false, nullsFirst: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const result = (data ?? []).map((row: Record<string, unknown>) => {
    const b = row.broadcasts as { name: string; status: string } | null;
    return {
      id: row.id,
      broadcast_id: row.broadcast_id,
      broadcast_name: b?.name ?? "—",
      broadcast_status: b?.status ?? "unknown",
      message_status: row.status,
      sent_at: row.sent_at,
      first_replied_at: row.first_replied_at,
    };
  });

  return NextResponse.json(result);
}
```

- [ ] **Step 2: Testar manualmente**

No terminal:
```bash
curl "http://localhost:3000/api/leads/ALGUM_LEAD_ID/broadcasts"
```

Esperado: array JSON com `broadcast_name`, `message_status`, `sent_at`.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/leads/[id]/broadcasts/route.ts"
git commit -m "feat(api): GET /api/leads/[id]/broadcasts — histórico de disparos por lead"
```

---

### Task 3: API — GET /api/broadcasts/[id]/spam-check

**Files:**
- Create: `frontend/src/app/api/broadcasts/[id]/spam-check/route.ts`

- [ ] **Step 1: Criar rota**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  // Fetch pending leads in this broadcast
  const { data: pendingLeads, error: plErr } = await supabase
    .from("broadcast_leads")
    .select("lead_id")
    .eq("broadcast_id", id)
    .eq("status", "pending");

  if (plErr) {
    return NextResponse.json({ error: plErr.message }, { status: 500 });
  }

  if (!pendingLeads || pendingLeads.length === 0) {
    return NextResponse.json({ conflicts: [] });
  }

  const leadIds = pendingLeads.map((r: { lead_id: string }) => r.lead_id);

  // 48h window
  const cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();

  // Find recent broadcast_leads for these leads in OTHER broadcasts
  const { data: recentSends, error: rsErr } = await supabase
    .from("broadcast_leads")
    .select(`
      lead_id,
      broadcast_id,
      sent_at,
      leads!inner(name, phone),
      broadcasts!inner(name)
    `)
    .in("lead_id", leadIds)
    .neq("broadcast_id", id)
    .in("status", ["sent", "delivered"])
    .gte("sent_at", cutoff)
    .order("sent_at", { ascending: false });

  if (rsErr) {
    return NextResponse.json({ error: rsErr.message }, { status: 500 });
  }

  // Deduplicate: keep most recent conflict per lead_id
  const seen = new Set<string>();
  const conflicts = [];
  for (const row of (recentSends ?? [])) {
    if (seen.has(row.lead_id)) continue;
    seen.add(row.lead_id);
    const lead = row.leads as { name: string | null; phone: string } | null;
    const broadcast = row.broadcasts as { name: string } | null;
    conflicts.push({
      lead_id: row.lead_id,
      lead_name: lead?.name ?? null,
      lead_phone: lead?.phone ?? "",
      last_broadcast_id: row.broadcast_id,
      last_broadcast_name: broadcast?.name ?? "—",
      last_sent_at: row.sent_at,
    });
  }

  return NextResponse.json({ conflicts });
}
```

- [ ] **Step 2: Testar manualmente**

```bash
curl "http://localhost:3000/api/broadcasts/ALGUM_BROADCAST_ID/spam-check"
```

Esperado: `{ "conflicts": [] }` para disparo sem conflitos. Para testar com conflitos, criar um broadcast draft com leads que já foram disparados nas últimas 48h.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/broadcasts/[id]/spam-check/route.ts"
git commit -m "feat(api): GET /api/broadcasts/[id]/spam-check — verifica spam 48h"
```

---

### Task 4: API — POST /api/broadcasts/[id]/resolve-spam

**Files:**
- Create: `frontend/src/app/api/broadcasts/[id]/resolve-spam/route.ts`

- [ ] **Step 1: Criar rota**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { conflict_lead_ids }: { conflict_lead_ids: string[] } = await request.json();

  if (!conflict_lead_ids || conflict_lead_ids.length === 0) {
    return NextResponse.json({ error: "conflict_lead_ids vazio" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  // 1. Fetch original broadcast for copying fields
  const { data: orig, error: origErr } = await supabase
    .from("broadcasts")
    .select("*")
    .eq("id", id)
    .single();

  if (origErr || !orig) {
    return NextResponse.json({ error: "Broadcast não encontrado" }, { status: 404 });
  }

  // 2. Create new draft broadcast
  const { data: newBroadcast, error: createErr } = await supabase
    .from("broadcasts")
    .insert({
      name: `Rascunho - ${orig.name}`,
      channel_id: orig.channel_id,
      template_name: orig.template_name,
      template_language_code: orig.template_language_code,
      template_preset_id: orig.template_preset_id,
      template_variables: orig.template_variables,
      send_interval_min: orig.send_interval_min,
      send_interval_max: orig.send_interval_max,
      cadence_id: orig.cadence_id,
      agent_profile_id: orig.agent_profile_id,
      move_to_stage_id: orig.move_to_stage_id,
      env_tag: orig.env_tag,
      status: "draft",
      scheduled_at: null,
      total_leads: conflict_lead_ids.length,
    })
    .select("id, name")
    .single();

  if (createErr || !newBroadcast) {
    return NextResponse.json({ error: "Falha ao criar rascunho" }, { status: 500 });
  }

  // 3. Remove conflicting leads from original broadcast
  const { error: deleteErr } = await supabase
    .from("broadcast_leads")
    .delete()
    .eq("broadcast_id", id)
    .in("lead_id", conflict_lead_ids);

  if (deleteErr) {
    return NextResponse.json({ error: "Falha ao remover leads" }, { status: 500 });
  }

  // 4. Update total_leads count on original broadcast
  const { count } = await supabase
    .from("broadcast_leads")
    .select("id", { count: "exact", head: true })
    .eq("broadcast_id", id);

  await supabase
    .from("broadcasts")
    .update({ total_leads: count ?? 0 })
    .eq("id", id);

  // 5. Insert conflict leads into new draft broadcast
  const inserts = conflict_lead_ids.map((lead_id) => ({
    broadcast_id: newBroadcast.id,
    lead_id,
    status: "pending",
  }));

  const { error: insertErr } = await supabase
    .from("broadcast_leads")
    .insert(inserts);

  if (insertErr) {
    return NextResponse.json({ error: "Falha ao adicionar leads ao rascunho" }, { status: 500 });
  }

  return NextResponse.json({
    new_broadcast_id: newBroadcast.id,
    new_broadcast_name: newBroadcast.name,
    removed_count: conflict_lead_ids.length,
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add "frontend/src/app/api/broadcasts/[id]/resolve-spam/route.ts"
git commit -m "feat(api): POST /api/broadcasts/[id]/resolve-spam — move conflitos para rascunho"
```

---

### Task 5: Componente LeadBroadcastHistory

**Files:**
- Create: `frontend/src/components/leads/lead-broadcast-history.tsx`

**IMPORTANT:** Invoke `superpowers:frontend-design` skill before writing this file.

- [ ] **Step 1: Criar componente**

```tsx
"use client";

import { useState, useEffect } from "react";
import type { LeadBroadcastEntry } from "@/lib/types";

interface LeadBroadcastHistoryProps {
  leadId: string;
}

const messageStatusStyles: Record<string, string> = {
  pending: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
  sent: "bg-[#65b5ff]/10 text-[#65b5ff] border-[#65b5ff]/20",
  delivered: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
  failed: "bg-[#c41c1c]/10 text-[#c41c1c] border-[#c41c1c]/20",
};

const messageStatusLabels: Record<string, string> = {
  pending: "Pendente",
  sent: "Enviado",
  delivered: "Entregue",
  failed: "Falhou",
};

export function LeadBroadcastHistory({ leadId }: LeadBroadcastHistoryProps) {
  const [entries, setEntries] = useState<LeadBroadcastEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`/api/leads/${leadId}/broadcasts`)
      .then((r) => r.json())
      .then((data) => {
        setEntries(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [leadId]);

  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1].map((i) => (
          <div key={i} className="h-10 rounded-[4px] bg-[#f0ede8] animate-pulse" />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <p className="text-[12px] text-[#7b7b78]">Nenhum disparo recebido</p>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map((entry) => (
        <div
          key={entry.id}
          className="flex items-center justify-between py-2 border-b border-[#f0ede8] last:border-0"
        >
          <div className="min-w-0 flex-1 mr-3">
            <p className="text-[13px] text-[#111111] truncate">{entry.broadcast_name}</p>
            {entry.sent_at && (
              <p className="text-[11px] text-[#7b7b78]">
                {new Date(entry.sent_at).toLocaleString("pt-BR", {
                  day: "2-digit",
                  month: "2-digit",
                  year: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <span
              className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-1.5 py-0.5 rounded-[4px] border ${
                messageStatusStyles[entry.message_status] ?? messageStatusStyles.pending
              }`}
            >
              {messageStatusLabels[entry.message_status] ?? entry.message_status}
            </span>
            {entry.first_replied_at && (
              <span className="inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-1.5 py-0.5 rounded-[4px] border bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20">
                Respondeu
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/leads/lead-broadcast-history.tsx
git commit -m "feat(ui): componente LeadBroadcastHistory"
```

---

### Task 6: Integrar LeadBroadcastHistory na Sidebar

**Files:**
- Modify: `frontend/src/components/lead-detail-sidebar.tsx`

**IMPORTANT:** Invoke `superpowers:frontend-design` skill before writing code.

- [ ] **Step 1: Ler arquivo completo**

Ler `frontend/src/components/lead-detail-sidebar.tsx` para entender a estrutura atual antes de modificar.

- [ ] **Step 2: Adicionar import**

No topo do arquivo, após os imports existentes:
```typescript
import { LeadBroadcastHistory } from "./leads/lead-broadcast-history";
```

- [ ] **Step 3: Adicionar seção de disparos**

Após o bloco de deals (buscar pelo texto "leadDeals" ou a seção de Oportunidades), adicionar nova seção:

```tsx
{/* Disparos recebidos */}
<div className="px-4 py-3 border-t border-[#dedbd6]">
  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
    Disparos Recebidos
  </p>
  <LeadBroadcastHistory leadId={lead.id} />
</div>
```

- [ ] **Step 4: Verificar que não há erros de TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Esperado: sem erros relacionados a `lead-detail-sidebar.tsx`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/lead-detail-sidebar.tsx
git commit -m "feat(sidebar): seção de disparos recebidos no sidebar do lead"
```

---

### Task 7: Integrar LeadBroadcastHistory no Modal

**Files:**
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx`

**IMPORTANT:** Invoke `superpowers:frontend-design` skill before writing code.

- [ ] **Step 1: Ler arquivo completo**

Ler `frontend/src/components/leads/lead-detail-modal.tsx` para localizar a aba "campanhas" e onde cadências são exibidas.

- [ ] **Step 2: Adicionar import**

No topo do arquivo, após os imports existentes:
```typescript
import { LeadBroadcastHistory } from "./lead-broadcast-history";
```

- [ ] **Step 3: Adicionar seção na aba "campanhas"**

Na aba "campanhas" (`activeTab === "campanhas"`), após o bloco de cadências (buscar pela string `cadence_enrollments` ou pelo texto "Cadências"), adicionar:

```tsx
{/* Disparos */}
<div className="mt-6">
  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">
    Disparos Recebidos
  </p>
  <LeadBroadcastHistory leadId={lead.id} />
</div>
```

- [ ] **Step 4: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/leads/lead-detail-modal.tsx
git commit -m "feat(modal): seção de disparos recebidos na aba Campanhas do modal"
```

---

### Task 8: Anti-Spam Modal + handleStart em broadcast-detail.tsx

**Files:**
- Modify: `frontend/src/components/campaigns/broadcast-detail.tsx`

**IMPORTANT:** Invoke `superpowers:frontend-design` skill before writing code.

- [ ] **Step 1: Ler o arquivo completo**

Ler `frontend/src/components/campaigns/broadcast-detail.tsx` completo para entender estado atual, especialmente `handleStart` e o bloco de imports/estados.

- [ ] **Step 2: Adicionar novos estados no componente**

Após a declaração de `const [replyMetrics, ...]`, adicionar:
```typescript
import type { SpamConflict } from "@/lib/types";
// (adicionar SpamConflict ao import existente de types.ts)

const [spamConflicts, setSpamConflicts] = useState<SpamConflict[]>([]);
const [showSpamModal, setShowSpamModal] = useState(false);
const [confirmLoading, setConfirmLoading] = useState(false);
```

- [ ] **Step 3: Reescrever handleStart com spam check**

Substituir a função `handleStart` existente pela versão com spam check:

```typescript
const handleStart = async () => {
  if (!broadcast || actionLoading) return;
  setActionLoading(true);
  try {
    const spamRes = await fetch(`/api/broadcasts/${broadcastId}/spam-check`);
    const spamData = await spamRes.json();
    const conflicts: SpamConflict[] = spamData.conflicts ?? [];

    if (conflicts.length > 0) {
      setSpamConflicts(conflicts);
      setShowSpamModal(true);
      setActionLoading(false);
      return;
    }

    await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
    setBroadcast({ ...broadcast, status: "running" });
  } finally {
    setActionLoading(false);
  }
};
```

- [ ] **Step 4: Adicionar handleResolveSpam**

Após `handleStart`, adicionar:

```typescript
const handleResolveSpam = async () => {
  if (!broadcast || confirmLoading) return;
  setConfirmLoading(true);
  try {
    const conflictLeadIds = [...new Set(spamConflicts.map((c) => c.lead_id))];
    const resolveRes = await fetch(`/api/broadcasts/${broadcastId}/resolve-spam`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conflict_lead_ids: conflictLeadIds }),
    });
    const resolveData = await resolveRes.json();

    await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });

    setShowSpamModal(false);
    setSpamConflicts([]);
    setBroadcast({ ...broadcast, status: "running" });
    alert(`${resolveData.removed_count} lead(s) movidos para rascunho "${resolveData.new_broadcast_name}"`);
  } finally {
    setConfirmLoading(false);
    setActionLoading(false);
  }
};
```

- [ ] **Step 5: Adicionar SpamWarningModal no JSX**

Antes do `return` final, garantir que o componente importa SpamConflict do types (atualizar import existente). No final do JSX, antes do `</div>` de fechamento do componente principal, adicionar:

```tsx
{/* Spam Warning Modal */}
{showSpamModal && (
  <div
    className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
    onClick={() => { setShowSpamModal(false); setSpamConflicts([]); }}
  >
    <div
      className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[600px] max-h-[80vh] overflow-hidden flex flex-col"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="px-6 py-5 border-b border-[#dedbd6]">
        <h2 className="text-[20px] font-normal text-[#111111]" style={{ letterSpacing: "-0.4px" }}>
          Leads disparados recentemente
        </h2>
        <p className="text-[13px] text-[#7b7b78] mt-1">
          {spamConflicts.length} lead(s) abaixo receberam um disparo nas últimas 48h.
          Eles serão removidos deste disparo e adicionados a um novo rascunho.
        </p>
      </div>

      <div className="overflow-auto flex-1 px-6 py-4">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] border-b border-[#dedbd6]">
              <th className="text-left pb-2 font-normal">Nome</th>
              <th className="text-left pb-2 font-normal">Telefone</th>
              <th className="text-left pb-2 font-normal">Último Disparo</th>
              <th className="text-left pb-2 font-normal">Enviado em</th>
            </tr>
          </thead>
          <tbody>
            {spamConflicts.map((c) => (
              <tr key={c.lead_id} className="border-b border-[#f0ede8]">
                <td className="py-2 pr-3 text-[#111111]">{c.lead_name ?? "—"}</td>
                <td className="py-2 pr-3 text-[#7b7b78]">{c.lead_phone}</td>
                <td className="py-2 pr-3 text-[#111111] max-w-[160px] truncate">{c.last_broadcast_name}</td>
                <td className="py-2 text-[#7b7b78] whitespace-nowrap">
                  {new Date(c.last_sent_at).toLocaleString("pt-BR", {
                    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="px-6 py-4 border-t border-[#dedbd6] flex justify-end gap-2">
        <button
          onClick={() => { setShowSpamModal(false); setSpamConflicts([]); }}
          disabled={confirmLoading}
          className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
        >
          Cancelar
        </button>
        <button
          onClick={handleResolveSpam}
          disabled={confirmLoading}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
        >
          {confirmLoading ? "Processando..." : "Remover e Disparar"}
        </button>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 6: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Esperado: sem erros.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/campaigns/broadcast-detail.tsx
git commit -m "feat(broadcast): verificação anti-spam 48h antes de iniciar disparo"
```

---

## Após Todos os Tasks

1. Rodar `npx tsc --noEmit` na pasta `frontend` — deve passar sem erros
2. Testar manualmente no dev:
   - Abrir um lead e verificar a seção "Disparos Recebidos" na sidebar
   - Abrir o modal do lead na aba "Campanhas" e verificar a seção de disparos
   - Criar um broadcast draft com leads que foram disparados nas últimas 48h e tentar iniciar — deve aparecer o modal anti-spam
3. Avisar o usuário para testar no dev antes de autorizar o push para master

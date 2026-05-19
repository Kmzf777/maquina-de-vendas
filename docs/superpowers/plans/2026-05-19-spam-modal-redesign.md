# Spam Modal Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Any agent touching the frontend MUST use the superpowers:frontend-design skill.

**Goal:** Redesign the spam warning modal to support per-lead checkbox selection with three actions: remove selected, create new draft with selected, or dispatch ignoring conflicts.

**Architecture:** Two independent changes — a new Next.js API route (`remove-leads`) and a modal redesign inside `broadcast-detail.tsx`. The modal redesign replaces one handler and one state var with three handlers and two state vars, then replaces the modal JSX entirely.

**Tech Stack:** Next.js 15 App Router, TypeScript, Supabase JS v2, Tailwind CSS (inline style tokens).

---

## Task 1: Create `POST /api/broadcasts/[id]/remove-leads` route

**Files:**
- Create: `frontend/src/app/api/broadcasts/[id]/remove-leads/route.ts`

**Context:** This route permanently removes specific leads (by `lead_id`) from a broadcast's `broadcast_leads` table and recounts `total_leads` on the parent broadcast. It follows the exact same pattern as the existing `resolve-spam` route in the same directory — use that as reference for Supabase client, error handling, and response shape.

- [ ] **Step 1: Create the route file**

```typescript
// frontend/src/app/api/broadcasts/[id]/remove-leads/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const body = await request.json();
    const lead_ids: string[] = body.lead_ids ?? [];

    if (!lead_ids.length) {
      return NextResponse.json({ error: "lead_ids vazio" }, { status: 400 });
    }

    const supabase = await getServiceSupabase();

    // Verify broadcast exists
    const { data: broadcast, error: broadcastErr } = await supabase
      .from("broadcasts")
      .select("id")
      .eq("id", id)
      .single();

    if (broadcastErr || !broadcast) {
      return NextResponse.json({ error: "Broadcast não encontrado" }, { status: 404 });
    }

    // Delete selected leads
    const { error: deleteErr } = await supabase
      .from("broadcast_leads")
      .delete()
      .eq("broadcast_id", id)
      .in("lead_id", lead_ids);

    if (deleteErr) {
      return NextResponse.json({ error: deleteErr.message }, { status: 500 });
    }

    // Recount remaining leads
    const { count } = await supabase
      .from("broadcast_leads")
      .select("id", { count: "exact", head: true })
      .eq("broadcast_id", id);

    // Update total_leads on broadcast
    await supabase
      .from("broadcasts")
      .update({ total_leads: count ?? 0 })
      .eq("id", id);

    return NextResponse.json({
      removed_count: lead_ids.length,
      new_total: count ?? 0,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
```

- [ ] **Step 2: Type-check**

```
cd frontend
npm run type-check
```

Expected: no errors related to the new file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/broadcasts/[id]/remove-leads/route.ts
git commit -m "feat(spam-modal): rota POST remove-leads para remover leads do broadcast"
```

---

## Task 2: Redesign spam modal in `broadcast-detail.tsx`

**Files:**
- Modify: `frontend/src/components/campaigns/broadcast-detail.tsx`

**Context:** The file is 575 lines. The spam modal state and logic currently lives at lines 54–121 (`confirmLoading`, `handleResolveSpam`). The modal JSX is at lines 506–571. This task replaces those sections entirely. Do NOT touch any other part of the file (metrics cards, lead table, page header, pause/delete handlers).

The existing `SpamConflict` type imported from `@/lib/types` has: `{ lead_id: string; lead_name: string | null; lead_phone: string; last_broadcast_id: string; last_broadcast_name: string; last_sent_at: string }`.

**IMPORTANT:** Any agent implementing this task MUST invoke the `superpowers:frontend-design` skill before writing any code.

- [ ] **Step 1: Replace state declarations and add new ones**

Find these lines (currently ~54–56):
```typescript
const [spamConflicts, setSpamConflicts] = useState<SpamConflict[]>([]);
const [showSpamModal, setShowSpamModal] = useState(false);
const [confirmLoading, setConfirmLoading] = useState(false);
```

Replace with:
```typescript
const [spamConflicts, setSpamConflicts] = useState<SpamConflict[]>([]);
const [showSpamModal, setShowSpamModal] = useState(false);
const [selectedConflictIds, setSelectedConflictIds] = useState<Set<string>>(new Set());
const [modalActionLoading, setModalActionLoading] = useState(false);
```

- [ ] **Step 2: Update `handleStart` to pre-select all conflicts on modal open**

Find (currently ~85–90):
```typescript
      if (conflicts.length > 0) {
        setSpamConflicts(conflicts);
        setShowSpamModal(true);
        setActionLoading(false);
        return;
      }
```

Replace with:
```typescript
      if (conflicts.length > 0) {
        setSpamConflicts(conflicts);
        setSelectedConflictIds(new Set(conflicts.map((c) => c.lead_id)));
        setShowSpamModal(true);
        setActionLoading(false);
        return;
      }
```

- [ ] **Step 3: Replace `handleResolveSpam` with three new handlers**

Remove the entire `handleResolveSpam` function (currently lines ~99–121) and replace with:

```typescript
  const handleRemoveSelected = async () => {
    if (!broadcast || modalActionLoading || selectedConflictIds.size === 0) return;
    setModalActionLoading(true);
    try {
      const res = await fetch(`/api/broadcasts/${broadcastId}/remove-leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lead_ids: [...selectedConflictIds] }),
      });
      if (!res.ok) {
        const data = await res.json();
        alert(`Erro ao remover leads: ${data.error}`);
        return;
      }
      const startRes = await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
      setShowSpamModal(false);
      setSpamConflicts([]);
      setSelectedConflictIds(new Set());
      if (startRes.ok) {
        setBroadcast({ ...broadcast, status: "running" });
      }
    } finally {
      setModalActionLoading(false);
      setActionLoading(false);
    }
  };

  const handleCreateDraftWithSelected = async () => {
    if (!broadcast || modalActionLoading || selectedConflictIds.size === 0) return;
    setModalActionLoading(true);
    try {
      const resolveRes = await fetch(`/api/broadcasts/${broadcastId}/resolve-spam`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conflict_lead_ids: [...selectedConflictIds] }),
      });
      if (!resolveRes.ok) {
        const data = await resolveRes.json();
        alert(`Erro: ${data.error}`);
        return;
      }
      const resolveData = await resolveRes.json();
      const startRes = await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
      setShowSpamModal(false);
      setSpamConflicts([]);
      setSelectedConflictIds(new Set());
      if (startRes.ok) {
        setBroadcast({ ...broadcast, status: "running" });
      }
      alert(`${resolveData.removed_count} lead(s) movidos para o rascunho "${resolveData.new_broadcast_name}"`);
    } finally {
      setModalActionLoading(false);
      setActionLoading(false);
    }
  };

  const handleDispatchAnyway = async () => {
    if (!broadcast || modalActionLoading) return;
    setModalActionLoading(true);
    try {
      await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
      setShowSpamModal(false);
      setSpamConflicts([]);
      setSelectedConflictIds(new Set());
      setBroadcast({ ...broadcast, status: "running" });
    } finally {
      setModalActionLoading(false);
      setActionLoading(false);
    }
  };
```

- [ ] **Step 4: Replace the modal JSX block**

Find the entire `{/* Spam Warning Modal */}` block (currently lines ~506–571) and replace with:

```tsx
      {/* Spam Warning Modal */}
      {showSpamModal && (
        <div
          className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
          onClick={() => {
            setShowSpamModal(false);
            setSpamConflicts([]);
            setSelectedConflictIds(new Set());
          }}
        >
          <div
            className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[640px] max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="px-6 py-5 border-b border-[#dedbd6]">
              <h2
                className="text-[20px] font-normal text-[#111111]"
                style={{ letterSpacing: "-0.4px" }}
              >
                Leads disparados recentemente
              </h2>
              <p className="text-[13px] text-[#7b7b78] mt-1">
                {spamConflicts.length} lead(s) abaixo receberam um disparo nas últimas 48h.
              </p>
            </div>

            {/* Contextual toolbar — visible only when ≥1 lead selected */}
            {selectedConflictIds.size > 0 && (
              <div className="px-6 py-3 border-b border-[#dedbd6] bg-[#faf9f6] flex items-center gap-3">
                <span className="text-[13px] text-[#7b7b78] flex-1">
                  {selectedConflictIds.size} selecionado(s)
                </span>
                <button
                  onClick={handleRemoveSelected}
                  disabled={modalActionLoading}
                  className="border border-[#c41c1c]/40 text-[#c41c1c] px-[12px] py-1.5 rounded-[4px] text-[13px] hover:bg-[#c41c1c]/5 disabled:opacity-50 transition-colors"
                >
                  {modalActionLoading ? "Processando..." : "Remover selecionados"}
                </button>
                <button
                  onClick={handleCreateDraftWithSelected}
                  disabled={modalActionLoading}
                  className="bg-[#111111] text-white px-[12px] py-1.5 rounded-[4px] text-[13px] hover:bg-[#333333] disabled:opacity-50 transition-colors"
                >
                  {modalActionLoading ? "Processando..." : "Criar novo disparo com selecionados"}
                </button>
              </div>
            )}

            {/* Table */}
            <div className="overflow-auto flex-1">
              <table className="w-full text-[13px]">
                <thead className="sticky top-0 bg-white border-b border-[#dedbd6]">
                  <tr className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
                    <th className="text-left pl-6 pr-3 py-3 font-normal w-10">
                      <input
                        type="checkbox"
                        checked={
                          spamConflicts.length > 0 &&
                          selectedConflictIds.size === spamConflicts.length
                        }
                        onChange={() => {
                          if (selectedConflictIds.size === spamConflicts.length) {
                            setSelectedConflictIds(new Set());
                          } else {
                            setSelectedConflictIds(
                              new Set(spamConflicts.map((c) => c.lead_id))
                            );
                          }
                        }}
                        className="cursor-pointer"
                      />
                    </th>
                    <th className="text-left pr-3 py-3 font-normal">Nome</th>
                    <th className="text-left pr-3 py-3 font-normal">Telefone</th>
                    <th className="text-left pr-3 py-3 font-normal">Último Disparo</th>
                    <th className="text-left pr-6 py-3 font-normal">Enviado em</th>
                  </tr>
                </thead>
                <tbody>
                  {spamConflicts.map((c) => (
                    <tr
                      key={c.lead_id}
                      className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6] transition-colors"
                    >
                      <td className="pl-6 pr-3 py-2.5">
                        <input
                          type="checkbox"
                          checked={selectedConflictIds.has(c.lead_id)}
                          onChange={() => {
                            setSelectedConflictIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(c.lead_id)) next.delete(c.lead_id);
                              else next.add(c.lead_id);
                              return next;
                            });
                          }}
                          className="cursor-pointer"
                        />
                      </td>
                      <td className="pr-3 py-2.5 text-[#111111]">{c.lead_name ?? "—"}</td>
                      <td className="pr-3 py-2.5 text-[#7b7b78] font-mono text-[12px]">
                        {c.lead_phone}
                      </td>
                      <td className="pr-3 py-2.5 text-[#111111] max-w-[160px] truncate">
                        {c.last_broadcast_name}
                      </td>
                      <td className="pr-6 py-2.5 text-[#7b7b78] whitespace-nowrap">
                        {new Date(c.last_sent_at).toLocaleString("pt-BR", {
                          day: "2-digit",
                          month: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-[#dedbd6] flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowSpamModal(false);
                  setSpamConflicts([]);
                  setSelectedConflictIds(new Set());
                }}
                disabled={modalActionLoading}
                className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] hover:border-[#111111] transition-colors disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                onClick={handleDispatchAnyway}
                disabled={modalActionLoading}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] hover:bg-[#333333] disabled:opacity-50 transition-colors"
              >
                {modalActionLoading ? "Processando..." : "Disparar mesmo assim"}
              </button>
            </div>
          </div>
        </div>
      )}
```

- [ ] **Step 5: Type-check**

```
cd frontend
npm run type-check
```

Expected: no errors. If TypeScript complains about `Set` mutability, add `as const` or use the functional updater pattern already shown in Step 3 (`setSelectedConflictIds((prev) => { const next = new Set(prev); ... return next; })`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/campaigns/broadcast-detail.tsx
git commit -m "feat(spam-modal): redesign com checkboxes, toolbar contextual e 3 ações"
```

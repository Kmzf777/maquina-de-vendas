# Cadence Visibility (Tier A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give per-lead visibility of the multi-touch cadence (Feature 3): a read endpoint for `follow_up_jobs`, a "Cadência" mini-timeline in the lead's contact panel, and a distinct badge on follow-up message bubbles.

**Architecture:** Backend adds a read-only `GET /api/leads/{id}/followups` (simple SELECT, no migration). Frontend adds a BFF route reading `follow_up_jobs` directly from Supabase (mirrors the existing `/api/leads/[id]/deals` pattern), a self-contained `CadenceTimeline` component rendered in the Perfil tab, and a `followup → "Cadência"` case in the message-bubble sender badge (extracted to a tested pure helper).

**Tech Stack:** FastAPI + supabase-py + pytest (backend); Next.js App Router BFF + React + TailwindCSS + vitest (frontend).

## Global Constraints

- Tier A ONLY. Do NOT touch `/campanhas`, the automation engine, realtime/Supabase subscriptions, or persist new metadata. Read-only visibility.
- No DB migration. `follow_up_jobs` already has: `id, conversation_id, lead_id, channel_id, sequence, fire_at, status, cancel_reason, sent_at, env_tag, created_at, job_type, metadata (jsonb)`.
- The endpoint exposes exactly: `sequence, job_type, status, fire_at, sent_at, cancel_reason, objetivo` (objetivo = `metadata.objetivo`).
- Touch modality is DERIVED from `(status, cancel_reason)` — no schema change:
  - `pending` → "Agendado"
  - `sent` → "Texto enviado"
  - `awaiting_reopen` → "Template enviado"
  - `cancelled` + `cancel_reason == "reopen_context_refreshed"` → "Contexto atualizado"
  - `cancelled` (other reason) → "Cancelado" (+ reason)
- Objective slug → label: `reengajar`→"Reengajar", `reforco_valor`→"Reforço de valor", `prova_social`→"Prova social", `ultima_chamada`→"Última chamada".
- Only cadence/standard follow-up jobs are relevant; the timeline shows all `follow_up_jobs` rows of the lead ordered by `fire_at` asc, but other job_types (handoff_rescue/lp_welcome/ai_*) are labeled by their generic state too (no special-casing beyond the table above).
- Follow existing visual style (the project's Tailwind tokens, e.g. `#7b7b78`, `#dedbd6`, `#111111`, `#ff5600`); keep components small.

---

### Task 1: Backend read endpoint `GET /api/leads/{id}/followups`

**Files:**
- Modify: `backend/app/leads/router.py` (add a route after `get_lead_messages`, ~line 55)
- Test: `backend/tests/test_lead_followups_endpoint.py` (create)

**Interfaces:**
- Produces: `GET /api/leads/{lead_id}/followups` → `{"data": [ {sequence, job_type, status, fire_at, sent_at, cancel_reason, objetivo} ... ]}`, ordered by `fire_at` asc. `objetivo` is flattened from `metadata.objetivo` (None if absent).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_lead_followups_endpoint.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class _Resp:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, rows): self._rows = rows
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def order(self, *a, **k): return self
    def execute(self): return _Resp(self._rows)


class _SB:
    def __init__(self, rows): self._rows = rows
    def table(self, name): return _Query(self._rows)


def test_followups_endpoint_flattens_objetivo_and_selects_fields():
    rows = [
        {"sequence": 1, "job_type": None, "status": "sent",
         "fire_at": "2026-06-29T12:00:00+00:00", "sent_at": "2026-06-29T12:00:01+00:00",
         "cancel_reason": None, "metadata": {"objetivo": "reengajar", "objective_prompt": "x"}},
        {"sequence": 2, "job_type": None, "status": "cancelled",
         "fire_at": "2026-06-30T12:00:00+00:00", "sent_at": None,
         "cancel_reason": "reopen_context_refreshed", "metadata": {"objetivo": "reforco_valor"}},
        {"sequence": 3, "job_type": None, "status": "pending",
         "fire_at": "2026-07-02T12:00:00+00:00", "sent_at": None,
         "cancel_reason": None, "metadata": None},
    ]
    with patch("app.leads.router.get_supabase", return_value=_SB(rows)):
        r = client.get("/api/leads/lead-1/followups")
    assert r.status_code == 200
    data = r.json()["data"]
    assert [d["sequence"] for d in data] == [1, 2, 3]
    assert data[0]["objetivo"] == "reengajar"
    assert data[1]["objetivo"] == "reforco_valor"
    assert data[1]["cancel_reason"] == "reopen_context_refreshed"
    assert data[2]["objetivo"] is None
    # objective_prompt (heavy text) must NOT leak through
    assert "objective_prompt" not in data[0]
    assert "metadata" not in data[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_lead_followups_endpoint.py -q`
Expected: FAIL — 404 (route not defined) → assertion on status_code 200 fails.

- [ ] **Step 3: Add the route**

In `backend/app/leads/router.py`, after `get_lead_messages` (~line 55):

```python
@router.get("/{lead_id}/followups")
async def get_lead_followups(lead_id: str):
    """Read-only: cadence/follow-up jobs of a lead for the visibility timeline.

    Flattens metadata.objetivo and omits the heavy objective_prompt. Ordered by fire_at asc.
    """
    sb = get_supabase()
    result = (
        sb.table("follow_up_jobs")
        .select("sequence, job_type, status, fire_at, sent_at, cancel_reason, metadata")
        .eq("lead_id", lead_id)
        .order("fire_at", desc=False)
        .execute()
    )
    rows = []
    for j in (result.data or []):
        md = j.get("metadata") or {}
        rows.append({
            "sequence": j.get("sequence"),
            "job_type": j.get("job_type"),
            "status": j.get("status"),
            "fire_at": j.get("fire_at"),
            "sent_at": j.get("sent_at"),
            "cancel_reason": j.get("cancel_reason"),
            "objetivo": md.get("objetivo"),
        })
    return {"data": rows}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_lead_followups_endpoint.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/leads/router.py backend/tests/test_lead_followups_endpoint.py
git commit -m "feat(leads): read endpoint for cadence follow-up jobs (visibility)"
```

---

### Task 2: Frontend cadence helpers (pure, tested) + BFF route

**Files:**
- Create: `frontend/src/lib/cadence-display.ts`
- Create: `frontend/src/lib/cadence-display.test.ts`
- Create: `frontend/src/app/api/leads/[id]/followups/route.ts`

**Interfaces:**
- Produces:
  - `type FollowupJob = { sequence: number | null; job_type: string | null; status: string; fire_at: string | null; sent_at: string | null; cancel_reason: string | null; objetivo: string | null }`
  - `touchStateLabel(job: FollowupJob): string` — derives the modality label per the Global Constraints table.
  - `objectiveLabel(objetivo: string | null): string` — slug→PT label; unknown/None → "—".
  - `GET /api/leads/{id}/followups` BFF → returns `FollowupJob[]` array (reads `follow_up_jobs` from Supabase directly, mirroring `/api/leads/[id]/deals`).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/cadence-display.test.ts
import { describe, it, expect } from "vitest";
import { touchStateLabel, objectiveLabel, type FollowupJob } from "@/lib/cadence-display";

function job(overrides: Partial<FollowupJob>): FollowupJob {
  return {
    sequence: 1, job_type: null, status: "pending",
    fire_at: null, sent_at: null, cancel_reason: null, objetivo: null,
    ...overrides,
  };
}

describe("touchStateLabel", () => {
  it("pending → Agendado", () => {
    expect(touchStateLabel(job({ status: "pending" }))).toBe("Agendado");
  });
  it("sent → Texto enviado", () => {
    expect(touchStateLabel(job({ status: "sent" }))).toBe("Texto enviado");
  });
  it("awaiting_reopen → Template enviado", () => {
    expect(touchStateLabel(job({ status: "awaiting_reopen" }))).toBe("Template enviado");
  });
  it("cancelled + reopen_context_refreshed → Contexto atualizado", () => {
    expect(touchStateLabel(job({ status: "cancelled", cancel_reason: "reopen_context_refreshed" })))
      .toBe("Contexto atualizado");
  });
  it("cancelled other reason → Cancelado", () => {
    expect(touchStateLabel(job({ status: "cancelled", cancel_reason: "window_expired" })))
      .toBe("Cancelado");
  });
});

describe("objectiveLabel", () => {
  it("maps known slugs", () => {
    expect(objectiveLabel("reengajar")).toBe("Reengajar");
    expect(objectiveLabel("reforco_valor")).toBe("Reforço de valor");
    expect(objectiveLabel("prova_social")).toBe("Prova social");
    expect(objectiveLabel("ultima_chamada")).toBe("Última chamada");
  });
  it("unknown / null → dash", () => {
    expect(objectiveLabel(null)).toBe("—");
    expect(objectiveLabel("xpto")).toBe("—");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/cadence-display.test.ts`
Expected: FAIL — cannot resolve `@/lib/cadence-display`.

- [ ] **Step 3: Implement the helper**

```typescript
// frontend/src/lib/cadence-display.ts
export type FollowupJob = {
  sequence: number | null;
  job_type: string | null;
  status: string;
  fire_at: string | null;
  sent_at: string | null;
  cancel_reason: string | null;
  objetivo: string | null;
};

/** Modalidade do toque derivada de (status, cancel_reason). Ver plano Tier A. */
export function touchStateLabel(job: FollowupJob): string {
  switch (job.status) {
    case "pending":
      return "Agendado";
    case "sent":
      return "Texto enviado";
    case "awaiting_reopen":
      return "Template enviado";
    case "cancelled":
      return job.cancel_reason === "reopen_context_refreshed"
        ? "Contexto atualizado"
        : "Cancelado";
    default:
      return job.status;
  }
}

const OBJECTIVE_LABELS: Record<string, string> = {
  reengajar: "Reengajar",
  reforco_valor: "Reforço de valor",
  prova_social: "Prova social",
  ultima_chamada: "Última chamada",
};

/** Slug do objetivo → rótulo PT; desconhecido/None → "—". */
export function objectiveLabel(objetivo: string | null): string {
  if (!objetivo) return "—";
  return OBJECTIVE_LABELS[objetivo] ?? "—";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/cadence-display.test.ts`
Expected: PASS (7 tests)

- [ ] **Step 5: Add the BFF route (mirrors /api/leads/[id]/deals)**

```typescript
// frontend/src/app/api/leads/[id]/followups/route.ts
import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("follow_up_jobs")
    .select("sequence, job_type, status, fire_at, sent_at, cancel_reason, metadata")
    .eq("lead_id", id)
    .order("fire_at", { ascending: true });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const rows = (data ?? []).map((j) => {
    const md = (j.metadata ?? {}) as Record<string, unknown>;
    return {
      sequence: j.sequence,
      job_type: j.job_type,
      status: j.status,
      fire_at: j.fire_at,
      sent_at: j.sent_at,
      cancel_reason: j.cancel_reason,
      objetivo: (md.objetivo as string | undefined) ?? null,
    };
  });

  return NextResponse.json(rows);
}
```

- [ ] **Step 6: Verify type-check + tests**

Run: `cd frontend && npx vitest run src/lib/cadence-display.test.ts && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/cadence-display.ts frontend/src/lib/cadence-display.test.ts "frontend/src/app/api/leads/[id]/followups/route.ts"
git commit -m "feat(cadence): frontend display helpers + BFF route for follow-up jobs"
```

---

### Task 3: `CadenceTimeline` component + render in Perfil tab

**Files:**
- Create: `frontend/src/components/conversas/cadence-timeline.tsx`
- Modify: `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx` (render `<CadenceTimeline leadId={lead.id} />` near the end of the tab body)

**Interfaces:**
- Consumes: `GET /api/leads/{id}/followups` (Task 2), `touchStateLabel`, `objectiveLabel`, `FollowupJob` (Task 2).
- Produces: `CadenceTimeline({ leadId }: { leadId: string })` — self-contained: fetches its own data, renders a compact list; renders nothing (returns null) when there are no jobs.

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/components/conversas/cadence-timeline.tsx
"use client";

import { useEffect, useState } from "react";
import { touchStateLabel, objectiveLabel, type FollowupJob } from "@/lib/cadence-display";
import { formatDayLabel } from "@/lib/datetime";

const DOT: Record<string, string> = {
  Agendado: "bg-[#7b7b78]",
  "Texto enviado": "bg-[#ff5600]",
  "Template enviado": "bg-[#1e6ee8]",
  "Contexto atualizado": "bg-[#1e6ee8]",
  Cancelado: "bg-[#dedbd6]",
};

export function CadenceTimeline({ leadId }: { leadId: string }) {
  const [jobs, setJobs] = useState<FollowupJob[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(`/api/leads/${leadId}/followups`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => { if (active) { setJobs(Array.isArray(data) ? data : []); setLoaded(true); } })
      .catch(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, [leadId]);

  if (!loaded || jobs.length === 0) return null;

  return (
    <div className="px-4 py-3 border-t border-[#dedbd6]">
      <h4 className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
        Cadência
      </h4>
      <ol className="flex flex-col gap-2">
        {jobs.map((job, idx) => {
          const state = touchStateLabel(job);
          const when = job.sent_at || job.fire_at;
          return (
            <li key={idx} className="flex items-start gap-2">
              <span className={`mt-1 h-1.5 w-1.5 rounded-full flex-shrink-0 ${DOT[state] ?? "bg-[#7b7b78]"}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[12px] font-medium text-[#111111]">
                    {job.sequence ? `T${job.sequence}` : "—"} · {objectiveLabel(job.objetivo)}
                  </span>
                </div>
                <div className="text-[11px] text-[#7b7b78]">
                  {state}
                  {state === "Cancelado" && job.cancel_reason ? ` · ${job.cancel_reason}` : ""}
                  {when ? ` · ${formatDayLabel(when)}` : ""}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
```

- [ ] **Step 2: (info) datetime helper**

`formatDayLabel(iso)` is confirmed exported from `src/lib/datetime.ts` (returns "Hoje"/"Ontem"/weekday/date — correct for a multi-day cadence). Use it as written; do not substitute a time-only formatter.

- [ ] **Step 3: Render in the Perfil tab**

In `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`: add the import at top:

```tsx
import { CadenceTimeline } from "@/components/conversas/cadence-timeline";
```

Then render `<CadenceTimeline leadId={lead.id} />` as the LAST child inside the tab's root container (after the existing sections, before the container closes). Use the `lead.id` prop already available in that component (confirm the prop name by reading the file; the component receives `lead`).

- [ ] **Step 4: Type-check + build sanity**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/conversas/cadence-timeline.tsx frontend/src/components/conversas/tabs/crm-perfil-tab.tsx
git commit -m "feat(cadence): Cadência mini-timeline in lead contact panel"
```

---

### Task 4: Follow-up badge on message bubble (extracted, tested)

**Files:**
- Create: `frontend/src/lib/sender-badge.ts`
- Create: `frontend/src/lib/sender-badge.test.ts`
- Modify: `frontend/src/components/conversas/message-bubble.tsx` (replace inline `getSenderBadge` with the imported one; ~lines 34-39)

**Interfaces:**
- Consumes: nothing new.
- Produces: `senderBadge(message: { role: string; sent_by?: string | null }): string | null` — `user`→null; `agent`→"IA"; `seller`→"Vendedor"; `followup`→"Cadência"; else null.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/sender-badge.test.ts
import { describe, it, expect } from "vitest";
import { senderBadge } from "@/lib/sender-badge";

describe("senderBadge", () => {
  it("user → null", () => {
    expect(senderBadge({ role: "user", sent_by: "user" })).toBeNull();
  });
  it("agent → IA", () => {
    expect(senderBadge({ role: "assistant", sent_by: "agent" })).toBe("IA");
  });
  it("seller → Vendedor", () => {
    expect(senderBadge({ role: "assistant", sent_by: "seller" })).toBe("Vendedor");
  });
  it("followup → Cadência (distinct from IA)", () => {
    expect(senderBadge({ role: "assistant", sent_by: "followup" })).toBe("Cadência");
  });
  it("unknown sent_by → null", () => {
    expect(senderBadge({ role: "assistant", sent_by: "handoff_context" })).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/sender-badge.test.ts`
Expected: FAIL — cannot resolve `@/lib/sender-badge`.

- [ ] **Step 3: Implement the helper**

```typescript
// frontend/src/lib/sender-badge.ts
/** Rótulo do remetente para a bolha de mensagem. followup → "Cadência" (distinto da IA). */
export function senderBadge(
  message: { role: string; sent_by?: string | null }
): string | null {
  if (message.role === "user") return null;
  if (message.sent_by === "agent") return "IA";
  if (message.sent_by === "seller") return "Vendedor";
  if (message.sent_by === "followup") return "Cadência";
  return null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/sender-badge.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Use it in message-bubble.tsx**

In `frontend/src/components/conversas/message-bubble.tsx`:
- Add import near the top (with the other imports): `import { senderBadge } from "@/lib/sender-badge";`
- DELETE the local `getSenderBadge` function (lines ~34-39).
- Change the call site (`const senderBadge = getSenderBadge(message);`, ~line 138) to use the imported helper. To avoid a name clash with the imported `senderBadge`, rename the local variable:
  `const badge = senderBadge(message);` and update its two usages (`{senderBadge && (` → `{badge && (` and `· {senderBadge}` → `· {badge}`) at ~lines 449-455.

- [ ] **Step 6: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/sender-badge.ts frontend/src/lib/sender-badge.test.ts frontend/src/components/conversas/message-bubble.tsx
git commit -m "feat(conversas): label follow-up message bubbles as 'Cadência'"
```

---

## Notes for the implementer

- The backend endpoint and the BFF route both flatten `metadata.objetivo` and intentionally DROP `objective_prompt` (heavy text — not needed for display).
- `getServiceSupabase` + the `params: Promise<{id}>` signature are the established BFF pattern (see `frontend/src/app/api/leads/[id]/deals/route.ts`) — copy it.
- The timeline is self-contained (fetches on mount, returns null when empty) so it adds nothing to leads without a cadence and needs no prop wiring beyond `leadId`.
- Do NOT add realtime/subscriptions, do NOT touch `/campanhas`, do NOT persist new metadata (Tier B — out of scope).
- After all tasks: run `cd frontend && npx vitest run` (all lib tests) and `cd backend && python -m pytest -q` once to confirm no regressions.

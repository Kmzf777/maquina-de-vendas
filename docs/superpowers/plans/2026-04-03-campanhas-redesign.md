# Campanhas Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unified campaigns system with independent Broadcasts (mass template sends) and Cadences (automated follow-up sequences) with triggers, presets, and unified dashboard.

**Architecture:** Evolve existing infra — create new tables (broadcasts, broadcast_leads, cadences, cadence_enrollments, template_presets), evolve cadence_steps. Refactor backend worker/scheduler to use new tables. Rewrite frontend `/campanhas` page with dashboard + tabs. Data migration from old campaigns/cadence_state tables.

**Tech Stack:** Supabase (PostgreSQL), FastAPI (Python), Next.js 15 App Router, TypeScript, Recharts (for trend chart)

**IMPORTANT Next.js 15 patterns:**
- Route handler params are `Promise<{id: string}>` — must use `await params`
- Use `getServiceSupabase` from `@/lib/supabase/api` for all API routes
- Follow existing patterns in `crm/src/app/api/deals/route.ts` and `crm/src/app/api/deals/[id]/route.ts`

---

## File Structure

### Database
- Create: `backend-evolution/migrations/010_campaigns_redesign.sql`

### Backend (Python)
- Create: `backend-evolution/app/broadcast/__init__.py`
- Create: `backend-evolution/app/broadcast/router.py`
- Create: `backend-evolution/app/broadcast/worker.py`
- Create: `backend-evolution/app/broadcast/service.py`
- Modify: `backend-evolution/app/cadence/service.py` — refactor to use cadence_enrollments + cadences tables
- Modify: `backend-evolution/app/cadence/scheduler.py` — refactor to use new tables + add stagnation trigger logic
- Modify: `backend-evolution/app/cadence/router.py` — refactor endpoints to use new tables
- Modify: `backend-evolution/app/buffer/processor.py` — update cadence pause to use new tables
- Modify: `backend-evolution/app/campaign/worker.py` — replace with broadcast worker import
- Modify: `backend-evolution/main.py` — register new routers

### Frontend Types & Constants
- Modify: `crm/src/lib/types.ts` — replace Campaign/CadenceStep/CadenceState with new types
- Modify: `crm/src/lib/constants.ts` — add BROADCAST_STATUS_COLORS, ENROLLMENT_STATUS_COLORS

### Frontend Hooks
- Create: `crm/src/hooks/use-realtime-broadcasts.ts`
- Create: `crm/src/hooks/use-realtime-cadences.ts`
- Delete: `crm/src/hooks/use-realtime-campaigns.ts` (replaced)

### Frontend API Routes
- Create: `crm/src/app/api/broadcasts/route.ts`
- Create: `crm/src/app/api/broadcasts/[id]/route.ts`
- Create: `crm/src/app/api/broadcasts/[id]/leads/route.ts`
- Create: `crm/src/app/api/broadcasts/[id]/start/route.ts`
- Create: `crm/src/app/api/cadences/route.ts`
- Create: `crm/src/app/api/cadences/[id]/route.ts`
- Create: `crm/src/app/api/cadences/[id]/steps/route.ts`
- Create: `crm/src/app/api/cadences/[id]/steps/[stepId]/route.ts`
- Create: `crm/src/app/api/cadences/[id]/enrollments/route.ts`
- Create: `crm/src/app/api/cadences/[id]/enrollments/[enrollId]/route.ts`
- Create: `crm/src/app/api/template-presets/route.ts`
- Create: `crm/src/app/api/template-presets/[id]/route.ts`
- Create: `crm/src/app/api/campaigns/stats/route.ts`

### Frontend Components
- Create: `crm/src/components/campaigns/campaigns-dashboard.tsx`
- Create: `crm/src/components/campaigns/campaigns-tabs.tsx`
- Create: `crm/src/components/campaigns/broadcast-list.tsx`
- Create: `crm/src/components/campaigns/broadcast-card.tsx`
- Create: `crm/src/components/campaigns/cadence-list.tsx`
- Create: `crm/src/components/campaigns/cadence-card.tsx`
- Create: `crm/src/components/campaigns/create-broadcast-modal.tsx`
- Create: `crm/src/components/campaigns/cadence-detail.tsx`
- Create: `crm/src/components/campaigns/cadence-steps-table.tsx`
- Create: `crm/src/components/campaigns/cadence-enrollments-table.tsx`
- Create: `crm/src/components/campaigns/cadence-trigger-config.tsx`
- Create: `crm/src/components/campaigns/campaign-trend-chart.tsx`

### Frontend Pages
- Rewrite: `crm/src/app/(authenticated)/campanhas/page.tsx`
- Rewrite: `crm/src/app/(authenticated)/campanhas/[id]/page.tsx` — cadence detail page

### Cleanup
- Delete: `crm/src/components/campaign-card.tsx`
- Delete: `crm/src/components/campaign-kpis.tsx`
- Delete: `crm/src/components/campaign-table.tsx`
- Delete: `crm/src/components/create-campaign-modal.tsx`
- Delete: `crm/src/components/cadence-leads-table.tsx`
- Delete: `crm/src/components/cadence-steps-modal.tsx`
- Delete: `crm/src/components/cadence-activity.tsx`

---

### Task 1: Database migration

**Files:**
- Create: `backend-evolution/migrations/010_campaigns_redesign.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 010_campaigns_redesign.sql
-- Split campaigns into broadcasts + cadences

-- 1. Create broadcasts table
CREATE TABLE IF NOT EXISTS broadcasts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    channel_id uuid REFERENCES channels(id),
    template_name text NOT NULL,
    template_preset_id uuid,
    template_variables jsonb DEFAULT '{}',
    total_leads int DEFAULT 0,
    sent int DEFAULT 0,
    failed int DEFAULT 0,
    delivered int DEFAULT 0,
    status text NOT NULL DEFAULT 'draft',
    scheduled_at timestamptz,
    send_interval_min int DEFAULT 3,
    send_interval_max int DEFAULT 8,
    cadence_id uuid,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_broadcasts_status ON broadcasts(status);

-- 2. Create broadcast_leads table
CREATE TABLE IF NOT EXISTS broadcast_leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    broadcast_id uuid NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'pending',
    sent_at timestamptz,
    error_message text,
    UNIQUE(broadcast_id, lead_id)
);

CREATE INDEX IF NOT EXISTS idx_broadcast_leads_broadcast ON broadcast_leads(broadcast_id);
CREATE INDEX IF NOT EXISTS idx_broadcast_leads_status ON broadcast_leads(broadcast_id, status);

-- 3. Create cadences table
CREATE TABLE IF NOT EXISTS cadences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    description text,
    target_type text NOT NULL DEFAULT 'manual',
    target_stage text,
    stagnation_days int,
    send_start_hour int DEFAULT 7,
    send_end_hour int DEFAULT 18,
    cooldown_hours int DEFAULT 48,
    max_messages int DEFAULT 5,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cadences_status ON cadences(status);
CREATE INDEX IF NOT EXISTS idx_cadences_target ON cadences(target_type, target_stage);

-- 4. Add FK from broadcasts to cadences (after cadences exists)
ALTER TABLE broadcasts ADD CONSTRAINT fk_broadcasts_cadence
    FOREIGN KEY (cadence_id) REFERENCES cadences(id) ON DELETE SET NULL;

-- 5. Create new cadence_steps table (replaces old one)
-- Drop old cadence_steps
DROP TABLE IF EXISTS cadence_steps CASCADE;

CREATE TABLE cadence_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cadence_id uuid NOT NULL REFERENCES cadences(id) ON DELETE CASCADE,
    step_order int NOT NULL,
    message_text text NOT NULL,
    delay_days int DEFAULT 0,
    created_at timestamptz DEFAULT now(),
    UNIQUE(cadence_id, step_order)
);

CREATE INDEX IF NOT EXISTS idx_cadence_steps_cadence ON cadence_steps(cadence_id);

-- 6. Create cadence_enrollments table (replaces cadence_state)
CREATE TABLE IF NOT EXISTS cadence_enrollments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cadence_id uuid NOT NULL REFERENCES cadences(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    deal_id uuid REFERENCES deals(id) ON DELETE SET NULL,
    broadcast_id uuid REFERENCES broadcasts(id) ON DELETE SET NULL,
    current_step int DEFAULT 0,
    status text NOT NULL DEFAULT 'active',
    total_messages_sent int DEFAULT 0,
    next_send_at timestamptz,
    cooldown_until timestamptz,
    responded_at timestamptz,
    enrolled_at timestamptz DEFAULT now(),
    completed_at timestamptz,
    UNIQUE(cadence_id, lead_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_cadence ON cadence_enrollments(cadence_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_lead ON cadence_enrollments(lead_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_status ON cadence_enrollments(status);
CREATE INDEX IF NOT EXISTS idx_enrollments_next_send ON cadence_enrollments(status, next_send_at);

-- 7. Create template_presets table
CREATE TABLE IF NOT EXISTS template_presets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    template_name text NOT NULL,
    variables jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- 8. Migrate data from campaigns -> broadcasts + cadences
DO $$
DECLARE
    c RECORD;
    new_cadence_id uuid;
    new_broadcast_id uuid;
BEGIN
    FOR c IN SELECT * FROM campaigns LOOP
        -- Create cadence from campaign's cadence config
        INSERT INTO cadences (name, description, target_type, send_start_hour, send_end_hour, cooldown_hours, max_messages, status)
        VALUES (
            c.name || ' - Cadencia',
            'Migrado da campanha: ' || c.name,
            'manual',
            COALESCE(c.cadence_send_start_hour, 7),
            COALESCE(c.cadence_send_end_hour, 18),
            COALESCE(c.cadence_cooldown_hours, 48),
            COALESCE(c.cadence_max_messages, 8),
            CASE c.status WHEN 'completed' THEN 'archived' WHEN 'paused' THEN 'paused' ELSE 'active' END
        )
        RETURNING id INTO new_cadence_id;

        -- Create broadcast from campaign's send config
        INSERT INTO broadcasts (name, template_name, template_variables, total_leads, sent, failed, status, send_interval_min, send_interval_max, cadence_id, created_at)
        VALUES (
            c.name,
            c.template_name,
            COALESCE(c.template_params, '{}'),
            c.total_leads,
            c.sent,
            c.failed,
            c.status,
            COALESCE(c.send_interval_min, 3),
            COALESCE(c.send_interval_max, 8),
            new_cadence_id,
            c.created_at
        )
        RETURNING id INTO new_broadcast_id;

        -- Migrate leads.campaign_id -> broadcast_leads
        INSERT INTO broadcast_leads (broadcast_id, lead_id, status)
        SELECT new_broadcast_id, id,
            CASE status
                WHEN 'imported' THEN 'pending'
                WHEN 'template_sent' THEN 'sent'
                WHEN 'failed' THEN 'failed'
                ELSE 'sent'
            END
        FROM leads
        WHERE campaign_id = c.id;

        -- Migrate cadence_state -> cadence_enrollments
        INSERT INTO cadence_enrollments (cadence_id, lead_id, broadcast_id, current_step, status, total_messages_sent, next_send_at, cooldown_until, responded_at, enrolled_at)
        SELECT new_cadence_id, cs.lead_id, new_broadcast_id, cs.current_step,
            CASE cs.status
                WHEN 'cooled' THEN 'completed'
                ELSE cs.status
            END,
            cs.total_messages_sent, cs.next_send_at, cs.cooldown_until, cs.responded_at, cs.created_at
        FROM cadence_state cs
        WHERE cs.campaign_id = c.id;
    END LOOP;
END $$;

-- 9. Drop old tables
DROP TABLE IF EXISTS cadence_state CASCADE;
DROP TABLE IF EXISTS campaigns CASCADE;

-- 10. Remove campaign_id from leads
ALTER TABLE leads DROP COLUMN IF EXISTS campaign_id;

-- 11. Enable realtime
ALTER PUBLICATION supabase_realtime ADD TABLE broadcasts;
ALTER PUBLICATION supabase_realtime ADD TABLE cadences;
ALTER PUBLICATION supabase_realtime ADD TABLE cadence_enrollments;
ALTER PUBLICATION supabase_realtime ADD TABLE broadcast_leads;
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/migrations/010_campaigns_redesign.sql
git commit -m "feat: add migration 010 — split campaigns into broadcasts + cadences"
```

---

### Task 2: Update TypeScript types and constants

**Files:**
- Modify: `crm/src/lib/types.ts`
- Modify: `crm/src/lib/constants.ts`

- [ ] **Step 1: Replace Campaign/CadenceStep/CadenceState types in types.ts**

Remove the existing `Campaign`, `CadenceStep`, and `CadenceState` interfaces (lines 100-151) and replace with:

```typescript
export interface Broadcast {
  id: string;
  name: string;
  channel_id: string | null;
  template_name: string;
  template_preset_id: string | null;
  template_variables: Record<string, unknown>;
  total_leads: number;
  sent: number;
  failed: number;
  delivered: number;
  status: "draft" | "scheduled" | "running" | "paused" | "completed";
  scheduled_at: string | null;
  send_interval_min: number;
  send_interval_max: number;
  cadence_id: string | null;
  created_at: string;
  updated_at: string;
  // Joined
  cadences?: { id: string; name: string } | null;
}

export interface BroadcastLead {
  id: string;
  broadcast_id: string;
  lead_id: string;
  status: "pending" | "sent" | "failed" | "delivered";
  sent_at: string | null;
  error_message: string | null;
  leads?: { id: string; name: string | null; phone: string };
}

export interface Cadence {
  id: string;
  name: string;
  description: string | null;
  target_type: "manual" | "lead_stage" | "deal_stage";
  target_stage: string | null;
  stagnation_days: number | null;
  send_start_hour: number;
  send_end_hour: number;
  cooldown_hours: number;
  max_messages: number;
  status: "active" | "paused" | "archived";
  created_at: string;
  updated_at: string;
}

export interface CadenceStep {
  id: string;
  cadence_id: string;
  step_order: number;
  message_text: string;
  delay_days: number;
  created_at: string;
}

export interface CadenceEnrollment {
  id: string;
  cadence_id: string;
  lead_id: string;
  deal_id: string | null;
  broadcast_id: string | null;
  current_step: number;
  status: "active" | "paused" | "responded" | "exhausted" | "completed";
  total_messages_sent: number;
  next_send_at: string | null;
  cooldown_until: string | null;
  responded_at: string | null;
  enrolled_at: string;
  completed_at: string | null;
  leads?: { id: string; name: string | null; phone: string; company: string | null; stage: string };
  deals?: { id: string; title: string; stage: string } | null;
}

export interface TemplatePreset {
  id: string;
  name: string;
  template_name: string;
  variables: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}
```

Also remove `campaign_id` from the `Lead` interface (line 8).

- [ ] **Step 2: Update constants.ts**

Replace `CAMPAIGN_STATUS_COLORS` with `BROADCAST_STATUS_COLORS` and add `ENROLLMENT_STATUS_*`:

```typescript
export const BROADCAST_STATUS_COLORS: Record<string, string> = {
  draft: "bg-[#f4f4f0] text-[#5f6368]",
  scheduled: "bg-[#f0ecd0] text-[#8a7a2a]",
  running: "bg-[#d8f0dc] text-[#2d6a3f]",
  paused: "bg-[#f0ecd0] text-[#8a7a2a]",
  completed: "bg-[#dce8f0] text-[#2a5a8a]",
};

export const CADENCE_TARGET_LABELS: Record<string, string> = {
  manual: "Manual",
  lead_stage: "Stage do Lead",
  deal_stage: "Stage do Deal",
};

export const ENROLLMENT_STATUS_COLORS: Record<string, { dot: string; bg: string; text: string }> = {
  active: { dot: "#f59e0b", bg: "bg-[#fef3c7]", text: "text-[#92400e]" },
  paused: { dot: "#9ca3af", bg: "bg-[#f4f4f0]", text: "text-[#5f6368]" },
  responded: { dot: "#4ade80", bg: "bg-[#d8f0dc]", text: "text-[#2d6a3f]" },
  exhausted: { dot: "#f87171", bg: "bg-[#fee2e2]", text: "text-[#991b1b]" },
  completed: { dot: "#5b8aad", bg: "bg-[#dce8f0]", text: "text-[#2a5a8a]" },
};

export const ENROLLMENT_STATUS_LABELS: Record<string, string> = {
  active: "Ativo",
  paused: "Pausado",
  responded: "Respondeu",
  exhausted: "Esgotado",
  completed: "Completou",
};
```

Remove the old `CAMPAIGN_STATUS_COLORS`, `CADENCE_STATUS_COLORS`, `CADENCE_STATUS_LABELS`. Keep all other constants unchanged.

- [ ] **Step 3: Commit**

```bash
git add crm/src/lib/types.ts crm/src/lib/constants.ts
git commit -m "feat: replace Campaign types with Broadcast + Cadence + Enrollment types"
```

---

### Task 3: Backend — broadcast service and router

**Files:**
- Create: `backend-evolution/app/broadcast/__init__.py`
- Create: `backend-evolution/app/broadcast/service.py`
- Create: `backend-evolution/app/broadcast/router.py`

- [ ] **Step 1: Create `backend-evolution/app/broadcast/__init__.py`**

```python
```

Empty file.

- [ ] **Step 2: Create `backend-evolution/app/broadcast/service.py`**

```python
from typing import Any
from app.db.supabase import get_supabase


def get_broadcast(broadcast_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("broadcasts").select("*").eq("id", broadcast_id).single().execute()
    return result.data


def get_pending_broadcast_leads(broadcast_id: str, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("broadcast_leads")
        .select("*, leads!inner(id, phone, stage)")
        .eq("broadcast_id", broadcast_id)
        .eq("status", "pending")
        .limit(limit)
        .execute()
    )
    return result.data


def mark_broadcast_lead_sent(bl_id: str) -> None:
    from datetime import datetime, timezone
    sb = get_supabase()
    sb.table("broadcast_leads").update({
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", bl_id).execute()


def mark_broadcast_lead_failed(bl_id: str, error: str) -> None:
    sb = get_supabase()
    sb.table("broadcast_leads").update({
        "status": "failed",
        "error_message": error,
    }).eq("id", bl_id).execute()


def increment_broadcast_sent(broadcast_id: str) -> None:
    sb = get_supabase()
    broadcast = sb.table("broadcasts").select("sent").eq("id", broadcast_id).single().execute().data
    sb.table("broadcasts").update({"sent": broadcast["sent"] + 1}).eq("id", broadcast_id).execute()


def increment_broadcast_failed(broadcast_id: str) -> None:
    sb = get_supabase()
    broadcast = sb.table("broadcasts").select("failed").eq("id", broadcast_id).single().execute().data
    sb.table("broadcasts").update({"failed": broadcast["failed"] + 1}).eq("id", broadcast_id).execute()
```

- [ ] **Step 3: Create `backend-evolution/app/broadcast/router.py`**

```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.campaign.importer import parse_csv

router = APIRouter(prefix="/api/broadcasts", tags=["broadcasts"])


class BroadcastCreate(BaseModel):
    name: str
    channel_id: str | None = None
    template_name: str
    template_preset_id: str | None = None
    template_variables: dict | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8
    cadence_id: str | None = None
    scheduled_at: str | None = None


class AssignLeadsRequest(BaseModel):
    lead_ids: list[str]


@router.get("")
async def list_broadcasts():
    sb = get_supabase()
    result = (
        sb.table("broadcasts")
        .select("*, cadences(id, name)")
        .order("created_at", desc=True)
        .execute()
    )
    return {"data": result.data}


@router.post("")
async def create_broadcast(broadcast: BroadcastCreate):
    sb = get_supabase()
    data = broadcast.model_dump(exclude_none=True)
    if "template_variables" not in data:
        data["template_variables"] = {}
    status = "scheduled" if data.get("scheduled_at") else "draft"
    data["status"] = status
    result = sb.table("broadcasts").insert(data).execute()
    return result.data[0]


@router.get("/{broadcast_id}")
async def get_broadcast(broadcast_id: str):
    sb = get_supabase()
    result = (
        sb.table("broadcasts")
        .select("*, cadences(id, name)")
        .eq("id", broadcast_id)
        .single()
        .execute()
    )
    return result.data


@router.patch("/{broadcast_id}")
async def update_broadcast(broadcast_id: str, body: dict):
    sb = get_supabase()
    from datetime import datetime, timezone
    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = sb.table("broadcasts").update(body).eq("id", broadcast_id).select().single().execute()
    return result.data


@router.delete("/{broadcast_id}")
async def delete_broadcast(broadcast_id: str):
    sb = get_supabase()
    broadcast = sb.table("broadcasts").select("status").eq("id", broadcast_id).single().execute().data
    if broadcast["status"] not in ("draft", "completed"):
        raise HTTPException(400, "Apenas disparos em rascunho ou completos podem ser excluidos")
    sb.table("broadcasts").delete().eq("id", broadcast_id).execute()
    return {"ok": True}


@router.post("/{broadcast_id}/leads")
async def assign_leads(broadcast_id: str, req: AssignLeadsRequest):
    sb = get_supabase()
    assigned = 0
    for lead_id in req.lead_ids:
        try:
            sb.table("broadcast_leads").insert({
                "broadcast_id": broadcast_id,
                "lead_id": lead_id,
            }).execute()
            assigned += 1
        except Exception:
            pass  # Duplicate, skip

    total = sb.table("broadcast_leads").select("id", count="exact").eq("broadcast_id", broadcast_id).execute().count
    sb.table("broadcasts").update({"total_leads": total or 0}).eq("id", broadcast_id).execute()
    return {"assigned": assigned}


@router.post("/{broadcast_id}/import")
async def import_leads(broadcast_id: str, file: UploadFile = File(...)):
    content = await file.read()
    result = parse_csv(content)

    if not result.valid:
        raise HTTPException(400, "Nenhum numero valido encontrado no CSV")

    sb = get_supabase()
    created = 0

    for phone in result.valid:
        try:
            lead_result = sb.table("leads").select("id").eq("phone", phone).execute()
            if lead_result.data:
                lead_id = lead_result.data[0]["id"]
            else:
                insert_result = sb.table("leads").insert({
                    "phone": phone,
                    "status": "imported",
                    "stage": "pending",
                }).execute()
                lead_id = insert_result.data[0]["id"]

            sb.table("broadcast_leads").insert({
                "broadcast_id": broadcast_id,
                "lead_id": lead_id,
            }).execute()
            created += 1
        except Exception:
            pass

    total = sb.table("broadcast_leads").select("id", count="exact").eq("broadcast_id", broadcast_id).execute().count
    sb.table("broadcasts").update({"total_leads": total or 0}).eq("id", broadcast_id).execute()

    return {"imported": created, "invalid": len(result.invalid), "invalid_numbers": result.invalid[:20]}


@router.post("/{broadcast_id}/start")
async def start_broadcast(broadcast_id: str):
    sb = get_supabase()
    broadcast = sb.table("broadcasts").select("*").eq("id", broadcast_id).single().execute().data
    if broadcast["status"] == "running":
        raise HTTPException(400, "Disparo ja esta rodando")

    pending = sb.table("broadcast_leads").select("id", count="exact").eq("broadcast_id", broadcast_id).eq("status", "pending").execute().count
    if not pending:
        raise HTTPException(400, "Nenhum lead pendente para envio")

    sb.table("broadcasts").update({"status": "running"}).eq("id", broadcast_id).execute()
    return {"status": "started", "leads_queued": pending}


@router.post("/{broadcast_id}/pause")
async def pause_broadcast(broadcast_id: str):
    sb = get_supabase()
    sb.table("broadcasts").update({"status": "paused"}).eq("id", broadcast_id).execute()
    return {"status": "paused"}
```

- [ ] **Step 4: Commit**

```bash
git add backend-evolution/app/broadcast/
git commit -m "feat: add broadcast service and router"
```

---

### Task 4: Backend — refactor cadence service for new tables

**Files:**
- Modify: `backend-evolution/app/cadence/service.py`

- [ ] **Step 1: Rewrite cadence service to use new tables**

Replace the entire content of `backend-evolution/app/cadence/service.py` with:

```python
from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase


def create_enrollment(
    cadence_id: str,
    lead_id: str,
    deal_id: str | None = None,
    broadcast_id: str | None = None,
    next_send_at: datetime | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    data = {
        "cadence_id": cadence_id,
        "lead_id": lead_id,
        "status": "active",
        "current_step": 0,
        "total_messages_sent": 0,
        "next_send_at": next_send_at.isoformat() if next_send_at else None,
    }
    if deal_id:
        data["deal_id"] = deal_id
    if broadcast_id:
        data["broadcast_id"] = broadcast_id
    result = sb.table("cadence_enrollments").insert(data).execute()
    return result.data[0]


def get_active_enrollment(lead_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("*, cadences!inner(id, name, cooldown_hours)")
        .eq("lead_id", lead_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def pause_enrollment(enrollment_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "status": "responded",
            "responded_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def resume_enrollment(enrollment_id: str, next_send_at: datetime) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "status": "active",
            "current_step": 0,
            "next_send_at": next_send_at.isoformat(),
            "cooldown_until": None,
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def advance_enrollment(
    enrollment_id: str,
    new_step: int,
    total_sent: int,
    next_send_at: datetime,
) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "current_step": new_step,
            "total_messages_sent": total_sent,
            "next_send_at": next_send_at.isoformat(),
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def exhaust_enrollment(enrollment_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "status": "exhausted",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def complete_enrollment(enrollment_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def get_next_step(cadence_id: str, step_order: int) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .select("*")
        .eq("cadence_id", cadence_id)
        .eq("step_order", step_order)
        .execute()
    )
    return result.data[0] if result.data else None


def get_due_enrollments(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("*, leads!inner(phone, stage, human_control, name, company), cadences!inner(id, name, send_start_hour, send_end_hour, max_messages, status)")
        .eq("status", "active")
        .lte("next_send_at", now.isoformat())
        .limit(limit)
        .execute()
    )
    return result.data


def get_reengagement_enrollments(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("*, leads!inner(phone, last_msg_at, human_control), cadences!inner(id, cooldown_hours, status)")
        .eq("status", "responded")
        .lte("responded_at", now.isoformat())
        .limit(limit)
        .execute()
    )
    return result.data


def get_stagnation_cadences() -> list[dict[str, Any]]:
    """Get active cadences that have stagnation triggers configured."""
    sb = get_supabase()
    result = (
        sb.table("cadences")
        .select("*")
        .eq("status", "active")
        .not_.is_("stagnation_days", "null")
        .execute()
    )
    return result.data


def is_enrolled(cadence_id: str, lead_id: str) -> bool:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("id")
        .eq("cadence_id", cadence_id)
        .eq("lead_id", lead_id)
        .in_("status", ["active", "paused", "responded"])
        .limit(1)
        .execute()
    )
    return len(result.data) > 0
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/app/cadence/service.py
git commit -m "refactor: rewrite cadence service for new enrollments + cadences tables"
```

---

### Task 5: Backend — refactor cadence scheduler and broadcast worker

**Files:**
- Modify: `backend-evolution/app/cadence/scheduler.py`
- Create: `backend-evolution/app/broadcast/worker.py`
- Modify: `backend-evolution/app/campaign/worker.py`

- [ ] **Step 1: Rewrite `backend-evolution/app/cadence/scheduler.py`**

Replace entire content:

```python
import logging
import random
import asyncio
from datetime import datetime, timezone, timedelta

from app.cadence.service import (
    get_due_enrollments,
    get_reengagement_enrollments,
    get_stagnation_cadences,
    get_next_step,
    advance_enrollment,
    complete_enrollment,
    exhaust_enrollment,
    resume_enrollment,
    create_enrollment,
    is_enrolled,
)
from app.leads.service import save_message
from app.whatsapp.client import send_text
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

BRT_OFFSET = timedelta(hours=-3)


def is_within_send_window(now_utc: datetime, start_hour: int = 7, end_hour: int = 18) -> bool:
    brt_time = now_utc + BRT_OFFSET
    return start_hour <= brt_time.hour < end_hour


def calculate_next_send_at(
    now_utc: datetime,
    delay_days: int = 0,
    start_hour: int = 7,
    end_hour: int = 18,
) -> datetime:
    candidate = now_utc + timedelta(days=delay_days)
    candidate_brt = candidate + BRT_OFFSET

    if candidate_brt.hour < start_hour:
        candidate_brt = candidate_brt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        return candidate_brt - BRT_OFFSET
    elif candidate_brt.hour >= end_hour:
        next_day = candidate_brt + timedelta(days=1)
        next_day = next_day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        return next_day - BRT_OFFSET

    return candidate


def _substitute_variables(text: str, lead: dict) -> str:
    """Replace {{nome}}, {{empresa}}, {{telefone}} with lead data."""
    text = text.replace("{{nome}}", lead.get("name") or "")
    text = text.replace("{{empresa}}", lead.get("company") or "")
    text = text.replace("{{telefone}}", lead.get("phone") or "")
    return text


async def process_due_cadences(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    enrollments = get_due_enrollments(now, limit=10)

    for enrollment in enrollments:
        lead = enrollment["leads"]
        cadence = enrollment["cadences"]

        if cadence["status"] != "active":
            continue
        if lead.get("human_control"):
            continue
        if not is_within_send_window(now, cadence["send_start_hour"], cadence["send_end_hour"]):
            continue

        next_step_order = enrollment["current_step"] + 1
        step = get_next_step(enrollment["cadence_id"], next_step_order)

        if step is None:
            complete_enrollment(enrollment["id"])
            logger.info(f"[CADENCE] Lead {lead['phone']} completed cadence — no more steps")
            continue

        try:
            message = _substitute_variables(step["message_text"], lead)
            await send_text(lead["phone"], message)

            new_total = enrollment["total_messages_sent"] + 1

            save_message(
                lead_id=enrollment["lead_id"],
                role="assistant",
                content=message,
                stage=lead.get("stage"),
                sent_by="cadence",
            )

            max_msgs = cadence["max_messages"]
            if new_total >= max_msgs:
                exhaust_enrollment(enrollment["id"])
                logger.info(f"[CADENCE] Lead {lead['phone']} exhausted — {new_total} messages")
            else:
                next_step = get_next_step(enrollment["cadence_id"], next_step_order + 1)
                delay = next_step["delay_days"] if next_step else 1
                next_send = calculate_next_send_at(now, delay, cadence["send_start_hour"], cadence["send_end_hour"])
                advance_enrollment(enrollment["id"], new_step=next_step_order, total_sent=new_total, next_send_at=next_send)
                logger.info(f"[CADENCE] Sent step {next_step_order} to {lead['phone']}")

        except Exception as e:
            logger.error(f"[CADENCE] Failed to send to {lead['phone']}: {e}", exc_info=True)

        await asyncio.sleep(random.randint(2, 5))


async def process_reengagements(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    enrollments = get_reengagement_enrollments(now)

    for enrollment in enrollments:
        lead = enrollment["leads"]
        cadence = enrollment["cadences"]

        if cadence["status"] != "active":
            continue
        if lead.get("human_control"):
            continue

        responded_at = enrollment["responded_at"]
        if isinstance(responded_at, str):
            from dateutil.parser import parse
            responded_at = parse(responded_at)

        cooldown_deadline = responded_at + timedelta(hours=cadence["cooldown_hours"])
        if now < cooldown_deadline:
            continue

        last_msg_at = lead.get("last_msg_at")
        if last_msg_at:
            if isinstance(last_msg_at, str):
                from dateutil.parser import parse
                last_msg_at = parse(last_msg_at)
            if last_msg_at > responded_at:
                continue

        next_send = calculate_next_send_at(now, 0, 7, 18)
        resume_enrollment(enrollment["id"], next_send_at=next_send)
        logger.info(f"[CADENCE] Lead {lead['phone']} re-engaged — resuming cadence")


async def process_stagnation_triggers(now: datetime | None = None):
    """Check for leads/deals stuck in stages and auto-enroll in cadences."""
    now = now or datetime.now(timezone.utc)
    cadences = get_stagnation_cadences()
    sb = get_supabase()

    for cadence in cadences:
        target_type = cadence["target_type"]
        target_stage = cadence["target_stage"]
        stagnation_days = cadence["stagnation_days"]

        if not target_stage or not stagnation_days:
            continue

        cutoff = (now - timedelta(days=stagnation_days)).isoformat()

        if target_type == "lead_stage":
            leads = (
                sb.table("leads")
                .select("id, phone")
                .eq("stage", target_stage)
                .eq("human_control", False)
                .lte("entered_stage_at", cutoff)
                .limit(20)
                .execute()
                .data
            )
            for lead in leads:
                if not is_enrolled(cadence["id"], lead["id"]):
                    try:
                        next_send = calculate_next_send_at(now, 0, cadence["send_start_hour"], cadence["send_end_hour"])
                        create_enrollment(cadence["id"], lead["id"], next_send_at=next_send)
                        logger.info(f"[STAGNATION] Enrolled lead {lead['phone']} in cadence '{cadence['name']}'")
                    except Exception as e:
                        logger.warning(f"[STAGNATION] Failed to enroll lead {lead['id']}: {e}")

        elif target_type == "deal_stage":
            deals = (
                sb.table("deals")
                .select("id, lead_id, leads!inner(id, phone, human_control)")
                .eq("stage", target_stage)
                .lte("updated_at", cutoff)
                .limit(20)
                .execute()
                .data
            )
            for deal in deals:
                lead = deal["leads"]
                if lead.get("human_control"):
                    continue
                if not is_enrolled(cadence["id"], lead["id"]):
                    try:
                        next_send = calculate_next_send_at(now, 0, cadence["send_start_hour"], cadence["send_end_hour"])
                        create_enrollment(cadence["id"], lead["id"], deal_id=deal["id"], next_send_at=next_send)
                        logger.info(f"[STAGNATION] Enrolled deal {deal['id']} in cadence '{cadence['name']}'")
                    except Exception as e:
                        logger.warning(f"[STAGNATION] Failed to enroll deal {deal['id']}: {e}")
```

- [ ] **Step 2: Create `backend-evolution/app/broadcast/worker.py`**

```python
import asyncio
import logging
import random
from datetime import datetime, timezone

from app.db.supabase import get_supabase
from app.whatsapp.client import send_template
from app.broadcast.service import (
    get_pending_broadcast_leads,
    mark_broadcast_lead_sent,
    mark_broadcast_lead_failed,
    increment_broadcast_sent,
    increment_broadcast_failed,
)
from app.cadence.service import create_enrollment
from app.cadence.scheduler import (
    process_due_cadences,
    process_reengagements,
    process_stagnation_triggers,
    calculate_next_send_at,
)

logger = logging.getLogger(__name__)


async def run_worker():
    """Main worker loop: processes broadcasts, cadences, and stagnation triggers."""
    logger.info("Broadcast + Cadence worker started")

    while True:
        try:
            await process_broadcasts()
            await process_due_cadences()
            await process_reengagements()
            await process_stagnation_triggers()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)


async def process_broadcasts():
    """Find running broadcasts and send pending templates."""
    sb = get_supabase()
    broadcasts = (
        sb.table("broadcasts")
        .select("*")
        .eq("status", "running")
        .execute()
        .data
    )

    for broadcast in broadcasts:
        await process_single_broadcast(broadcast)


async def process_single_broadcast(broadcast: dict):
    sb = get_supabase()
    broadcast_id = broadcast["id"]

    pending_leads = get_pending_broadcast_leads(broadcast_id, limit=10)

    if not pending_leads:
        # Check if all leads are processed
        remaining = (
            sb.table("broadcast_leads")
            .select("id", count="exact")
            .eq("broadcast_id", broadcast_id)
            .eq("status", "pending")
            .execute()
            .count
        )
        if not remaining:
            sb.table("broadcasts").update({"status": "completed"}).eq("id", broadcast_id).execute()
            logger.info(f"Broadcast {broadcast_id} completed")
        return

    for bl in pending_leads:
        # Check if still running
        current = sb.table("broadcasts").select("status").eq("id", broadcast_id).single().execute().data
        if current["status"] != "running":
            return

        lead = bl["leads"]

        try:
            await send_template(
                to=lead["phone"],
                template_name=broadcast["template_name"],
                components=broadcast.get("template_variables", {}).get("components"),
            )
            mark_broadcast_lead_sent(bl["id"])
            increment_broadcast_sent(broadcast_id)

            # Enroll in cadence if configured
            if broadcast.get("cadence_id"):
                try:
                    cadence = sb.table("cadences").select("*").eq("id", broadcast["cadence_id"]).single().execute().data
                    if cadence:
                        first_step = (
                            sb.table("cadence_steps")
                            .select("delay_days")
                            .eq("cadence_id", cadence["id"])
                            .eq("step_order", 1)
                            .execute()
                            .data
                        )
                        delay = first_step[0]["delay_days"] if first_step else 1
                        next_send = calculate_next_send_at(
                            datetime.now(timezone.utc),
                            delay,
                            cadence.get("send_start_hour", 7),
                            cadence.get("send_end_hour", 18),
                        )
                        create_enrollment(
                            cadence_id=cadence["id"],
                            lead_id=lead["id"],
                            broadcast_id=broadcast_id,
                            next_send_at=next_send,
                        )
                except Exception as ce:
                    logger.warning(f"Could not enroll {lead['phone']} in cadence: {ce}")

            logger.info(f"Template sent to {lead['phone']}")

        except Exception as e:
            logger.error(f"Failed to send to {lead['phone']}: {e}")
            mark_broadcast_lead_failed(bl["id"], str(e))
            increment_broadcast_failed(broadcast_id)

        interval = random.randint(
            broadcast.get("send_interval_min", 3),
            broadcast.get("send_interval_max", 8),
        )
        await asyncio.sleep(interval)
```

- [ ] **Step 3: Update `backend-evolution/app/campaign/worker.py` to delegate**

Replace entire content:

```python
# Legacy entry point — delegates to broadcast worker
from app.broadcast.worker import run_worker

if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
```

- [ ] **Step 4: Commit**

```bash
git add backend-evolution/app/cadence/scheduler.py backend-evolution/app/broadcast/worker.py backend-evolution/app/campaign/worker.py
git commit -m "feat: refactor scheduler for enrollments + add broadcast worker with stagnation triggers"
```

---

### Task 6: Backend — refactor cadence router and buffer processor

**Files:**
- Modify: `backend-evolution/app/cadence/router.py`
- Modify: `backend-evolution/app/buffer/processor.py`
- Modify: `backend-evolution/main.py`

- [ ] **Step 1: Rewrite `backend-evolution/app/cadence/router.py`**

Replace entire content:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/cadences", tags=["cadences"])


class CadenceCreate(BaseModel):
    name: str
    description: str | None = None
    target_type: str = "manual"
    target_stage: str | None = None
    stagnation_days: int | None = None
    send_start_hour: int = 7
    send_end_hour: int = 18
    cooldown_hours: int = 48
    max_messages: int = 5


class StepCreate(BaseModel):
    step_order: int
    message_text: str
    delay_days: int = 0


class EnrollRequest(BaseModel):
    lead_id: str
    deal_id: str | None = None


@router.get("")
async def list_cadences():
    sb = get_supabase()
    result = sb.table("cadences").select("*").order("created_at", desc=True).execute()
    return {"data": result.data}


@router.post("")
async def create_cadence(cadence: CadenceCreate):
    sb = get_supabase()
    result = sb.table("cadences").insert(cadence.model_dump(exclude_none=True)).execute()
    return result.data[0]


@router.get("/{cadence_id}")
async def get_cadence(cadence_id: str):
    sb = get_supabase()
    result = sb.table("cadences").select("*").eq("id", cadence_id).single().execute()
    return result.data


@router.patch("/{cadence_id}")
async def update_cadence(cadence_id: str, body: dict):
    sb = get_supabase()
    from datetime import datetime, timezone
    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = sb.table("cadences").update(body).eq("id", cadence_id).select().single().execute()
    return result.data


@router.delete("/{cadence_id}")
async def delete_cadence(cadence_id: str):
    sb = get_supabase()
    active = (
        sb.table("cadence_enrollments")
        .select("id", count="exact")
        .eq("cadence_id", cadence_id)
        .eq("status", "active")
        .execute()
        .count
    )
    if active:
        raise HTTPException(400, f"Cadencia tem {active} leads ativos — pause ou remova antes de excluir")
    sb.table("cadences").delete().eq("id", cadence_id).execute()
    return {"ok": True}


# --- Steps ---

@router.get("/{cadence_id}/steps")
async def list_steps(cadence_id: str):
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .select("*")
        .eq("cadence_id", cadence_id)
        .order("step_order")
        .execute()
    )
    return {"data": result.data}


@router.post("/{cadence_id}/steps")
async def create_step(cadence_id: str, step: StepCreate):
    sb = get_supabase()
    result = sb.table("cadence_steps").insert({
        "cadence_id": cadence_id,
        **step.model_dump(),
    }).execute()
    return result.data[0]


@router.put("/{cadence_id}/steps/{step_id}")
async def update_step(cadence_id: str, step_id: str, body: dict):
    sb = get_supabase()
    result = sb.table("cadence_steps").update(body).eq("id", step_id).select().single().execute()
    return result.data


@router.delete("/{cadence_id}/steps/{step_id}")
async def delete_step(cadence_id: str, step_id: str):
    sb = get_supabase()
    sb.table("cadence_steps").delete().eq("id", step_id).execute()
    return {"ok": True}


# --- Enrollments ---

@router.get("/{cadence_id}/enrollments")
async def list_enrollments(cadence_id: str, status: str | None = None):
    sb = get_supabase()
    query = (
        sb.table("cadence_enrollments")
        .select("*, leads!inner(id, name, phone, company, stage)")
        .eq("cadence_id", cadence_id)
        .order("enrolled_at", desc=True)
    )
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return {"data": result.data}


@router.post("/{cadence_id}/enrollments")
async def enroll_lead(cadence_id: str, req: EnrollRequest):
    from app.cadence.service import create_enrollment, is_enrolled
    from app.cadence.scheduler import calculate_next_send_at
    from datetime import datetime, timezone

    if is_enrolled(cadence_id, req.lead_id):
        raise HTTPException(400, "Lead ja esta nesta cadencia")

    sb = get_supabase()
    cadence = sb.table("cadences").select("*").eq("id", cadence_id).single().execute().data

    first_step = (
        sb.table("cadence_steps")
        .select("delay_days")
        .eq("cadence_id", cadence_id)
        .eq("step_order", 1)
        .execute()
        .data
    )
    delay = first_step[0]["delay_days"] if first_step else 0

    now = datetime.now(timezone.utc)
    next_send = calculate_next_send_at(now, delay, cadence["send_start_hour"], cadence["send_end_hour"])

    enrollment = create_enrollment(
        cadence_id=cadence_id,
        lead_id=req.lead_id,
        deal_id=req.deal_id,
        next_send_at=next_send,
    )
    return enrollment


@router.patch("/{cadence_id}/enrollments/{enroll_id}")
async def update_enrollment(cadence_id: str, enroll_id: str, body: dict):
    from app.cadence.service import pause_enrollment, resume_enrollment
    from app.cadence.scheduler import calculate_next_send_at
    from datetime import datetime, timezone

    action = body.get("action")
    if action == "pause":
        return pause_enrollment(enroll_id)
    elif action == "resume":
        now = datetime.now(timezone.utc)
        next_send = calculate_next_send_at(now, 0, 7, 18)
        return resume_enrollment(enroll_id, next_send_at=next_send)

    sb = get_supabase()
    result = sb.table("cadence_enrollments").update(body).eq("id", enroll_id).select().single().execute()
    return result.data


@router.delete("/{cadence_id}/enrollments/{enroll_id}")
async def remove_enrollment(cadence_id: str, enroll_id: str):
    sb = get_supabase()
    sb.table("cadence_enrollments").delete().eq("id", enroll_id).execute()
    return {"ok": True}
```

- [ ] **Step 2: Update buffer processor to use new enrollment functions**

In `backend-evolution/app/buffer/processor.py`, replace the import and cadence pause block.

Replace the import line:
```python
from app.cadence.service import get_cadence_state, pause_cadence
```
with:
```python
from app.cadence.service import get_active_enrollment, pause_enrollment
```

Replace the cadence pause block (lines 72-77):
```python
        cadence = get_cadence_state(lead["id"])
        if cadence:
            pause_cadence(cadence["id"])
            sb = get_supabase()
            sb.rpc("increment_cadence_responded", {"campaign_id_param": cadence["campaign_id"]}).execute()
            logger.info(f"[CADENCE] Lead {phone} responded — pausing cadence")
```
with:
```python
        enrollment = get_active_enrollment(lead["id"])
        if enrollment:
            pause_enrollment(enrollment["id"])
            logger.info(f"[CADENCE] Lead {phone} responded — pausing enrollment")
```

- [ ] **Step 3: Register new routers in main.py**

Read `backend-evolution/main.py` to find where routers are registered, then add:

```python
from app.broadcast.router import router as broadcast_router
from app.cadence.router import router as cadence_router

app.include_router(broadcast_router)
app.include_router(cadence_router)
```

And update the worker import to use broadcast worker:
```python
from app.broadcast.worker import run_worker
```

- [ ] **Step 4: Commit**

```bash
git add backend-evolution/app/cadence/router.py backend-evolution/app/buffer/processor.py backend-evolution/main.py
git commit -m "refactor: update cadence router, buffer processor, and main.py for new tables"
```

---

### Task 7: Frontend API routes — broadcasts

**Files:**
- Create: `crm/src/app/api/broadcasts/route.ts`
- Create: `crm/src/app/api/broadcasts/[id]/route.ts`
- Create: `crm/src/app/api/broadcasts/[id]/leads/route.ts`
- Create: `crm/src/app/api/broadcasts/[id]/start/route.ts`

- [ ] **Step 1: Create `crm/src/app/api/broadcasts/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("broadcasts")
    .select("*, cadences(id, name)")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("broadcasts")
    .insert({
      name: body.name,
      channel_id: body.channel_id || null,
      template_name: body.template_name,
      template_preset_id: body.template_preset_id || null,
      template_variables: body.template_variables || {},
      send_interval_min: body.send_interval_min || 3,
      send_interval_max: body.send_interval_max || 8,
      cadence_id: body.cadence_id || null,
      scheduled_at: body.scheduled_at || null,
      status: body.scheduled_at ? "scheduled" : "draft",
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Create `crm/src/app/api/broadcasts/[id]/route.ts`**

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
    .from("broadcasts")
    .select("*, cadences(id, name)")
    .eq("id", id)
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("broadcasts")
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { error } = await supabase.from("broadcasts").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 3: Create `crm/src/app/api/broadcasts/[id]/leads/route.ts`**

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
    .select("*, leads(id, name, phone, company)")
    .eq("broadcast_id", id)
    .order("sent_at", { ascending: false, nullsFirst: true });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const leadIds: string[] = body.lead_ids || [];
  let assigned = 0;

  for (const leadId of leadIds) {
    const { error } = await supabase
      .from("broadcast_leads")
      .insert({ broadcast_id: id, lead_id: leadId });
    if (!error) assigned++;
  }

  const { count } = await supabase
    .from("broadcast_leads")
    .select("id", { count: "exact", head: true })
    .eq("broadcast_id", id);

  await supabase
    .from("broadcasts")
    .update({ total_leads: count || 0 })
    .eq("id", id);

  return NextResponse.json({ assigned });
}
```

- [ ] **Step 4: Create `crm/src/app/api/broadcasts/[id]/start/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data: broadcast } = await supabase
    .from("broadcasts")
    .select("status")
    .eq("id", id)
    .single();

  if (broadcast?.status === "running") {
    return NextResponse.json({ error: "Disparo ja esta rodando" }, { status: 400 });
  }

  const { count } = await supabase
    .from("broadcast_leads")
    .select("id", { count: "exact", head: true })
    .eq("broadcast_id", id)
    .eq("status", "pending");

  if (!count) {
    return NextResponse.json({ error: "Nenhum lead pendente" }, { status: 400 });
  }

  await supabase
    .from("broadcasts")
    .update({ status: "running" })
    .eq("id", id);

  return NextResponse.json({ status: "started", leads_queued: count });
}
```

- [ ] **Step 5: Commit**

```bash
git add crm/src/app/api/broadcasts/
git commit -m "feat: add broadcast API routes (CRUD, leads, start)"
```

---

### Task 8: Frontend API routes — cadences, steps, enrollments, presets, stats

**Files:**
- Create: `crm/src/app/api/cadences/route.ts`
- Create: `crm/src/app/api/cadences/[id]/route.ts`
- Create: `crm/src/app/api/cadences/[id]/steps/route.ts`
- Create: `crm/src/app/api/cadences/[id]/steps/[stepId]/route.ts`
- Create: `crm/src/app/api/cadences/[id]/enrollments/route.ts`
- Create: `crm/src/app/api/cadences/[id]/enrollments/[enrollId]/route.ts`
- Create: `crm/src/app/api/template-presets/route.ts`
- Create: `crm/src/app/api/template-presets/[id]/route.ts`
- Create: `crm/src/app/api/campaigns/stats/route.ts`

- [ ] **Step 1: Create `crm/src/app/api/cadences/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("cadences")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadences")
    .insert({
      name: body.name,
      description: body.description || null,
      target_type: body.target_type || "manual",
      target_stage: body.target_stage || null,
      stagnation_days: body.stagnation_days || null,
      send_start_hour: body.send_start_hour ?? 7,
      send_end_hour: body.send_end_hour ?? 18,
      cooldown_hours: body.cooldown_hours ?? 48,
      max_messages: body.max_messages ?? 5,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 2: Create `crm/src/app/api/cadences/[id]/route.ts`**

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
    .from("cadences")
    .select("*")
    .eq("id", id)
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadences")
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { error } = await supabase.from("cadences").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 3: Create `crm/src/app/api/cadences/[id]/steps/route.ts`**

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
    .from("cadence_steps")
    .select("*")
    .eq("cadence_id", id)
    .order("step_order");

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadence_steps")
    .insert({
      cadence_id: id,
      step_order: body.step_order,
      message_text: body.message_text,
      delay_days: body.delay_days ?? 0,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 4: Create `crm/src/app/api/cadences/[id]/steps/[stepId]/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; stepId: string }> }
) {
  const { stepId } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadence_steps")
    .update(body)
    .eq("id", stepId)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; stepId: string }> }
) {
  const { stepId } = await params;
  const supabase = await getServiceSupabase();
  const { error } = await supabase.from("cadence_steps").delete().eq("id", stepId);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 5: Create `crm/src/app/api/cadences/[id]/enrollments/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const status = request.nextUrl.searchParams.get("status");
  const supabase = await getServiceSupabase();

  let query = supabase
    .from("cadence_enrollments")
    .select("*, leads!inner(id, name, phone, company, stage)")
    .eq("cadence_id", id)
    .order("enrolled_at", { ascending: false });

  if (status) query = query.eq("status", status);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadence_enrollments")
    .insert({
      cadence_id: id,
      lead_id: body.lead_id,
      deal_id: body.deal_id || null,
      status: "active",
      current_step: 0,
      total_messages_sent: 0,
    })
    .select("*, leads!inner(id, name, phone, company, stage)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 6: Create `crm/src/app/api/cadences/[id]/enrollments/[enrollId]/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; enrollId: string }> }
) {
  const { enrollId } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("cadence_enrollments")
    .update(body)
    .eq("id", enrollId)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; enrollId: string }> }
) {
  const { enrollId } = await params;
  const supabase = await getServiceSupabase();
  const { error } = await supabase.from("cadence_enrollments").delete().eq("id", enrollId);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 7: Create `crm/src/app/api/template-presets/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("template_presets")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("template_presets")
    .insert({
      name: body.name,
      template_name: body.template_name,
      variables: body.variables || {},
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 8: Create `crm/src/app/api/template-presets/[id]/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("template_presets")
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { error } = await supabase.from("template_presets").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 9: Create `crm/src/app/api/campaigns/stats/route.ts`**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const period = request.nextUrl.searchParams.get("period") || "30d";

  const daysMap: Record<string, number> = { "7d": 7, "30d": 30, "90d": 90 };
  const days = daysMap[period] || 30;
  const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

  const [broadcasts, cadences, enrollments, recentMessages] = await Promise.all([
    supabase.from("broadcasts").select("id, status").in("status", ["running", "scheduled"]),
    supabase.from("cadences").select("id, status").eq("status", "active"),
    supabase.from("cadence_enrollments").select("id, status, responded_at, enrolled_at"),
    supabase
      .from("messages")
      .select("created_at")
      .eq("sent_by", "cadence")
      .gte("created_at", since)
      .order("created_at"),
  ]);

  const allEnrollments = enrollments.data || [];
  const activeCount = allEnrollments.filter((e) => e.status === "active").length;
  const respondedCount = allEnrollments.filter((e) => e.status === "responded").length;
  const exhaustedCount = allEnrollments.filter((e) => e.status === "exhausted").length;
  const completedCount = allEnrollments.filter((e) => e.status === "completed").length;
  const totalFinished = respondedCount + exhaustedCount + completedCount;
  const responseRate = totalFinished > 0 ? Math.round((respondedCount / totalFinished) * 100) : 0;

  // Build daily trend data
  const msgs = recentMessages.data || [];
  const dailyMap: Record<string, { sent: number; responded: number }> = {};

  for (const m of msgs) {
    const day = m.created_at.slice(0, 10);
    if (!dailyMap[day]) dailyMap[day] = { sent: 0, responded: 0 };
    dailyMap[day].sent++;
  }

  for (const e of allEnrollments) {
    if (e.responded_at) {
      const day = e.responded_at.slice(0, 10);
      if (day >= since.slice(0, 10)) {
        if (!dailyMap[day]) dailyMap[day] = { sent: 0, responded: 0 };
        dailyMap[day].responded++;
      }
    }
  }

  const trend = Object.entries(dailyMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, data]) => ({ date, ...data }));

  return NextResponse.json({
    activeBroadcasts: (broadcasts.data || []).length,
    activeCadences: (cadences.data || []).length,
    leadsInFollowUp: activeCount,
    responseRate,
    respondedCount,
    trend,
  });
}
```

- [ ] **Step 10: Commit**

```bash
git add crm/src/app/api/cadences/ crm/src/app/api/template-presets/ crm/src/app/api/campaigns/stats/
git commit -m "feat: add cadences, template-presets, and campaigns stats API routes"
```

---

### Task 9: Frontend hooks — realtime broadcasts and cadences

**Files:**
- Create: `crm/src/hooks/use-realtime-broadcasts.ts`
- Create: `crm/src/hooks/use-realtime-cadences.ts`
- Delete: `crm/src/hooks/use-realtime-campaigns.ts`

- [ ] **Step 1: Create `crm/src/hooks/use-realtime-broadcasts.ts`**

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Broadcast } from "@/lib/types";

export function useRealtimeBroadcasts() {
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchBroadcasts = useCallback(async () => {
    const { data } = await supabase
      .from("broadcasts")
      .select("*, cadences(id, name)")
      .order("created_at", { ascending: false });
    if (data) setBroadcasts(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchBroadcasts();

    const channel = supabase
      .channel("broadcasts-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "broadcasts" },
        () => fetchBroadcasts()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchBroadcasts]);

  return { broadcasts, loading };
}
```

- [ ] **Step 2: Create `crm/src/hooks/use-realtime-cadences.ts`**

```typescript
"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Cadence } from "@/lib/types";

export function useRealtimeCadences() {
  const [cadences, setCadences] = useState<Cadence[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchCadences = useCallback(async () => {
    const { data } = await supabase
      .from("cadences")
      .select("*")
      .order("created_at", { ascending: false });
    if (data) setCadences(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchCadences();

    const channel = supabase
      .channel("cadences-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "cadences" },
        () => fetchCadences()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchCadences]);

  return { cadences, loading };
}
```

- [ ] **Step 3: Delete old hook**

```bash
rm crm/src/hooks/use-realtime-campaigns.ts
```

- [ ] **Step 4: Commit**

```bash
git add crm/src/hooks/use-realtime-broadcasts.ts crm/src/hooks/use-realtime-cadences.ts
git rm crm/src/hooks/use-realtime-campaigns.ts
git commit -m "feat: add realtime hooks for broadcasts and cadences, remove old campaigns hook"
```

---

### Task 10: Frontend components — dashboard, cards, lists

**Files:**
- Create: `crm/src/components/campaigns/campaigns-dashboard.tsx`
- Create: `crm/src/components/campaigns/campaigns-tabs.tsx`
- Create: `crm/src/components/campaigns/broadcast-card.tsx`
- Create: `crm/src/components/campaigns/broadcast-list.tsx`
- Create: `crm/src/components/campaigns/cadence-card.tsx`
- Create: `crm/src/components/campaigns/cadence-list.tsx`
- Create: `crm/src/components/campaigns/campaign-trend-chart.tsx`

- [ ] **Step 1: Create `crm/src/components/campaigns/campaigns-dashboard.tsx`**

```typescript
"use client";

import { useEffect, useState } from "react";
import { CampaignTrendChart } from "./campaign-trend-chart";

interface Stats {
  activeBroadcasts: number;
  activeCadences: number;
  leadsInFollowUp: number;
  responseRate: number;
  respondedCount: number;
  trend: { date: string; sent: number; responded: number }[];
}

interface CampaignsDashboardProps {
  period: string;
  onPeriodChange: (p: string) => void;
}

export function CampaignsDashboard({ period, onPeriodChange }: CampaignsDashboardProps) {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    fetch(`/api/campaigns/stats?period=${period}`)
      .then((r) => r.json())
      .then(setStats);
  }, [period]);

  if (!stats) {
    return (
      <div className="grid grid-cols-5 gap-4 mb-6">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="card p-4 h-20 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
        ))}
      </div>
    );
  }

  const kpis = [
    { label: "Disparos ativos", value: stats.activeBroadcasts },
    { label: "Cadencias ativas", value: stats.activeCadences },
    { label: "Leads em follow-up", value: stats.leadsInFollowUp },
    { label: "Taxa de resposta", value: `${stats.responseRate}%` },
    { label: "Responderam", value: stats.respondedCount },
  ];

  const periods = [
    { key: "7d", label: "7 dias" },
    { key: "30d", label: "30 dias" },
    { key: "90d", label: "90 dias" },
  ];

  return (
    <div className="space-y-5 mb-6">
      <div className="grid grid-cols-5 gap-4">
        {kpis.map((kpi) => (
          <div key={kpi.label} className="card p-4">
            <p className="text-[10px] text-[#9ca3af] uppercase font-semibold tracking-wider">{kpi.label}</p>
            <span className="text-[22px] font-bold text-[#1f1f1f] leading-none mt-1 block">{kpi.value}</span>
          </div>
        ))}
      </div>

      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[13px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
            Tendencia de respostas
          </h3>
          <div className="flex gap-1">
            {periods.map((p) => (
              <button
                key={p.key}
                onClick={() => onPeriodChange(p.key)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${
                  period === p.key ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <CampaignTrendChart data={stats.trend} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `crm/src/components/campaigns/campaign-trend-chart.tsx`**

```typescript
"use client";

interface TrendData {
  date: string;
  sent: number;
  responded: number;
}

export function CampaignTrendChart({ data }: { data: TrendData[] }) {
  if (!data.length) {
    return <p className="text-[13px] text-[#9ca3af] text-center py-8">Sem dados no periodo</p>;
  }

  const maxVal = Math.max(...data.map((d) => Math.max(d.sent, d.responded)), 1);
  const height = 160;
  const width = data.length * 40;

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${Math.max(width, 400)} ${height + 30}`} className="w-full" style={{ minWidth: 400 }}>
        {data.map((d, i) => {
          const x = (i / (data.length - 1 || 1)) * (Math.max(width, 400) - 40) + 20;
          const ySent = height - (d.sent / maxVal) * height;
          const yResp = height - (d.responded / maxVal) * height;

          return (
            <g key={d.date}>
              {i > 0 && (
                <>
                  <line
                    x1={((i - 1) / (data.length - 1 || 1)) * (Math.max(width, 400) - 40) + 20}
                    y1={height - (data[i - 1].sent / maxVal) * height}
                    x2={x}
                    y2={ySent}
                    stroke="#c8cc8e"
                    strokeWidth="2"
                  />
                  <line
                    x1={((i - 1) / (data.length - 1 || 1)) * (Math.max(width, 400) - 40) + 20}
                    y1={height - (data[i - 1].responded / maxVal) * height}
                    x2={x}
                    y2={yResp}
                    stroke="#5aad65"
                    strokeWidth="2"
                  />
                </>
              )}
              <circle cx={x} cy={ySent} r="3" fill="#c8cc8e" />
              <circle cx={x} cy={yResp} r="3" fill="#5aad65" />
              {i % Math.ceil(data.length / 8) === 0 && (
                <text x={x} y={height + 18} textAnchor="middle" fontSize="10" fill="#9ca3af">
                  {d.date.slice(5)}
                </text>
              )}
            </g>
          );
        })}
        <text x="10" y="12" fontSize="10" fill="#c8cc8e">Enviadas</text>
        <text x="80" y="12" fontSize="10" fill="#5aad65">Respostas</text>
      </svg>
    </div>
  );
}
```

- [ ] **Step 3: Create `crm/src/components/campaigns/broadcast-card.tsx`**

```typescript
"use client";

import type { Broadcast } from "@/lib/types";
import { BROADCAST_STATUS_COLORS } from "@/lib/constants";

interface BroadcastCardProps {
  broadcast: Broadcast;
  onStart: () => void;
  onPause: () => void;
  onClick: () => void;
}

export function BroadcastCard({ broadcast: b, onStart, onPause, onClick }: BroadcastCardProps) {
  const pct = b.total_leads > 0 ? Math.round((b.sent / b.total_leads) * 100) : 0;

  return (
    <div className="card p-4 cursor-pointer hover:shadow-md transition-shadow" onClick={onClick}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[14px] font-semibold text-[#1f1f1f] truncate">{b.name}</h4>
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${BROADCAST_STATUS_COLORS[b.status] || ""}`}>
          {b.status}
        </span>
      </div>

      <p className="text-[12px] text-[#5f6368] mb-3">Template: {b.template_name}</p>

      <div className="w-full h-1.5 bg-[#e5e5dc] rounded-full mb-3">
        <div className="h-full bg-[#c8cc8e] rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>

      <div className="grid grid-cols-4 gap-2 text-center mb-3">
        <div>
          <p className="text-[16px] font-bold text-[#1f1f1f]">{b.total_leads}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Leads</p>
        </div>
        <div>
          <p className="text-[16px] font-bold text-[#2d6a3f]">{b.sent}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Enviados</p>
        </div>
        <div>
          <p className="text-[16px] font-bold text-[#5b8aad]">{b.delivered}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Entregues</p>
        </div>
        <div>
          <p className="text-[16px] font-bold text-[#a33]">{b.failed}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Falhas</p>
        </div>
      </div>

      {b.cadences && (
        <p className="text-[11px] text-[#5f6368] mb-2">
          Cadencia: <span className="font-medium text-[#1f1f1f]">{b.cadences.name}</span>
        </p>
      )}

      <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
        {b.status === "draft" && (
          <button onClick={onStart} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333]">
            Iniciar
          </button>
        )}
        {b.status === "running" && (
          <button onClick={onPause} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#f0ecd0] text-[#8a7a2a] hover:bg-[#e5e0c0]">
            Pausar
          </button>
        )}
        {b.status === "paused" && (
          <button onClick={onStart} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#d8f0dc] text-[#2d6a3f] hover:bg-[#c0e8c4]">
            Retomar
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create `crm/src/components/campaigns/broadcast-list.tsx`**

```typescript
"use client";

import { useState } from "react";
import type { Broadcast } from "@/lib/types";
import { BroadcastCard } from "./broadcast-card";

interface BroadcastListProps {
  broadcasts: Broadcast[];
  onRefresh: () => void;
}

export function BroadcastList({ broadcasts, onRefresh }: BroadcastListProps) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const filtered = broadcasts.filter((b) => {
    if (filter !== "all" && b.status !== filter) return false;
    if (search && !b.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const filters = [
    { key: "all", label: "Todos" },
    { key: "draft", label: "Rascunho" },
    { key: "running", label: "Rodando" },
    { key: "completed", label: "Completos" },
  ];

  const handleAction = async (id: string, action: "start" | "pause") => {
    const url = action === "start" ? `/api/broadcasts/${id}/start` : `/api/broadcasts/${id}`;
    const method = action === "start" ? "POST" : "PATCH";
    const body = action === "pause" ? JSON.stringify({ status: "paused" }) : undefined;
    await fetch(url, { method, headers: { "Content-Type": "application/json" }, body });
    onRefresh();
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Buscar disparo..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 rounded-lg border border-[#e5e5dc] text-[13px] bg-white w-64"
        />
        <div className="flex gap-1">
          {filters.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${
                filter === f.key ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[13px] text-[#9ca3af] text-center py-12">Nenhum disparo encontrado</p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {filtered.map((b) => (
            <BroadcastCard
              key={b.id}
              broadcast={b}
              onStart={() => handleAction(b.id, "start")}
              onPause={() => handleAction(b.id, "pause")}
              onClick={() => {}}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Create `crm/src/components/campaigns/cadence-card.tsx`**

```typescript
"use client";

import type { Cadence } from "@/lib/types";
import { AGENT_STAGES, DEAL_STAGES, CADENCE_TARGET_LABELS } from "@/lib/constants";
import { useRouter } from "next/navigation";

interface CadenceCardProps {
  cadence: Cadence;
  enrollmentCounts?: { active: number; responded: number; exhausted: number; completed: number };
  stepsCount?: number;
}

export function CadenceCard({ cadence: c, enrollmentCounts, stepsCount }: CadenceCardProps) {
  const router = useRouter();
  const counts = enrollmentCounts || { active: 0, responded: 0, exhausted: 0, completed: 0 };

  const allStages = [...AGENT_STAGES, ...DEAL_STAGES];
  const stageName = c.target_stage
    ? allStages.find((s) => s.key === c.target_stage)?.label || c.target_stage
    : null;

  let triggerText = "Manual";
  if (c.target_type !== "manual" && stageName) {
    triggerText = c.stagnation_days
      ? `Apos ${c.stagnation_days} dias em ${stageName}`
      : `Quando entra em ${stageName}`;
  }

  return (
    <div
      className="card p-4 cursor-pointer hover:shadow-md transition-shadow"
      onClick={() => router.push(`/campanhas/${c.id}`)}
    >
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-[14px] font-semibold text-[#1f1f1f] truncate">{c.name}</h4>
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
          c.status === "active" ? "bg-[#d8f0dc] text-[#2d6a3f]" :
          c.status === "paused" ? "bg-[#f0ecd0] text-[#8a7a2a]" :
          "bg-[#f4f4f0] text-[#5f6368]"
        }`}>
          {c.status === "active" ? "Ativa" : c.status === "paused" ? "Pausada" : "Arquivada"}
        </span>
      </div>

      <div className="flex items-center gap-2 mb-3">
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-[#f6f7ed] text-[#5f6368] font-medium">
          {CADENCE_TARGET_LABELS[c.target_type]}
        </span>
        <span className="text-[12px] text-[#5f6368]">{triggerText}</span>
      </div>

      {c.description && (
        <p className="text-[12px] text-[#5f6368] mb-3 line-clamp-2">{c.description}</p>
      )}

      <div className="grid grid-cols-4 gap-2 text-center mb-3">
        <div>
          <p className="text-[14px] font-bold text-[#92400e]">{counts.active}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Ativos</p>
        </div>
        <div>
          <p className="text-[14px] font-bold text-[#2d6a3f]">{counts.responded}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Responderam</p>
        </div>
        <div>
          <p className="text-[14px] font-bold text-[#991b1b]">{counts.exhausted}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Esgotados</p>
        </div>
        <div>
          <p className="text-[14px] font-bold text-[#2a5a8a]">{counts.completed}</p>
          <p className="text-[10px] text-[#9ca3af] uppercase">Completaram</p>
        </div>
      </div>

      <div className="flex items-center gap-3 text-[11px] text-[#5f6368]">
        {stepsCount !== undefined && <span>{stepsCount} steps</span>}
        <span>Janela: {c.send_start_hour}h-{c.send_end_hour}h</span>
        <span>Max: {c.max_messages} msgs</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Create `crm/src/components/campaigns/cadence-list.tsx`**

```typescript
"use client";

import { useState, useEffect } from "react";
import type { Cadence } from "@/lib/types";
import { CadenceCard } from "./cadence-card";
import { createClient } from "@/lib/supabase/client";

interface CadenceListProps {
  cadences: Cadence[];
}

export function CadenceList({ cadences }: CadenceListProps) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [enrollmentData, setEnrollmentData] = useState<Record<string, { active: number; responded: number; exhausted: number; completed: number }>>({});
  const [stepsData, setStepsData] = useState<Record<string, number>>({});

  useEffect(() => {
    const supabase = createClient();

    async function loadCounts() {
      const { data: enrollments } = await supabase
        .from("cadence_enrollments")
        .select("cadence_id, status");

      const { data: steps } = await supabase
        .from("cadence_steps")
        .select("cadence_id");

      if (enrollments) {
        const counts: typeof enrollmentData = {};
        for (const e of enrollments) {
          if (!counts[e.cadence_id]) counts[e.cadence_id] = { active: 0, responded: 0, exhausted: 0, completed: 0 };
          const s = e.status as keyof typeof counts[string];
          if (s in counts[e.cadence_id]) counts[e.cadence_id][s]++;
        }
        setEnrollmentData(counts);
      }

      if (steps) {
        const sc: Record<string, number> = {};
        for (const s of steps) {
          sc[s.cadence_id] = (sc[s.cadence_id] || 0) + 1;
        }
        setStepsData(sc);
      }
    }

    loadCounts();
  }, [cadences]);

  const filtered = cadences.filter((c) => {
    if (filter !== "all" && c.status !== filter) return false;
    if (search && !c.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const filters = [
    { key: "all", label: "Todas" },
    { key: "active", label: "Ativas" },
    { key: "paused", label: "Pausadas" },
    { key: "archived", label: "Arquivadas" },
  ];

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Buscar cadencia..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 rounded-lg border border-[#e5e5dc] text-[13px] bg-white w-64"
        />
        <div className="flex gap-1">
          {filters.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${
                filter === f.key ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[13px] text-[#9ca3af] text-center py-12">Nenhuma cadencia encontrada</p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {filtered.map((c) => (
            <CadenceCard
              key={c.id}
              cadence={c}
              enrollmentCounts={enrollmentData[c.id]}
              stepsCount={stepsData[c.id]}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Create `crm/src/components/campaigns/campaigns-tabs.tsx`**

```typescript
"use client";

import { useState } from "react";
import type { Broadcast, Cadence } from "@/lib/types";
import { BroadcastList } from "./broadcast-list";
import { CadenceList } from "./cadence-list";

interface CampaignsTabsProps {
  broadcasts: Broadcast[];
  cadences: Cadence[];
  onRefreshBroadcasts: () => void;
}

export function CampaignsTabs({ broadcasts, cadences, onRefreshBroadcasts }: CampaignsTabsProps) {
  const [tab, setTab] = useState<"broadcasts" | "cadences">("broadcasts");

  return (
    <div>
      <div className="flex gap-1 mb-5">
        <button
          onClick={() => setTab("broadcasts")}
          className={`px-4 py-2 rounded-lg text-[13px] font-medium transition-colors ${
            tab === "broadcasts" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
          }`}
        >
          Disparos ({broadcasts.length})
        </button>
        <button
          onClick={() => setTab("cadences")}
          className={`px-4 py-2 rounded-lg text-[13px] font-medium transition-colors ${
            tab === "cadences" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
          }`}
        >
          Cadencias ({cadences.length})
        </button>
      </div>

      {tab === "broadcasts" ? (
        <BroadcastList broadcasts={broadcasts} onRefresh={onRefreshBroadcasts} />
      ) : (
        <CadenceList cadences={cadences} />
      )}
    </div>
  );
}
```

- [ ] **Step 8: Commit**

```bash
git add crm/src/components/campaigns/
git commit -m "feat: add campaigns dashboard, trend chart, broadcast and cadence cards and lists"
```

---

### Task 11: Frontend — create broadcast modal and cadence detail components

**Files:**
- Create: `crm/src/components/campaigns/create-broadcast-modal.tsx`
- Create: `crm/src/components/campaigns/cadence-steps-table.tsx`
- Create: `crm/src/components/campaigns/cadence-trigger-config.tsx`
- Create: `crm/src/components/campaigns/cadence-enrollments-table.tsx`
- Create: `crm/src/components/campaigns/cadence-detail.tsx`

These are the most complex components. The implementer should:
- Follow the design system: `bg-[#1f1f1f]` dark headers, `#c8cc8e` olive accent, `rounded-xl`, `text-[13px]` sizes
- Use the existing `LeadSelector` component pattern for lead selection in broadcast modal
- Build the cadence steps table as described in the spec (list with #, message, delay, actions)
- Build trigger config with dropdowns for target_type, target_stage, stagnation_days
- Build enrollments table following the pattern from the old `cadence-leads-table.tsx`

- [ ] **Step 1: Create `crm/src/components/campaigns/create-broadcast-modal.tsx`**

A 3-step modal wizard:
- Step 1: Name, channel (dropdown of meta_cloud channels from `/api/channels`), template name, template variables (jsonb fields), preset selector (from `/api/template-presets`), cadence selector (dropdown of active cadences), send interval min/max
- Step 2: Lead selection (CRM tab with LeadSelector + CSV tab with file upload)
- Step 3: Review — summary of config, lead count, confirm button

```typescript
"use client";

import { useState, useEffect } from "react";
import type { Channel, Cadence, TemplatePreset } from "@/lib/types";
import { LeadSelector } from "@/components/lead-selector";

interface CreateBroadcastModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function CreateBroadcastModal({ open, onClose, onCreated }: CreateBroadcastModalProps) {
  const [step, setStep] = useState(1);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [cadences, setCadences] = useState<Cadence[]>([]);
  const [presets, setPresets] = useState<TemplatePreset[]>([]);
  const [saving, setSaving] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [channelId, setChannelId] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [templateVars, setTemplateVars] = useState<Record<string, string>>({});
  const [presetId, setPresetId] = useState("");
  const [cadenceId, setCadenceId] = useState("");
  const [intervalMin, setIntervalMin] = useState(3);
  const [intervalMax, setIntervalMax] = useState(8);

  // Leads
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [leadTab, setLeadTab] = useState<"crm" | "csv">("crm");

  useEffect(() => {
    if (!open) return;
    fetch("/api/channels").then((r) => r.json()).then((d) => {
      const metaChannels = (d.data || d).filter((c: Channel) => c.provider === "meta_cloud" && c.is_active);
      setChannels(metaChannels);
    });
    fetch("/api/cadences").then((r) => r.json()).then((d) => {
      setCadences((d.data || d).filter((c: Cadence) => c.status === "active"));
    });
    fetch("/api/template-presets").then((r) => r.json()).then(setPresets);
  }, [open]);

  const handlePresetSelect = (id: string) => {
    setPresetId(id);
    const preset = presets.find((p) => p.id === id);
    if (preset) {
      setTemplateName(preset.template_name);
      setTemplateVars(preset.variables as Record<string, string>);
    }
  };

  const handleCreate = async () => {
    setSaving(true);
    try {
      const res = await fetch("/api/broadcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          channel_id: channelId || null,
          template_name: templateName,
          template_preset_id: presetId || null,
          template_variables: templateVars,
          cadence_id: cadenceId || null,
          send_interval_min: intervalMin,
          send_interval_max: intervalMax,
        }),
      });
      const broadcast = await res.json();

      if (leadTab === "crm" && selectedLeadIds.length) {
        await fetch(`/api/broadcasts/${broadcast.id}/leads`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lead_ids: selectedLeadIds }),
        });
      } else if (leadTab === "csv" && csvFile) {
        const formData = new FormData();
        formData.append("file", csvFile);
        const fastApiUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";
        await fetch(`${fastApiUrl}/api/broadcasts/${broadcast.id}/import`, {
          method: "POST",
          body: formData,
        });
      }

      onCreated();
      onClose();
      resetForm();
    } finally {
      setSaving(false);
    }
  };

  const resetForm = () => {
    setStep(1);
    setName("");
    setChannelId("");
    setTemplateName("");
    setTemplateVars({});
    setPresetId("");
    setCadenceId("");
    setSelectedLeadIds([]);
    setCsvFile(null);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto">
        <div className="bg-[#1f1f1f] text-white px-6 py-4 rounded-t-2xl flex items-center justify-between">
          <h2 className="text-[16px] font-semibold">Novo Disparo — Passo {step}/3</h2>
          <button onClick={() => { onClose(); resetForm(); }} className="text-[#9ca3af] hover:text-white text-xl">&times;</button>
        </div>

        <div className="p-6 space-y-4">
          {step === 1 && (
            <>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Nome do disparo</label>
                <input value={name} onChange={(e) => setName(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" placeholder="Ex: Promo Black Friday" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Canal (Meta Cloud)</label>
                <select value={channelId} onChange={(e) => setChannelId(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]">
                  <option value="">Selecionar canal...</option>
                  {channels.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.phone})</option>)}
                </select>
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Preset (opcional)</label>
                <select value={presetId} onChange={(e) => handlePresetSelect(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]">
                  <option value="">Nenhum preset</option>
                  {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Template</label>
                <input value={templateName} onChange={(e) => setTemplateName(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" placeholder="Nome do template na Meta" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Cadencia vinculada (opcional)</label>
                <select value={cadenceId} onChange={(e) => setCadenceId(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]">
                  <option value="">Sem cadencia</option>
                  {cadences.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Intervalo min (s)</label>
                  <input type="number" value={intervalMin} onChange={(e) => setIntervalMin(Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
                </div>
                <div>
                  <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Intervalo max (s)</label>
                  <input type="number" value={intervalMax} onChange={(e) => setIntervalMax(Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
                </div>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="flex gap-2 mb-4">
                <button onClick={() => setLeadTab("crm")} className={`px-3 py-1.5 rounded-lg text-[12px] font-medium ${leadTab === "crm" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] bg-[#f4f4f0]"}`}>
                  Do CRM
                </button>
                <button onClick={() => setLeadTab("csv")} className={`px-3 py-1.5 rounded-lg text-[12px] font-medium ${leadTab === "csv" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] bg-[#f4f4f0]"}`}>
                  Importar CSV
                </button>
              </div>

              {leadTab === "crm" ? (
                <LeadSelector selectedIds={selectedLeadIds} onChange={setSelectedLeadIds} />
              ) : (
                <div className="border-2 border-dashed border-[#e5e5dc] rounded-xl p-8 text-center">
                  <input type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files?.[0] || null)} className="text-[13px]" />
                  {csvFile && <p className="text-[12px] text-[#2d6a3f] mt-2">Arquivo: {csvFile.name}</p>}
                </div>
              )}
              <p className="text-[12px] text-[#5f6368]">
                {leadTab === "crm" ? `${selectedLeadIds.length} leads selecionados` : csvFile ? "CSV pronto para envio" : "Nenhum arquivo selecionado"}
              </p>
            </>
          )}

          {step === 3 && (
            <div className="space-y-3">
              <h3 className="text-[14px] font-semibold text-[#1f1f1f]">Revisao do disparo</h3>
              <div className="bg-[#f6f7ed] rounded-xl p-4 space-y-2 text-[13px]">
                <p><span className="text-[#5f6368]">Nome:</span> <strong>{name}</strong></p>
                <p><span className="text-[#5f6368]">Template:</span> <strong>{templateName}</strong></p>
                <p><span className="text-[#5f6368]">Leads:</span> <strong>{leadTab === "crm" ? selectedLeadIds.length : "CSV"}</strong></p>
                <p><span className="text-[#5f6368]">Intervalo:</span> <strong>{intervalMin}-{intervalMax}s</strong></p>
                {cadenceId && <p><span className="text-[#5f6368]">Cadencia:</span> <strong>{cadences.find((c) => c.id === cadenceId)?.name}</strong></p>}
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-[#e5e5dc] flex justify-between">
          {step > 1 ? (
            <button onClick={() => setStep(step - 1)} className="px-4 py-2 rounded-lg text-[13px] font-medium text-[#5f6368] hover:bg-[#f6f7ed]">
              Voltar
            </button>
          ) : <div />}
          {step < 3 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={step === 1 && (!name || !templateName)}
              className="px-4 py-2 rounded-lg text-[13px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333] disabled:opacity-50"
            >
              Proximo
            </button>
          ) : (
            <button onClick={handleCreate} disabled={saving} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Disparo"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `crm/src/components/campaigns/cadence-steps-table.tsx`**

```typescript
"use client";

import { useState, useEffect } from "react";
import type { CadenceStep } from "@/lib/types";

interface CadenceStepsTableProps {
  cadenceId: string;
}

export function CadenceStepsTable({ cadenceId }: CadenceStepsTableProps) {
  const [steps, setSteps] = useState<CadenceStep[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [editDelay, setEditDelay] = useState(0);
  const [newText, setNewText] = useState("");
  const [newDelay, setNewDelay] = useState(1);
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    fetch(`/api/cadences/${cadenceId}/steps`)
      .then((r) => r.json())
      .then((d) => setSteps(d.data || d));
  }, [cadenceId]);

  const handleSave = async (stepId: string) => {
    await fetch(`/api/cadences/${cadenceId}/steps/${stepId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_text: editText, delay_days: editDelay }),
    });
    setSteps(steps.map((s) => s.id === stepId ? { ...s, message_text: editText, delay_days: editDelay } : s));
    setEditingId(null);
  };

  const handleAdd = async () => {
    const res = await fetch(`/api/cadences/${cadenceId}/steps`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ step_order: steps.length + 1, message_text: newText, delay_days: newDelay }),
    });
    const step = await res.json();
    setSteps([...steps, step.data || step]);
    setNewText("");
    setNewDelay(1);
    setShowAdd(false);
  };

  const handleDelete = async (stepId: string) => {
    await fetch(`/api/cadences/${cadenceId}/steps/${stepId}`, { method: "DELETE" });
    setSteps(steps.filter((s) => s.id !== stepId));
  };

  return (
    <div>
      <div className="bg-[#f4f4f0] rounded-xl overflow-hidden">
        <div className="grid grid-cols-[50px_1fr_100px_80px] gap-2 px-4 py-2 text-[11px] text-[#9ca3af] uppercase tracking-wider font-medium">
          <span>#</span>
          <span>Mensagem</span>
          <span>Delay</span>
          <span>Acoes</span>
        </div>

        {steps.map((step) => (
          <div key={step.id} className="grid grid-cols-[50px_1fr_100px_80px] gap-2 px-4 py-3 border-t border-[#e5e5dc] items-start">
            <span className="text-[14px] font-bold text-[#c8cc8e]">{step.step_order}</span>

            {editingId === step.id ? (
              <>
                <textarea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  className="w-full px-2 py-1 rounded border border-[#e5e5dc] text-[13px] min-h-[60px]"
                />
                <input
                  type="number"
                  value={editDelay}
                  onChange={(e) => setEditDelay(Number(e.target.value))}
                  className="w-full px-2 py-1 rounded border border-[#e5e5dc] text-[13px]"
                />
                <div className="flex gap-1">
                  <button onClick={() => handleSave(step.id)} className="text-[11px] text-[#2d6a3f] font-medium">Salvar</button>
                  <button onClick={() => setEditingId(null)} className="text-[11px] text-[#5f6368]">Cancelar</button>
                </div>
              </>
            ) : (
              <>
                <p className="text-[13px] text-[#1f1f1f] whitespace-pre-wrap">{step.message_text}</p>
                <span className="text-[13px] text-[#5f6368]">
                  {step.delay_days === 0 ? "Imediato" : `${step.delay_days} dia${step.delay_days > 1 ? "s" : ""}`}
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setEditingId(step.id); setEditText(step.message_text); setEditDelay(step.delay_days); }}
                    className="text-[11px] text-[#5b8aad] font-medium"
                  >
                    Editar
                  </button>
                  <button onClick={() => handleDelete(step.id)} className="text-[11px] text-[#a33] font-medium">
                    Remover
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      {showAdd ? (
        <div className="mt-3 p-4 border border-dashed border-[#e5e5dc] rounded-xl space-y-3">
          <textarea
            value={newText}
            onChange={(e) => setNewText(e.target.value)}
            placeholder="Mensagem do step... (use {{nome}}, {{empresa}})"
            className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px] min-h-[80px]"
          />
          <div className="flex items-center gap-3">
            <label className="text-[12px] text-[#5f6368]">Delay (dias):</label>
            <input type="number" value={newDelay} onChange={(e) => setNewDelay(Number(e.target.value))} className="w-20 px-2 py-1 rounded border border-[#e5e5dc] text-[13px]" />
            <button onClick={handleAdd} disabled={!newText} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#1f1f1f] text-white disabled:opacity-50">
              Adicionar
            </button>
            <button onClick={() => setShowAdd(false)} className="text-[12px] text-[#5f6368]">Cancelar</button>
          </div>
        </div>
      ) : (
        <button onClick={() => setShowAdd(true)} className="mt-3 w-full py-2 border border-dashed border-[#e5e5dc] rounded-xl text-[12px] text-[#5f6368] hover:bg-[#f6f7ed] transition-colors">
          + Adicionar step
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create `crm/src/components/campaigns/cadence-trigger-config.tsx`**

```typescript
"use client";

import { AGENT_STAGES, DEAL_STAGES } from "@/lib/constants";

interface CadenceTriggerConfigProps {
  targetType: string;
  targetStage: string | null;
  stagnationDays: number | null;
  onChange: (field: string, value: string | number | null) => void;
}

export function CadenceTriggerConfig({ targetType, targetStage, stagnationDays, onChange }: CadenceTriggerConfigProps) {
  const stages = targetType === "lead_stage"
    ? AGENT_STAGES.map((s) => ({ key: s.key, label: s.label }))
    : targetType === "deal_stage"
    ? DEAL_STAGES.map((s) => ({ key: s.key, label: s.label }))
    : [];

  return (
    <div className="space-y-3">
      <div>
        <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Tipo de trigger</label>
        <select
          value={targetType}
          onChange={(e) => {
            onChange("target_type", e.target.value);
            onChange("target_stage", null);
            onChange("stagnation_days", null);
          }}
          className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
        >
          <option value="manual">Manual</option>
          <option value="lead_stage">Quando lead entra no stage</option>
          <option value="deal_stage">Quando deal entra no stage</option>
        </select>
      </div>

      {targetType !== "manual" && (
        <>
          <div>
            <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Stage</label>
            <select
              value={targetStage || ""}
              onChange={(e) => onChange("target_stage", e.target.value || null)}
              className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
            >
              <option value="">Selecionar stage...</option>
              {stages.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>

          <div>
            <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">
              Dias parado no stage (opcional — vazio = imediato)
            </label>
            <input
              type="number"
              value={stagnationDays ?? ""}
              onChange={(e) => onChange("stagnation_days", e.target.value ? Number(e.target.value) : null)}
              placeholder="Ex: 3"
              className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
            />
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create `crm/src/components/campaigns/cadence-enrollments-table.tsx`**

```typescript
"use client";

import { useState, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";
import type { CadenceEnrollment } from "@/lib/types";
import { ENROLLMENT_STATUS_COLORS, ENROLLMENT_STATUS_LABELS } from "@/lib/constants";

interface CadenceEnrollmentsTableProps {
  cadenceId: string;
}

export function CadenceEnrollmentsTable({ cadenceId }: CadenceEnrollmentsTableProps) {
  const [enrollments, setEnrollments] = useState<CadenceEnrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const fetchEnrollments = async () => {
    const res = await fetch(`/api/cadences/${cadenceId}/enrollments`);
    const data = await res.json();
    setEnrollments(data.data || data);
    setLoading(false);
  };

  useEffect(() => {
    fetchEnrollments();

    const supabase = createClient();
    const channel = supabase
      .channel(`enrollments-${cadenceId}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "cadence_enrollments", filter: `cadence_id=eq.${cadenceId}` }, () => fetchEnrollments())
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [cadenceId]);

  const handleAction = async (enrollId: string, action: string) => {
    if (action === "remove") {
      await fetch(`/api/cadences/${cadenceId}/enrollments/${enrollId}`, { method: "DELETE" });
    } else {
      await fetch(`/api/cadences/${cadenceId}/enrollments/${enrollId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
    }
    fetchEnrollments();
  };

  const filtered = enrollments.filter((e) => {
    if (filter !== "all" && e.status !== filter) return false;
    if (search) {
      const lead = e.leads;
      if (!lead) return false;
      const text = `${lead.name || ""} ${lead.phone} ${lead.company || ""}`.toLowerCase();
      if (!text.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const filters = ["all", "active", "responded", "exhausted", "completed"];

  if (loading) return <div className="py-8 text-center text-[#9ca3af] text-[13px]">Carregando...</div>;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Buscar lead..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 rounded-lg border border-[#e5e5dc] text-[13px] bg-white w-64"
        />
        <div className="flex gap-1">
          {filters.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors ${
                filter === f ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
              }`}
            >
              {f === "all" ? "Todos" : ENROLLMENT_STATUS_LABELS[f] || f}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[13px] text-[#9ca3af] text-center py-8">Nenhum lead nesta cadencia</p>
      ) : (
        <div className="bg-white rounded-xl border border-[#e5e5dc] overflow-hidden">
          <div className="grid grid-cols-[1fr_100px_80px_120px_100px] gap-2 px-4 py-2 bg-[#f4f4f0] text-[11px] text-[#9ca3af] uppercase tracking-wider font-medium">
            <span>Lead</span>
            <span>Status</span>
            <span>Step</span>
            <span>Proximo envio</span>
            <span>Acoes</span>
          </div>

          {filtered.map((e) => {
            const lead = e.leads;
            const colors = ENROLLMENT_STATUS_COLORS[e.status] || ENROLLMENT_STATUS_COLORS.active;
            return (
              <div key={e.id} className="grid grid-cols-[1fr_100px_80px_120px_100px] gap-2 px-4 py-3 border-t border-[#e5e5dc] items-center">
                <div>
                  <p className="text-[13px] font-medium text-[#1f1f1f]">{lead?.name || lead?.phone || "—"}</p>
                  {lead?.name && <p className="text-[11px] text-[#5f6368]">{lead.phone}</p>}
                </div>
                <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium ${colors.bg} ${colors.text}`}>
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: colors.dot }} />
                  {ENROLLMENT_STATUS_LABELS[e.status] || e.status}
                </span>
                <span className="text-[13px] text-[#1f1f1f]">{e.current_step}/{e.total_messages_sent}</span>
                <span className="text-[12px] text-[#5f6368]">
                  {e.next_send_at ? new Date(e.next_send_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}
                </span>
                <div className="flex gap-1">
                  {e.status === "active" && (
                    <button onClick={() => handleAction(e.id, "pause")} className="text-[11px] text-[#8a7a2a] font-medium">Pausar</button>
                  )}
                  {(e.status === "paused" || e.status === "responded") && (
                    <button onClick={() => handleAction(e.id, "resume")} className="text-[11px] text-[#2d6a3f] font-medium">Retomar</button>
                  )}
                  <button onClick={() => handleAction(e.id, "remove")} className="text-[11px] text-[#a33] font-medium">Remover</button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add crm/src/components/campaigns/create-broadcast-modal.tsx crm/src/components/campaigns/cadence-steps-table.tsx crm/src/components/campaigns/cadence-trigger-config.tsx crm/src/components/campaigns/cadence-enrollments-table.tsx
git commit -m "feat: add create broadcast modal, cadence steps table, trigger config, enrollments table"
```

---

### Task 12: Frontend — rewrite campanhas pages and cleanup old components

**Files:**
- Rewrite: `crm/src/app/(authenticated)/campanhas/page.tsx`
- Rewrite: `crm/src/app/(authenticated)/campanhas/[id]/page.tsx`
- Delete old components

- [ ] **Step 1: Rewrite `/campanhas/page.tsx`**

Replace entire content:

```typescript
"use client";

import { useState } from "react";
import { useRealtimeBroadcasts } from "@/hooks/use-realtime-broadcasts";
import { useRealtimeCadences } from "@/hooks/use-realtime-cadences";
import { CampaignsDashboard } from "@/components/campaigns/campaigns-dashboard";
import { CampaignsTabs } from "@/components/campaigns/campaigns-tabs";
import { CreateBroadcastModal } from "@/components/campaigns/create-broadcast-modal";

export default function CampanhasPage() {
  const { broadcasts, loading: bLoading } = useRealtimeBroadcasts();
  const { cadences, loading: cLoading } = useRealtimeCadences();
  const [period, setPeriod] = useState("30d");
  const [showBroadcastModal, setShowBroadcastModal] = useState(false);
  const [showCadenceModal, setShowCadenceModal] = useState(false);

  const handleCreateCadence = async () => {
    const name = prompt("Nome da cadencia:");
    if (!name) return;
    await fetch("/api/cadences", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    setShowCadenceModal(false);
  };

  if (bLoading || cLoading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
        <div className="grid grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="card p-4 h-20 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
            Campanhas
          </h1>
          <p className="text-[14px] mt-1" style={{ color: "var(--text-muted)" }}>
            Disparos em massa e cadencias de follow-up
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowBroadcastModal(true)}
            className="px-4 py-2 rounded-xl text-[13px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333] transition-colors"
          >
            + Disparo
          </button>
          <button
            onClick={handleCreateCadence}
            className="px-4 py-2 rounded-xl text-[13px] font-medium bg-[#f6f7ed] text-[#1f1f1f] border border-[#e5e5dc] hover:bg-[#eef0e0] transition-colors"
          >
            + Cadencia
          </button>
        </div>
      </div>

      <CampaignsDashboard period={period} onPeriodChange={setPeriod} />
      <CampaignsTabs broadcasts={broadcasts} cadences={cadences} onRefreshBroadcasts={() => {}} />

      <CreateBroadcastModal
        open={showBroadcastModal}
        onClose={() => setShowBroadcastModal(false)}
        onCreated={() => {}}
      />
    </div>
  );
}
```

- [ ] **Step 2: Rewrite `/campanhas/[id]/page.tsx` as cadence detail page**

Replace entire content:

```typescript
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import type { Cadence } from "@/lib/types";
import { CadenceStepsTable } from "@/components/campaigns/cadence-steps-table";
import { CadenceTriggerConfig } from "@/components/campaigns/cadence-trigger-config";
import { CadenceEnrollmentsTable } from "@/components/campaigns/cadence-enrollments-table";

export default function CadenceDetailPage() {
  const params = useParams();
  const cadenceId = params.id as string;
  const [cadence, setCadence] = useState<Cadence | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"steps" | "leads" | "config">("steps");

  useEffect(() => {
    fetch(`/api/cadences/${cadenceId}`)
      .then((r) => r.json())
      .then((d) => { setCadence(d); setLoading(false); });
  }, [cadenceId]);

  const handleConfigChange = async (field: string, value: string | number | null) => {
    if (!cadence) return;
    const updated = { ...cadence, [field]: value };
    setCadence(updated as Cadence);
    await fetch(`/api/cadences/${cadenceId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value }),
    });
  };

  const handleToggleStatus = async () => {
    if (!cadence) return;
    const newStatus = cadence.status === "active" ? "paused" : "active";
    setCadence({ ...cadence, status: newStatus });
    await fetch(`/api/cadences/${cadenceId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    });
  };

  if (loading || !cadence) {
    return <div className="h-8 w-48 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-[24px] font-bold text-[#1f1f1f]">{cadence.name}</h1>
          {cadence.description && <p className="text-[14px] text-[#5f6368] mt-1">{cadence.description}</p>}
        </div>
        <div className="flex items-center gap-3">
          <span className={`px-2.5 py-1 rounded-full text-[12px] font-medium ${
            cadence.status === "active" ? "bg-[#d8f0dc] text-[#2d6a3f]" :
            cadence.status === "paused" ? "bg-[#f0ecd0] text-[#8a7a2a]" :
            "bg-[#f4f4f0] text-[#5f6368]"
          }`}>
            {cadence.status === "active" ? "Ativa" : cadence.status === "paused" ? "Pausada" : "Arquivada"}
          </span>
          <button
            onClick={handleToggleStatus}
            className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333]"
          >
            {cadence.status === "active" ? "Pausar" : "Ativar"}
          </button>
        </div>
      </div>

      {/* Config summary bar */}
      <div className="flex gap-4 mb-6 text-[12px]">
        <span className="px-3 py-1.5 rounded-full bg-[#f6f7ed] text-[#5f6368]">
          Janela: {cadence.send_start_hour}h-{cadence.send_end_hour}h
        </span>
        <span className="px-3 py-1.5 rounded-full bg-[#f6f7ed] text-[#5f6368]">
          Cooldown: {cadence.cooldown_hours}h
        </span>
        <span className="px-3 py-1.5 rounded-full bg-[#f6f7ed] text-[#5f6368]">
          Max: {cadence.max_messages} msgs
        </span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5">
        {(["steps", "leads", "config"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-[13px] font-medium transition-colors ${
              tab === t ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
            }`}
          >
            {t === "steps" ? "Steps" : t === "leads" ? "Leads" : "Configuracao"}
          </button>
        ))}
      </div>

      {tab === "steps" && <CadenceStepsTable cadenceId={cadenceId} />}
      {tab === "leads" && <CadenceEnrollmentsTable cadenceId={cadenceId} />}
      {tab === "config" && (
        <div className="card p-5 space-y-5">
          <CadenceTriggerConfig
            targetType={cadence.target_type}
            targetStage={cadence.target_stage}
            stagnationDays={cadence.stagnation_days}
            onChange={handleConfigChange}
          />

          <div className="border-t border-[#e5e5dc] pt-5 space-y-4">
            <h3 className="text-[13px] font-semibold uppercase tracking-wider text-[#9ca3af]">Configuracoes de envio</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[12px] text-[#5f6368] block mb-1">Janela inicio (hora)</label>
                <input type="number" value={cadence.send_start_hour} onChange={(e) => handleConfigChange("send_start_hour", Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] block mb-1">Janela fim (hora)</label>
                <input type="number" value={cadence.send_end_hour} onChange={(e) => handleConfigChange("send_end_hour", Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] block mb-1">Cooldown apos resposta (horas)</label>
                <input type="number" value={cadence.cooldown_hours} onChange={(e) => handleConfigChange("cooldown_hours", Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
              </div>
              <div>
                <label className="text-[12px] text-[#5f6368] block mb-1">Max mensagens por lead</label>
                <input type="number" value={cadence.max_messages} onChange={(e) => handleConfigChange("max_messages", Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
              </div>
            </div>
          </div>

          <div className="border-t border-[#e5e5dc] pt-5">
            <h3 className="text-[13px] font-semibold uppercase tracking-wider text-[#9ca3af] mb-3">Nome e descricao</h3>
            <input
              value={cadence.name}
              onChange={(e) => handleConfigChange("name", e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px] mb-3"
            />
            <textarea
              value={cadence.description || ""}
              onChange={(e) => handleConfigChange("description", e.target.value || null)}
              placeholder="Descricao da cadencia..."
              className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px] min-h-[60px]"
            />
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Delete old components**

```bash
rm crm/src/components/campaign-card.tsx
rm crm/src/components/campaign-kpis.tsx
rm crm/src/components/campaign-table.tsx
rm crm/src/components/create-campaign-modal.tsx
rm crm/src/components/cadence-leads-table.tsx
rm crm/src/components/cadence-steps-modal.tsx
rm crm/src/components/cadence-activity.tsx
```

- [ ] **Step 4: Remove old campaign imports from dashboard**

In `crm/src/app/(authenticated)/dashboard/page.tsx`, remove the `CampaignMetricsTable` import and its usage. The line:
```typescript
import { CampaignMetricsTable } from "@/components/campaign-table";
```
should be removed, and the `<CampaignMetricsTable campaigns={campaigns} />` at the bottom should be removed along with the `useRealtimeCampaigns` import and its hook call.

- [ ] **Step 5: Commit**

```bash
git add crm/src/app/\(authenticated\)/campanhas/ crm/src/app/\(authenticated\)/dashboard/page.tsx
git rm crm/src/components/campaign-card.tsx crm/src/components/campaign-kpis.tsx crm/src/components/campaign-table.tsx crm/src/components/create-campaign-modal.tsx crm/src/components/cadence-leads-table.tsx crm/src/components/cadence-steps-modal.tsx crm/src/components/cadence-activity.tsx
git commit -m "feat: rewrite campanhas pages, cleanup old campaign components"
```

---

### Task 13: Final cleanup — remove all old campaign references

**Files:**
- Search and fix all remaining imports of `Campaign`, `CadenceState`, `useRealtimeCampaigns`, `CAMPAIGN_STATUS_COLORS`, `CADENCE_STATUS_COLORS`, `CADENCE_STATUS_LABELS`

- [ ] **Step 1: Search for stale references**

Run:
```bash
cd crm && grep -r "Campaign\|CadenceState\|useRealtimeCampaigns\|CAMPAIGN_STATUS_COLORS\|CADENCE_STATUS_COLORS\|CADENCE_STATUS_LABELS\|campaign_id" src/ --include="*.ts" --include="*.tsx" -l
```

Fix each file found:
- Replace `Campaign` type with `Broadcast` or `Cadence` as appropriate
- Replace `CadenceState` with `CadenceEnrollment`
- Replace `useRealtimeCampaigns` with `useRealtimeBroadcasts` or `useRealtimeCadences`
- Replace `CAMPAIGN_STATUS_COLORS` with `BROADCAST_STATUS_COLORS`
- Replace `CADENCE_STATUS_COLORS` with `ENROLLMENT_STATUS_COLORS`
- Replace `CADENCE_STATUS_LABELS` with `ENROLLMENT_STATUS_LABELS`
- Remove `campaign_id` references from Lead-related code

- [ ] **Step 2: Run TypeScript compilation check**

```bash
cd crm && npx tsc --noEmit --pretty
```

Fix all errors.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "fix: remove all stale campaign references, fix TypeScript errors"
```

---

### Task 14: Final verification

- [ ] **Step 1: TypeScript check**

```bash
cd crm && npx tsc --noEmit --pretty
```

Expected: 0 errors.

- [ ] **Step 2: Python syntax check**

```bash
cd backend-evolution && python -m py_compile app/broadcast/router.py && python -m py_compile app/broadcast/worker.py && python -m py_compile app/broadcast/service.py && python -m py_compile app/cadence/service.py && python -m py_compile app/cadence/scheduler.py && python -m py_compile app/cadence/router.py && python -m py_compile app/buffer/processor.py && echo "OK"
```

Expected: OK.

- [ ] **Step 3: Verify pages load**

```bash
cd crm && npm run dev
```

Check:
- `/campanhas` — dashboard KPIs + tabs (Disparos / Cadencias)
- `/campanhas/[id]` — cadence detail with steps, leads, config tabs
- `/dashboard` — still works without old campaign table

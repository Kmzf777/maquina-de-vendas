# Cadenciamento por Stage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic follow-up cadencing per funnel stage to the campaign worker, so leads who don't respond receive pre-written nurturing messages until they engage or exhaust the cadence.

**Architecture:** Extend the existing campaign worker with a second processing cycle that checks `cadence_state` records and sends the next `cadence_steps` message when due. The webhook processor pauses cadence when a lead responds. A re-engagement check resumes cadence after a configurable cooldown if the lead goes silent again.

**Tech Stack:** FastAPI, Supabase PostgreSQL, Python asyncio, existing WhatsApp client (Evolution API)

**Spec:** `docs/superpowers/specs/2026-03-27-cadenciamento-por-stage-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend-evolution/migrations/003_cadence.sql` | Create | New tables + campaign columns + RPC functions |
| `backend-evolution/app/cadence/__init__.py` | Create | Package init |
| `backend-evolution/app/cadence/service.py` | Create | Cadence CRUD: create state, advance step, pause, resume, query |
| `backend-evolution/app/cadence/scheduler.py` | Create | Cadence processing loop: fetch due leads, send, advance, re-engage |
| `backend-evolution/app/cadence/router.py` | Create | REST API for cadence steps + status |
| `backend-evolution/app/campaign/worker.py` | Modify | Create cadence_state after template send; call scheduler |
| `backend-evolution/app/campaign/router.py` | Modify | Add cadence fields to CampaignCreate |
| `backend-evolution/app/buffer/processor.py` | Modify | Pause cadence when lead responds |
| `backend-evolution/app/main.py` | Modify | Mount cadence router |
| `backend-evolution/tests/test_cadence_service.py` | Create | Unit tests for cadence service |
| `backend-evolution/tests/test_cadence_scheduler.py` | Create | Unit tests for scheduler logic |
| `backend-evolution/tests/test_cadence_router.py` | Create | API endpoint tests |

---

### Task 1: Database Migration

**Files:**
- Create: `backend-evolution/migrations/003_cadence.sql`

- [ ] **Step 1: Write the migration SQL**

Create `backend-evolution/migrations/003_cadence.sql`:

```sql
-- 003_cadence.sql
-- Run this in Supabase SQL Editor after 002_crm_columns.sql

-- Cadence configuration columns on campaigns
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_interval_hours int DEFAULT 24;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_send_start_hour int DEFAULT 7;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_send_end_hour int DEFAULT 18;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_cooldown_hours int DEFAULT 48;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_max_messages int DEFAULT 8;

-- Cadence counters on campaigns
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_sent int DEFAULT 0;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_responded int DEFAULT 0;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_exhausted int DEFAULT 0;

-- Cadence steps: pre-written messages per stage per campaign
CREATE TABLE IF NOT EXISTS cadence_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id uuid REFERENCES campaigns(id) ON DELETE CASCADE,
    stage text NOT NULL,
    step_order int NOT NULL,
    message_text text NOT NULL,
    created_at timestamptz DEFAULT now(),
    UNIQUE(campaign_id, stage, step_order)
);

-- Cadence state: tracks each lead's progress through the cadence
CREATE TABLE IF NOT EXISTS cadence_state (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE UNIQUE,
    campaign_id uuid REFERENCES campaigns(id) ON DELETE CASCADE,
    current_step int DEFAULT 0,
    status text DEFAULT 'active',
    total_messages_sent int DEFAULT 0,
    max_messages int DEFAULT 8,
    next_send_at timestamptz,
    cooldown_until timestamptz,
    responded_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_cadence_steps_campaign ON cadence_steps(campaign_id);
CREATE INDEX IF NOT EXISTS idx_cadence_steps_lookup ON cadence_steps(campaign_id, stage, step_order);
CREATE INDEX IF NOT EXISTS idx_cadence_state_lead ON cadence_state(lead_id);
CREATE INDEX IF NOT EXISTS idx_cadence_state_status ON cadence_state(status);
CREATE INDEX IF NOT EXISTS idx_cadence_state_next_send ON cadence_state(next_send_at);

-- RPC: increment cadence_sent counter
CREATE OR REPLACE FUNCTION increment_cadence_sent(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET cadence_sent = cadence_sent + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;

-- RPC: increment cadence_responded counter
CREATE OR REPLACE FUNCTION increment_cadence_responded(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET cadence_responded = cadence_responded + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;

-- RPC: increment cadence_exhausted counter
CREATE OR REPLACE FUNCTION increment_cadence_exhausted(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET cadence_exhausted = cadence_exhausted + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;

-- Enable Realtime on new tables
ALTER PUBLICATION supabase_realtime ADD TABLE cadence_steps;
ALTER PUBLICATION supabase_realtime ADD TABLE cadence_state;
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/migrations/003_cadence.sql
git commit -m "feat: add cadence migration (steps, state, campaign columns, RPCs)"
```

---

### Task 2: Cadence Service

**Files:**
- Create: `backend-evolution/app/cadence/__init__.py`
- Create: `backend-evolution/app/cadence/service.py`
- Create: `backend-evolution/tests/test_cadence_service.py`

- [ ] **Step 1: Create package init**

Create `backend-evolution/app/cadence/__init__.py` (empty file).

- [ ] **Step 2: Write failing tests for cadence service**

Create `backend-evolution/tests/test_cadence_service.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.cadence.service import (
    create_cadence_state,
    get_cadence_state,
    pause_cadence,
    resume_cadence,
    advance_cadence,
    exhaust_cadence,
    cool_cadence,
    get_next_step,
    get_due_cadences,
    get_reengagement_cadences,
)


@pytest.fixture
def mock_sb():
    with patch("app.cadence.service.get_supabase") as mock:
        sb = MagicMock()
        mock.return_value = sb
        yield sb


class TestCreateCadenceState:
    def test_creates_state_with_correct_fields(self, mock_sb):
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "state-1", "lead_id": "lead-1", "campaign_id": "camp-1", "status": "active"}
        ]
        next_send = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)

        result = create_cadence_state("lead-1", "camp-1", max_messages=8, next_send_at=next_send)

        mock_sb.table.assert_called_with("cadence_state")
        insert_call = mock_sb.table.return_value.insert.call_args[0][0]
        assert insert_call["lead_id"] == "lead-1"
        assert insert_call["campaign_id"] == "camp-1"
        assert insert_call["status"] == "active"
        assert insert_call["current_step"] == 0
        assert insert_call["total_messages_sent"] == 0
        assert insert_call["max_messages"] == 8
        assert result["id"] == "state-1"


class TestGetCadenceState:
    def test_returns_state_for_lead(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "state-1", "status": "active"}
        ]
        result = get_cadence_state("lead-1")
        assert result["status"] == "active"

    def test_returns_none_when_no_state(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        result = get_cadence_state("lead-1")
        assert result is None


class TestPauseCadence:
    def test_sets_responded_status(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "state-1", "status": "responded"}
        ]
        result = pause_cadence("state-1")
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "responded"
        assert "responded_at" in update_call


class TestResumeCadence:
    def test_sets_active_status_and_next_send(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "state-1", "status": "active"}
        ]
        next_send = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)
        result = resume_cadence("state-1", next_send_at=next_send)
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "active"
        assert update_call["cooldown_until"] is None


class TestAdvanceCadence:
    def test_increments_step_and_messages_sent(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "state-1", "current_step": 2, "total_messages_sent": 2}
        ]
        next_send = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
        result = advance_cadence("state-1", new_step=2, total_sent=2, next_send_at=next_send)
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["current_step"] == 2
        assert update_call["total_messages_sent"] == 2


class TestGetNextStep:
    def test_returns_step_for_campaign_stage_order(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "step-1", "message_text": "Oi, tudo bem?", "step_order": 1}
        ]
        result = get_next_step("camp-1", "atacado", step_order=1)
        assert result["message_text"] == "Oi, tudo bem?"

    def test_returns_none_when_no_more_steps(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        result = get_next_step("camp-1", "atacado", step_order=99)
        assert result is None


class TestGetDueCadences:
    def test_returns_active_cadences_due_now(self, mock_sb):
        now = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)
        mock_sb.table.return_value.select.return_value.eq.return_value.lte.return_value.limit.return_value.execute.return_value.data = [
            {"id": "state-1", "lead_id": "lead-1"}
        ]
        result = get_due_cadences(now, limit=10)
        assert len(result) == 1


class TestGetReengagementCadences:
    def test_returns_responded_cadences_past_cooldown(self, mock_sb):
        now = datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc)
        mock_sb.table.return_value.select.return_value.eq.return_value.lte.return_value.execute.return_value.data = [
            {"id": "state-1", "lead_id": "lead-1", "status": "responded"}
        ]
        result = get_reengagement_cadences(now)
        assert len(result) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend-evolution && python -m pytest tests/test_cadence_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cadence.service'`

- [ ] **Step 4: Write the cadence service**

Create `backend-evolution/app/cadence/service.py`:

```python
from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase


def create_cadence_state(
    lead_id: str,
    campaign_id: str,
    max_messages: int = 8,
    next_send_at: datetime | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    data = {
        "lead_id": lead_id,
        "campaign_id": campaign_id,
        "status": "active",
        "current_step": 0,
        "total_messages_sent": 0,
        "max_messages": max_messages,
        "next_send_at": next_send_at.isoformat() if next_send_at else None,
    }
    result = sb.table("cadence_state").insert(data).execute()
    return result.data[0]


def get_cadence_state(lead_id: str, status: str = "active") -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("status", status)
        .execute()
    )
    return result.data[0] if result.data else None


def get_cadence_state_any(lead_id: str) -> dict[str, Any] | None:
    """Get cadence state regardless of status (active or responded)."""
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*")
        .eq("lead_id", lead_id)
        .in_("status", ["active", "responded"])
        .execute()
    )
    return result.data[0] if result.data else None


def pause_cadence(state_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({
            "status": "responded",
            "responded_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def resume_cadence(state_id: str, next_send_at: datetime) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({
            "status": "active",
            "next_send_at": next_send_at.isoformat(),
            "cooldown_until": None,
        })
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def advance_cadence(
    state_id: str,
    new_step: int,
    total_sent: int,
    next_send_at: datetime,
) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({
            "current_step": new_step,
            "total_messages_sent": total_sent,
            "next_send_at": next_send_at.isoformat(),
        })
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def exhaust_cadence(state_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({"status": "exhausted"})
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def cool_cadence(state_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({"status": "cooled"})
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def get_next_step(campaign_id: str, stage: str, step_order: int) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("stage", stage)
        .eq("step_order", step_order)
        .execute()
    )
    return result.data[0] if result.data else None


def get_due_cadences(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*, leads!inner(phone, stage, human_control), campaigns!inner(status, cadence_send_start_hour, cadence_send_end_hour, cadence_interval_hours)")
        .eq("status", "active")
        .lte("next_send_at", now.isoformat())
        .limit(limit)
        .execute()
    )
    return result.data


def get_reengagement_cadences(now: datetime) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*, leads!inner(phone, last_msg_at, human_control), campaigns!inner(status, cadence_cooldown_hours)")
        .eq("status", "responded")
        .lte("responded_at", now.isoformat())
        .execute()
    )
    return result.data
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend-evolution && python -m pytest tests/test_cadence_service.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend-evolution/app/cadence/__init__.py backend-evolution/app/cadence/service.py backend-evolution/tests/test_cadence_service.py
git commit -m "feat: add cadence service with CRUD operations and queries"
```

---

### Task 3: Cadence Scheduler

**Files:**
- Create: `backend-evolution/app/cadence/scheduler.py`
- Create: `backend-evolution/tests/test_cadence_scheduler.py`

- [ ] **Step 1: Write failing tests for the scheduler**

Create `backend-evolution/tests/test_cadence_scheduler.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.cadence.scheduler import (
    process_due_cadences,
    process_reengagements,
    is_within_send_window,
    calculate_next_send_at,
)


class TestIsWithinSendWindow:
    def test_within_window(self):
        # 10:00 BRT (13:00 UTC) — within 7-18
        now_utc = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is True

    def test_before_window(self):
        # 05:00 BRT (08:00 UTC) — before 7
        now_utc = datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is False

    def test_after_window(self):
        # 19:00 BRT (22:00 UTC) — after 18
        now_utc = datetime(2026, 3, 28, 22, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is False

    def test_at_start_boundary(self):
        # 07:00 BRT (10:00 UTC) — exactly at start
        now_utc = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is True

    def test_at_end_boundary(self):
        # 18:00 BRT (21:00 UTC) — exactly at end, should be False (end is exclusive)
        now_utc = datetime(2026, 3, 28, 21, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is False


class TestCalculateNextSendAt:
    def test_next_send_within_window(self):
        # 10:00 BRT, interval 24h → tomorrow 10:00 BRT
        now_utc = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        result = calculate_next_send_at(now_utc, interval_hours=24, start_hour=7, end_hour=18)
        expected = datetime(2026, 3, 29, 13, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_next_send_lands_before_window(self):
        # 08:00 BRT (11:00 UTC), interval 20h → would be 04:00 BRT next day → push to 07:00 BRT (10:00 UTC)
        now_utc = datetime(2026, 3, 28, 11, 0, tzinfo=timezone.utc)
        result = calculate_next_send_at(now_utc, interval_hours=20, start_hour=7, end_hour=18)
        expected = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_next_send_lands_after_window(self):
        # 17:00 BRT (20:00 UTC), interval 3h → would be 20:00 BRT → push to 07:00 BRT next day (10:00 UTC)
        now_utc = datetime(2026, 3, 28, 20, 0, tzinfo=timezone.utc)
        result = calculate_next_send_at(now_utc, interval_hours=3, start_hour=7, end_hour=18)
        expected = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
        assert result == expected


@pytest.fixture
def mock_deps():
    with patch("app.cadence.scheduler.get_due_cadences") as mock_due, \
         patch("app.cadence.scheduler.get_next_step") as mock_step, \
         patch("app.cadence.scheduler.advance_cadence") as mock_advance, \
         patch("app.cadence.scheduler.cool_cadence") as mock_cool, \
         patch("app.cadence.scheduler.exhaust_cadence") as mock_exhaust, \
         patch("app.cadence.scheduler.save_message") as mock_save_msg, \
         patch("app.cadence.scheduler.send_text", new_callable=AsyncMock) as mock_send, \
         patch("app.cadence.scheduler.get_supabase") as mock_sb:
        yield {
            "get_due": mock_due,
            "get_step": mock_step,
            "advance": mock_advance,
            "cool": mock_cool,
            "exhaust": mock_exhaust,
            "save_msg": mock_save_msg,
            "send": mock_send,
            "sb": mock_sb.return_value,
        }


class TestProcessDueCadences:
    @pytest.mark.anyio
    async def test_sends_message_and_advances(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)  # 10:00 BRT
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]
        mock_deps["get_step"].return_value = {
            "id": "step-1", "message_text": "Oi! Viu nosso catalogo?", "step_order": 1,
        }

        await process_due_cadences(now)

        mock_deps["send"].assert_called_once_with("5511999999999", "Oi! Viu nosso catalogo?")
        mock_deps["advance"].assert_called_once()
        mock_deps["save_msg"].assert_called_once()

    @pytest.mark.anyio
    async def test_skips_paused_campaign(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "paused", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]

        await process_due_cadences(now)

        mock_deps["send"].assert_not_called()

    @pytest.mark.anyio
    async def test_skips_human_controlled_lead(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": True},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]

        await process_due_cadences(now)

        mock_deps["send"].assert_not_called()

    @pytest.mark.anyio
    async def test_cools_when_no_more_steps(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 3,
            "total_messages_sent": 3,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]
        mock_deps["get_step"].return_value = None  # No more steps

        await process_due_cadences(now)

        mock_deps["cool"].assert_called_once_with("state-1")
        mock_deps["send"].assert_not_called()

    @pytest.mark.anyio
    async def test_exhausts_when_max_messages_reached(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 7,
            "total_messages_sent": 7,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]
        mock_deps["get_step"].return_value = {
            "id": "step-8", "message_text": "Ultima tentativa!", "step_order": 8,
        }

        await process_due_cadences(now)

        # Should send the message (it's the 8th = max) then exhaust
        mock_deps["send"].assert_called_once()
        mock_deps["exhaust"].assert_called_once_with("state-1")

    @pytest.mark.anyio
    async def test_skips_outside_send_window(self, mock_deps):
        now = datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc)  # 05:00 BRT — before window
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]

        await process_due_cadences(now)

        mock_deps["send"].assert_not_called()


class TestProcessReengagements:
    @pytest.mark.anyio
    async def test_resumes_cadence_after_cooldown(self, mock_deps):
        now = datetime(2026, 3, 30, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = []  # Not used here

        with patch("app.cadence.scheduler.get_reengagement_cadences") as mock_reengage, \
             patch("app.cadence.scheduler.resume_cadence") as mock_resume:
            mock_reengage.return_value = [{
                "id": "state-1",
                "lead_id": "lead-1",
                "campaign_id": "camp-1",
                "responded_at": "2026-03-28T13:00:00+00:00",
                "total_messages_sent": 2,
                "max_messages": 8,
                "current_step": 0,
                "leads": {"phone": "5511999999999", "last_msg_at": "2026-03-28T13:00:00+00:00", "human_control": False},
                "campaigns": {"status": "running", "cadence_cooldown_hours": 48},
            }]

            await process_reengagements(now)

            mock_resume.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend-evolution && python -m pytest tests/test_cadence_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cadence.scheduler'`

- [ ] **Step 3: Write the cadence scheduler**

Create `backend-evolution/app/cadence/scheduler.py`:

```python
import logging
import random
import asyncio
from datetime import datetime, timezone, timedelta

from app.cadence.service import (
    get_due_cadences,
    get_reengagement_cadences,
    get_next_step,
    advance_cadence,
    cool_cadence,
    exhaust_cadence,
    resume_cadence,
)
from app.leads.service import save_message
from app.whatsapp.client import send_text
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# Brazil timezone offset (UTC-3)
BRT_OFFSET = timedelta(hours=-3)


def is_within_send_window(now_utc: datetime, start_hour: int = 7, end_hour: int = 18) -> bool:
    """Check if current time in BRT is within the send window."""
    brt_time = now_utc + BRT_OFFSET
    return start_hour <= brt_time.hour < end_hour


def calculate_next_send_at(
    now_utc: datetime,
    interval_hours: int,
    start_hour: int = 7,
    end_hour: int = 18,
) -> datetime:
    """Calculate the next send time, respecting the send window."""
    candidate = now_utc + timedelta(hours=interval_hours)
    candidate_brt = candidate + BRT_OFFSET

    if candidate_brt.hour < start_hour:
        # Before window — push to start_hour same day
        candidate_brt = candidate_brt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        return candidate_brt - BRT_OFFSET
    elif candidate_brt.hour >= end_hour:
        # After window — push to start_hour next day
        next_day = candidate_brt + timedelta(days=1)
        next_day = next_day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        return next_day - BRT_OFFSET

    return candidate


async def process_due_cadences(now: datetime | None = None):
    """Process all cadence states that are due for sending."""
    now = now or datetime.now(timezone.utc)
    cadences = get_due_cadences(now, limit=10)

    for cadence in cadences:
        lead = cadence["leads"]
        campaign = cadence["campaigns"]

        # Skip guards
        if campaign["status"] != "running":
            logger.info(f"[CADENCE] Skipping {lead['phone']} — campaign not running")
            continue
        if lead.get("human_control"):
            logger.info(f"[CADENCE] Skipping {lead['phone']} — human control active")
            continue
        if not is_within_send_window(now, campaign["cadence_send_start_hour"], campaign["cadence_send_end_hour"]):
            logger.info(f"[CADENCE] Skipping {lead['phone']} — outside send window")
            continue

        stage = lead["stage"]
        next_step_order = cadence["current_step"] + 1
        step = get_next_step(cadence["campaign_id"], stage, next_step_order)

        if step is None:
            # No more steps for this stage
            cool_cadence(cadence["id"])
            sb = get_supabase()
            sb.rpc("increment_cadence_exhausted", {"campaign_id_param": cadence["campaign_id"]}).execute()
            logger.info(f"[CADENCE] Lead {lead['phone']} cooled — no more steps for stage {stage}")
            continue

        try:
            await send_text(lead["phone"], step["message_text"])

            new_total = cadence["total_messages_sent"] + 1

            # Save to message history
            save_message(
                lead_id=cadence["lead_id"],
                role="assistant",
                content=step["message_text"],
                stage=stage,
            )

            # Increment campaign counter
            sb = get_supabase()
            sb.rpc("increment_cadence_sent", {"campaign_id_param": cadence["campaign_id"]}).execute()

            # Check if exhausted after this send
            if new_total >= cadence["max_messages"]:
                exhaust_cadence(cadence["id"])
                sb.rpc("increment_cadence_exhausted", {"campaign_id_param": cadence["campaign_id"]}).execute()
                logger.info(f"[CADENCE] Lead {lead['phone']} exhausted — {new_total} messages sent")
            else:
                next_send = calculate_next_send_at(
                    now,
                    campaign["cadence_interval_hours"],
                    campaign["cadence_send_start_hour"],
                    campaign["cadence_send_end_hour"],
                )
                advance_cadence(cadence["id"], new_step=next_step_order, total_sent=new_total, next_send_at=next_send)
                logger.info(f"[CADENCE] Sent step {next_step_order} to {lead['phone']} (stage={stage})")

        except Exception as e:
            logger.error(f"[CADENCE] Failed to send to {lead['phone']}: {e}", exc_info=True)

        # Random delay between sends (2-5s)
        await asyncio.sleep(random.randint(2, 5))


async def process_reengagements(now: datetime | None = None):
    """Check for leads that responded but went silent — resume their cadence."""
    now = now or datetime.now(timezone.utc)
    cadences = get_reengagement_cadences(now)

    for cadence in cadences:
        lead = cadence["leads"]
        campaign = cadence["campaigns"]

        if campaign["status"] != "running":
            continue
        if lead.get("human_control"):
            continue
        if cadence["total_messages_sent"] >= cadence["max_messages"]:
            exhaust_cadence(cadence["id"])
            continue

        # Check if lead actually went silent (last_msg_at hasn't changed since responded_at)
        responded_at = cadence["responded_at"]
        last_msg_at = lead.get("last_msg_at")
        cooldown_hours = campaign["cadence_cooldown_hours"]

        # Parse responded_at if string
        if isinstance(responded_at, str):
            from dateutil.parser import parse
            responded_at = parse(responded_at)

        cooldown_deadline = responded_at + timedelta(hours=cooldown_hours)
        if now < cooldown_deadline:
            continue

        # If last_msg_at is after responded_at, lead is still active — skip
        if last_msg_at:
            if isinstance(last_msg_at, str):
                from dateutil.parser import parse
                last_msg_at = parse(last_msg_at)
            if last_msg_at > responded_at:
                continue

        # Resume cadence — reset step to 0 for current stage
        next_send = calculate_next_send_at(now, 0, 7, 18)  # Send ASAP within window
        resume_cadence(cadence["id"], next_send_at=next_send)
        logger.info(f"[CADENCE] Lead {lead['phone']} re-engaged — resuming cadence")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend-evolution && python -m pytest tests/test_cadence_scheduler.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend-evolution/app/cadence/scheduler.py backend-evolution/tests/test_cadence_scheduler.py
git commit -m "feat: add cadence scheduler with send window, reengagement, and exhaustion logic"
```

---

### Task 4: Integrate Cadence into Campaign Worker

**Files:**
- Modify: `backend-evolution/app/campaign/worker.py`

- [ ] **Step 1: Update worker to create cadence state after template send and call scheduler**

Edit `backend-evolution/app/campaign/worker.py` — replace the entire file:

```python
import asyncio
import logging
import random

from app.config import settings
from app.db.supabase import get_supabase
from app.whatsapp.client import send_template
from app.cadence.service import create_cadence_state
from app.cadence.scheduler import process_due_cadences, process_reengagements

from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


async def run_worker():
    """Main worker loop: polls for running campaigns, sends templates, processes cadence."""
    logger.info("Campaign worker started")

    while True:
        try:
            await process_campaigns()
            await process_due_cadences()
            await process_reengagements()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)


async def process_campaigns():
    """Find running campaigns and send pending templates."""
    sb = get_supabase()

    # Get running campaigns
    campaigns = (
        sb.table("campaigns")
        .select("*")
        .eq("status", "running")
        .execute()
        .data
    )

    for campaign in campaigns:
        await process_single_campaign(campaign)


async def process_single_campaign(campaign: dict):
    """Process one campaign: send templates to pending leads."""
    sb = get_supabase()
    campaign_id = campaign["id"]

    # Get next batch of unsent leads
    leads = (
        sb.table("leads")
        .select("id, phone, stage")
        .eq("campaign_id", campaign_id)
        .eq("status", "imported")
        .limit(10)
        .execute()
        .data
    )

    if not leads:
        # Check if there are still active cadences before marking completed
        active_cadences = (
            sb.table("cadence_state")
            .select("id")
            .eq("campaign_id", campaign_id)
            .eq("status", "active")
            .limit(1)
            .execute()
            .data
        )
        if not active_cadences:
            sb.table("campaigns").update({"status": "completed"}).eq("id", campaign_id).execute()
            logger.info(f"Campaign {campaign_id} completed")
        return

    for lead in leads:
        # Check if campaign is still running (might have been paused)
        current = sb.table("campaigns").select("status").eq("id", campaign_id).single().execute().data
        if current["status"] != "running":
            logger.info(f"Campaign {campaign_id} paused, stopping")
            return

        try:
            await send_template(
                to=lead["phone"],
                template_name=campaign["template_name"],
                components=campaign.get("template_params", {}).get("components"),
            )
            sb.table("leads").update({"status": "template_sent"}).eq("id", lead["id"]).execute()

            # Update sent counter
            sb.rpc("increment_campaign_sent", {"campaign_id_param": campaign_id}).execute()

            # Create cadence state for this lead
            now = datetime.now(timezone.utc)
            interval = campaign.get("cadence_interval_hours", 24)
            max_msgs = campaign.get("cadence_max_messages", 8)

            from app.cadence.scheduler import calculate_next_send_at
            next_send = calculate_next_send_at(
                now, interval,
                campaign.get("cadence_send_start_hour", 7),
                campaign.get("cadence_send_end_hour", 18),
            )

            try:
                create_cadence_state(
                    lead_id=lead["id"],
                    campaign_id=campaign_id,
                    max_messages=max_msgs,
                    next_send_at=next_send,
                )
            except Exception as ce:
                # Lead might already have a cadence state (duplicate import)
                logger.warning(f"Could not create cadence state for {lead['phone']}: {ce}")

            logger.info(f"Template sent to {lead['phone']}")

        except Exception as e:
            logger.error(f"Failed to send to {lead['phone']}: {e}")
            sb.table("leads").update({"status": "failed"}).eq("id", lead["id"]).execute()

        # Wait between sends (randomized interval)
        interval = random.randint(
            campaign.get("send_interval_min", 3),
            campaign.get("send_interval_max", 8),
        )
        await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/app/campaign/worker.py
git commit -m "feat: integrate cadence creation and scheduling into campaign worker"
```

---

### Task 5: Pause Cadence on Lead Response

**Files:**
- Modify: `backend-evolution/app/buffer/processor.py`

- [ ] **Step 1: Add cadence pause logic to processor**

Edit `backend-evolution/app/buffer/processor.py` — add cadence pause after lead lookup, before agent runs. The new file:

```python
import asyncio
import logging

from app.leads.service import get_or_create_lead, activate_lead, update_lead
from app.agent.orchestrator import run_agent
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay
from app.whatsapp.client import send_text
from app.whatsapp.media import transcribe_audio, describe_image
from app.cadence.service import get_cadence_state, pause_cadence
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


async def process_buffered_messages(phone: str, combined_text: str):
    """Process accumulated buffer messages: resolve media, run agent, humanize, send."""
    try:
        # Resolve any media placeholders
        resolved_text = await _resolve_media(combined_text)

        # Get or create lead
        lead = get_or_create_lead(phone)

        # Pause cadence if active
        cadence = get_cadence_state(lead["id"])
        if cadence:
            pause_cadence(cadence["id"])
            sb = get_supabase()
            sb.rpc("increment_cadence_responded", {"campaign_id_param": cadence["campaign_id"]}).execute()
            logger.info(f"[CADENCE] Lead {phone} responded — pausing cadence")

        # Activate lead if pending/template_sent
        if lead.get("status") in ("imported", "template_sent"):
            lead = activate_lead(lead["id"])

        # Run agent
        response = await run_agent(lead, resolved_text)

        # Humanize and send
        bubbles = split_into_bubbles(response)
        for bubble in bubbles:
            delay = calculate_typing_delay(bubble)
            await asyncio.sleep(delay)
            await send_text(phone, bubble)

        # Update last_msg timestamp
        from datetime import datetime, timezone
        update_lead(lead["id"], last_msg_at=datetime.now(timezone.utc).isoformat())

    except Exception as e:
        logger.error(f"Error processing messages for {phone}: {e}", exc_info=True)


async def _resolve_media(text: str) -> str:
    """Replace media placeholders with actual content."""
    import re

    # Pattern: [audio: media_url=xxx] or [image: media_url=xxx]
    audio_pattern = r"\[audio: media_url=(\S+)\]"
    image_pattern = r"\[image: media_url=(\S+)\]"

    for match in re.finditer(audio_pattern, text):
        media_url = match.group(1)
        try:
            transcription = await transcribe_audio(media_url)
            text = text.replace(match.group(0), f"[audio transcrito: {transcription}]")
        except Exception as e:
            logger.warning(f"Failed to transcribe audio: {e}")
            text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for match in re.finditer(image_pattern, text):
        media_url = match.group(1)
        try:
            description = await describe_image(media_url)
            text = text.replace(match.group(0), f"[imagem recebida: {description}]")
        except Exception as e:
            logger.warning(f"Failed to describe image: {e}")
            text = text.replace(match.group(0), "[imagem: nao foi possivel descrever]")

    return text
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/app/buffer/processor.py
git commit -m "feat: pause cadence when lead responds via webhook"
```

---

### Task 6: Cadence REST API

**Files:**
- Create: `backend-evolution/app/cadence/router.py`
- Modify: `backend-evolution/app/campaign/router.py`
- Modify: `backend-evolution/app/main.py`
- Create: `backend-evolution/tests/test_cadence_router.py`

- [ ] **Step 1: Write failing tests for cadence API**

Create `backend-evolution/tests/test_cadence_router.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_redis():
    """Mock Redis for all tests so FastAPI lifespan doesn't fail."""
    with patch("app.main.aioredis") as mock:
        mock_r = MagicMock()
        mock.from_url.return_value = mock_r
        mock_r.set = MagicMock()
        mock_r.close = MagicMock()
        yield mock_r


@pytest.fixture
def mock_sb():
    with patch("app.cadence.router.get_supabase") as mock:
        sb = MagicMock()
        mock.return_value = sb
        yield sb


class TestListCadenceSteps:
    def test_returns_steps_grouped(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {"id": "s1", "stage": "atacado", "step_order": 1, "message_text": "Oi!"},
            {"id": "s2", "stage": "atacado", "step_order": 2, "message_text": "Viu?"},
        ]
        resp = client.get("/api/campaigns/camp-1/cadence")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2


class TestCreateCadenceStep:
    def test_creates_step(self, mock_sb):
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "s1", "stage": "atacado", "step_order": 1, "message_text": "Oi!"}
        ]
        resp = client.post("/api/campaigns/camp-1/cadence", json={
            "stage": "atacado", "step_order": 1, "message_text": "Oi!"
        })
        assert resp.status_code == 200
        assert resp.json()["stage"] == "atacado"


class TestCadenceStatus:
    def test_returns_status_summary(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"status": "active", "leads": {"stage": "atacado"}},
            {"status": "responded", "leads": {"stage": "atacado"}},
            {"status": "active", "leads": {"stage": "private_label"}},
        ]
        resp = client.get("/api/campaigns/camp-1/cadence/status")
        assert resp.status_code == 200
```

- [ ] **Step 2: Write the cadence router**

Create `backend-evolution/app/cadence/router.py`:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/campaigns/{campaign_id}/cadence", tags=["cadence"])


class CadenceStepCreate(BaseModel):
    stage: str
    step_order: int
    message_text: str


class CadenceStepUpdate(BaseModel):
    message_text: str


@router.get("")
async def list_cadence_steps(campaign_id: str):
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .select("*")
        .eq("campaign_id", campaign_id)
        .order("stage")
        .order("step_order")
        .execute()
    )
    return {"data": result.data}


@router.post("")
async def create_cadence_step(campaign_id: str, step: CadenceStepCreate):
    sb = get_supabase()
    data = step.model_dump()
    data["campaign_id"] = campaign_id
    result = sb.table("cadence_steps").insert(data).execute()
    return result.data[0]


@router.put("/{step_id}")
async def update_cadence_step(campaign_id: str, step_id: str, step: CadenceStepUpdate):
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .update({"message_text": step.message_text})
        .eq("id", step_id)
        .eq("campaign_id", campaign_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Step nao encontrado")
    return result.data[0]


@router.delete("/{step_id}")
async def delete_cadence_step(campaign_id: str, step_id: str):
    sb = get_supabase()
    sb.table("cadence_steps").delete().eq("id", step_id).eq("campaign_id", campaign_id).execute()
    return {"deleted": True}


@router.get("/status")
async def cadence_status(campaign_id: str):
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("status, leads(stage)")
        .eq("campaign_id", campaign_id)
        .execute()
    )

    # Group by stage and status
    summary: dict[str, dict[str, int]] = {}
    for row in result.data:
        stage = row.get("leads", {}).get("stage", "unknown")
        status = row["status"]
        if stage not in summary:
            summary[stage] = {"active": 0, "responded": 0, "exhausted": 0, "cooled": 0}
        if status in summary[stage]:
            summary[stage][status] += 1

    return {"data": summary}


# Lead-level cadence state (mounted separately)
lead_router = APIRouter(prefix="/api/leads/{lead_id}/cadence", tags=["cadence"])


@lead_router.get("")
async def get_lead_cadence(lead_id: str):
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*, cadence_steps(stage, step_order, message_text)")
        .eq("lead_id", lead_id)
        .execute()
    )
    return {"data": result.data[0] if result.data else None}
```

- [ ] **Step 3: Update CampaignCreate model with cadence fields**

Edit `backend-evolution/app/campaign/router.py` — update the `CampaignCreate` model (lines 10-15):

Replace:
```python
class CampaignCreate(BaseModel):
    name: str
    template_name: str
    template_params: dict | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8
```

With:
```python
class CampaignCreate(BaseModel):
    name: str
    template_name: str
    template_params: dict | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8
    cadence_interval_hours: int = 24
    cadence_send_start_hour: int = 7
    cadence_send_end_hour: int = 18
    cadence_cooldown_hours: int = 48
    cadence_max_messages: int = 8
```

- [ ] **Step 4: Mount cadence routers in main.py**

Edit `backend-evolution/app/main.py` — add after line 41 (`from app.campaign.router import router as campaign_router`):

Replace:
```python
from app.webhook.router import router as webhook_router
from app.leads.router import router as leads_router
from app.campaign.router import router as campaign_router

app.include_router(webhook_router)
app.include_router(leads_router)
app.include_router(campaign_router)
```

With:
```python
from app.webhook.router import router as webhook_router
from app.leads.router import router as leads_router
from app.campaign.router import router as campaign_router
from app.cadence.router import router as cadence_router, lead_router as cadence_lead_router

app.include_router(webhook_router)
app.include_router(leads_router)
app.include_router(campaign_router)
app.include_router(cadence_router)
app.include_router(cadence_lead_router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend-evolution && python -m pytest tests/test_cadence_router.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend-evolution/app/cadence/router.py backend-evolution/app/campaign/router.py backend-evolution/app/main.py backend-evolution/tests/test_cadence_router.py
git commit -m "feat: add cadence REST API and mount routers"
```

---

### Task 7: Add python-dateutil Dependency

**Files:**
- Modify: `backend-evolution/requirements.txt`

- [ ] **Step 1: Add python-dateutil to requirements**

The scheduler uses `dateutil.parser.parse` for ISO datetime string parsing. Add `python-dateutil` to `backend-evolution/requirements.txt`.

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/requirements.txt
git commit -m "chore: add python-dateutil dependency for cadence scheduler"
```

---

### Task 8: Run Full Test Suite and Verify

- [ ] **Step 1: Run all tests**

Run: `cd backend-evolution && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify imports work**

Run: `cd backend-evolution && python -c "from app.cadence.service import create_cadence_state; from app.cadence.scheduler import process_due_cadences; from app.cadence.router import router; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 3: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: resolve any issues from full test run"
```

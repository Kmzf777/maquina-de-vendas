# Cadence/Automation Engine Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the custom `/campanhas > cadências` automation engine safe against duplicate/dropped WhatsApp sends, starvation, and infinite loops, and bring it to n8n-grade runtime safety + observability.

**Architecture:** The live engine is `automation/engine.py::process_due_enrollments` (called by `broadcast/worker.py::run_worker`), fed by `automation/triggers.py` (event + polling enrollment). An enrollment (`campaign_enrollments`) is a cursor (`current_node_id` + `next_execute_at`) advanced one node per tick. We add: atomic claim, node-level send idempotency, crash-recovery, a unique-enrollment index, fair ordering, a step/loop guard, permanent-error cancel, weekend clamp, conversion cascade, and a per-node execution log — mirroring the already-hardened `follow_up` system (`follow_up/service.py`, `follow_up/scheduler.py`).

**Tech Stack:** Python 3, FastAPI, Supabase (Postgres) via `app.db.supabase.get_supabase`, pytest (`backend/tests`), Next.js App Router (frontend).

**Audit source:** findings F1–F15, see conversation audit + `docs/superpowers/specs` (this plan is the executable spec).

**Ground rules for every task:**
- Run tests from `backend/`: `cd backend && python -m pytest tests/<file> -v`.
- Env tag: code uses `_ENV_TAG` (`"dev"` if `settings.is_dev_env` else `"production"`). Tests stub Supabase like existing `backend/tests/test_automation_*.py`.
- **Migrations are idempotent** (`IF NOT EXISTS`) and must be safe to re-apply. Do NOT auto-apply to Supabase — they are applied manually by the user. Mirror `backend/migrations/20260527_automation_campaigns_schema.sql`.
- Commit after every green task with the shown message.
- Follow existing patterns; do not restructure unrelated code.

---

## File Structure

- `backend/migrations/20260709_cadence_enrollment_hardening.sql` — **new**: adds columns + unique index + execution-log table.
- `backend/app/campaigns/service.py` — **modify**: `create_enrollment` conflict-safe; `get_due_enrollments` ordering; new claim/recovery/idempotency helpers.
- `backend/app/automation/engine.py` — **modify**: claim before process, idempotent send, step guard, window-skip fix, permanent-error handling, weekend clamp, conversion cascade, execution-log writes.
- `backend/app/automation/retry.py` — **modify**: absorb `decide_failure_update` + `_is_permanent_error` (shared).
- `backend/app/automation/triggers.py` — **modify**: keyword word-boundary match (F11).
- `backend/app/campaigns/worker.py` — **modify**: delete dead duplicate engine (F7); keep `_execute_send_node`, `handle_campaign_reply`.
- `backend/app/campaigns/execution_log.py` — **new**: thin writer for the execution log.
- `frontend/src/app/(authenticated)/campanhas/cadencias/[id]/page.tsx` (+ a small component) — **modify/new**: execution-log panel (F13 UI).
- Tests: `backend/tests/test_cadence_hardening_*.py` (new, one per task area).

---

## Task 0: Schema migration (columns + unique index + execution log)

**Files:**
- Create: `backend/migrations/20260709_cadence_enrollment_hardening.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 20260709_cadence_enrollment_hardening.sql
-- Endurece o motor de cadências (campaign_enrollments): claim atômico, idempotência
-- por nó, guarda de loop, índice único de matrícula ativa, e log de execução por nó.
-- Idempotente: seguro reaplicar. Aplicar em HOMOLOG e depois PROD (paridade de schema).

-- 1) Colunas de runtime na matrícula.
ALTER TABLE campaign_enrollments
    ADD COLUMN IF NOT EXISTS claimed_at        timestamptz NULL,
    ADD COLUMN IF NOT EXISTS last_sent_node_id uuid NULL,
    ADD COLUMN IF NOT EXISTS last_sent_wamid   text NULL,
    ADD COLUMN IF NOT EXISTS step_count        int NOT NULL DEFAULT 0;

COMMENT ON COLUMN campaign_enrollments.claimed_at IS
    'Instante do claim atômico do tick atual. NULL = livre. Stale (> 5min) = worker morreu.';
COMMENT ON COLUMN campaign_enrollments.last_sent_node_id IS
    'Nó cujo envio JÁ foi despachado à Meta neste passo (idempotência anti-reenvio no crash).';
COMMENT ON COLUMN campaign_enrollments.step_count IS
    'Nós executados por esta matrícula (guarda anti-loop). Estoura MAX_STEPS → failed.';

-- 2) DEDUP antes do índice único: cancela matrículas ativas/pausadas duplicadas
--    (mantém a mais recente por campaign_id+lead_id). Necessário senão o índice falha.
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY campaign_id, lead_id
               ORDER BY enrolled_at DESC
           ) AS rn
    FROM campaign_enrollments
    WHERE status IN ('active', 'paused')
)
UPDATE campaign_enrollments e
SET status = 'cancelled'
FROM ranked r
WHERE e.id = r.id AND r.rn > 1;

-- 3) Índice único parcial: no máx. 1 matrícula viva por (campanha, lead).
CREATE UNIQUE INDEX IF NOT EXISTS uq_campaign_enrollments_active
    ON campaign_enrollments (campaign_id, lead_id)
    WHERE status IN ('active', 'paused');

-- 4) Índice do claim/recovery (varredura de presos).
CREATE INDEX IF NOT EXISTS idx_campaign_enrollments_claimed
    ON campaign_enrollments (status, env_tag, claimed_at)
    WHERE status = 'active';

-- 5) Opt-in de fim de semana por campanha (default = comportamento atual: envia todo dia).
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS skip_weekends boolean NOT NULL DEFAULT false;

-- 6) Log de execução por nó (observabilidade estilo n8n).
CREATE TABLE IF NOT EXISTS campaign_execution_log (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id uuid NOT NULL REFERENCES campaign_enrollments(id) ON DELETE CASCADE,
    campaign_id   uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id       uuid NULL REFERENCES leads(id) ON DELETE SET NULL,
    node_id       uuid NULL,
    node_type     text NULL,
    status        text NOT NULL,           -- 'done' | 'failed' | 'skipped'
    log           text NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_campaign_exec_log_campaign
    ON campaign_execution_log (campaign_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_campaign_exec_log_enrollment
    ON campaign_execution_log (enrollment_id, created_at DESC);

ALTER PUBLICATION supabase_realtime ADD TABLE campaign_execution_log;
```

- [ ] **Step 2: Commit**

```bash
git add backend/migrations/20260709_cadence_enrollment_hardening.sql
git commit -m "feat(cadence): migration — claim/idempotency/step cols, unique-enrollment index, exec log"
```

> **NOTE for executor:** the migration is NOT applied automatically. Tests below stub Supabase and never touch a real DB. Flag to the user at the end that this migration must be applied to Supabase (homolog then prod) before the code is deployed.

---

## Task 1: F3 — conflict-safe enrollment (no double-enroll)

**Files:**
- Modify: `backend/app/campaigns/service.py` (`create_enrollment`)
- Test: `backend/tests/test_cadence_hardening_enroll.py`

**Behavior:** `create_enrollment` must not raise on the new unique index; a duplicate active/paused enrollment is a no-op returning the existing row. This makes the TOCTOU in triggers harmless.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_cadence_hardening_enroll.py
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class _UniqueViolation(Exception):
    """Stand-in for postgrest unique-violation error (code 23505)."""
    def __init__(self):
        super().__init__("duplicate key value violates unique constraint "
                         "\"uq_campaign_enrollments_active\"")


def test_create_enrollment_duplicate_is_noop_returns_existing():
    from app.campaigns import service

    existing = {"id": "enr-existing", "campaign_id": "c1", "lead_id": "l1", "status": "active"}
    sb = MagicMock()
    # INSERT raises unique violation; fallback SELECT returns the existing row.
    sb.table.return_value.insert.return_value.execute.side_effect = _UniqueViolation()
    (sb.table.return_value.select.return_value.eq.return_value
       .eq.return_value.in_.return_value.limit.return_value.execute
       .return_value.data) = [existing]

    with patch.object(service, "get_supabase", return_value=sb):
        out = service.create_enrollment("c1", "l1", "node1", datetime.now(timezone.utc))

    assert out == existing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cadence_hardening_enroll.py -v`
Expected: FAIL (currently `create_enrollment` lets the exception propagate).

- [ ] **Step 3: Implement conflict-safe create_enrollment**

Replace `create_enrollment` in `backend/app/campaigns/service.py` with:

```python
def _is_unique_violation(exc: Exception) -> bool:
    s = str(exc).lower()
    return "23505" in s or "duplicate key" in s or "uq_campaign_enrollments_active" in s


def create_enrollment(campaign_id: str, lead_id: str, current_node_id: str, next_execute_at: datetime, deal_id: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    try:
        return sb.table("campaign_enrollments").insert({
            "campaign_id": campaign_id,
            "lead_id": lead_id,
            "deal_id": deal_id,
            "current_node_id": current_node_id,
            "next_execute_at": next_execute_at.isoformat(),
            "env_tag": _ENV_TAG,
        }).execute().data[0]
    except Exception as exc:
        if not _is_unique_violation(exc):
            raise
        # Already enrolled (unique index) — return the live enrollment, no-op.
        rows = (
            sb.table("campaign_enrollments")
            .select("*")
            .eq("campaign_id", campaign_id)
            .eq("lead_id", lead_id)
            .in_("status", ["active", "paused"])
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cadence_hardening_enroll.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/service.py tests/test_cadence_hardening_enroll.py
git commit -m "fix(cadence): F3 conflict-safe create_enrollment (no double-enroll)"
```

---

## Task 2: F1 + F4 — atomic claim + fair ordering

**Files:**
- Modify: `backend/app/campaigns/service.py` (`get_due_enrollments` ordering; new `claim_enrollment`, `release_enrollment_claim`)
- Modify: `backend/app/automation/engine.py` (`process_due_enrollments` claims before processing; release on advance)
- Test: `backend/tests/test_cadence_hardening_claim.py`

**Behavior:**
- `get_due_enrollments` orders by `next_execute_at ASC` (oldest first) → no starvation.
- `claim_enrollment(id)` does a guarded UPDATE: `claimed_at = now WHERE id=? AND status='active' AND (claimed_at IS NULL OR claimed_at < now-5min)`; returns True only if this worker won.
- `_process_one` calls claim first; on `False`, skip. Every terminal/advance path clears `claimed_at` (via the `_update`/`_complete` payloads adding `claimed_at=None`).

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_cadence_hardening_claim.py
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


def test_get_due_enrollments_orders_by_next_execute_at():
    from app.campaigns import service
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.lte.return_value
    chain.order.return_value.limit.return_value.execute.return_value.data = []
    with patch.object(service, "get_supabase", return_value=sb):
        service.get_due_enrollments(datetime.now(timezone.utc), limit=20)
    chain.order.assert_called_once_with("next_execute_at", desc=False)


def test_claim_enrollment_true_when_row_updated():
    from app.campaigns import service
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": "e1"}]
    with patch.object(service, "get_supabase", return_value=sb):
        assert service.claim_enrollment("e1", datetime.now(timezone.utc)) is True


def test_claim_enrollment_false_when_no_row():
    from app.campaigns import service
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    with patch.object(service, "get_supabase", return_value=sb):
        assert service.claim_enrollment("e1", datetime.now(timezone.utc)) is False
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && python -m pytest tests/test_cadence_hardening_claim.py -v`
Expected: FAIL (`claim_enrollment` undefined; `get_due_enrollments` has no `.order`).

- [ ] **Step 3: Implement in `service.py`**

In `get_due_enrollments`, insert `.order("next_execute_at", desc=False)` before `.limit(limit)`. Add:

```python
CLAIM_STALE_SECONDS = 300  # 5 min — mirrors follow_up crash-recovery cutoff.


def claim_enrollment(enrollment_id: str, now: datetime) -> bool:
    """Atomic pending→claimed guard. True only if THIS worker won the row.

    Guarded UPDATE: only claims an active enrollment whose claim is free or stale.
    Mirrors follow_up._claim_followup_job. Fail-open→False (skip, retry next tick)."""
    from datetime import timedelta
    try:
        sb = get_supabase()
        stale = (now - timedelta(seconds=CLAIM_STALE_SECONDS)).isoformat()
        res = (
            sb.table("campaign_enrollments")
            .update({"claimed_at": now.isoformat()})
            .eq("id", enrollment_id)
            .eq("status", "active")
            .or_(f"claimed_at.is.null,claimed_at.lt.{stale}")
            .execute()
        )
        return bool(res.data)
    except Exception:
        return False
```

> NOTE: the test stubs `.update().eq().eq().execute()`. Implement the guarded query with `.or_(...)` for production but keep the two `.eq` calls (`id`, `status`) so the mock chain matches; `.or_` on a MagicMock returns another MagicMock and is chain-safe. If the mock chain in the test breaks, adapt the test's mock to include `.or_` — the production query is authoritative.

- [ ] **Step 4: Wire claim into `engine.py`**

In `process_due_enrollments`, after the priority sort, change the loop to claim first:

```python
from app.campaigns.service import claim_enrollment
for enrollment in enrollments:
    if not claim_enrollment(enrollment["id"], now):
        continue
    await _process_one(enrollment, now)
    await asyncio.sleep(random.randint(1, 3))
```

Add `"claimed_at": None` to every advance/terminal update in `_process_one`, `_complete`, `_fail_enrollment` (so the next node/tick can re-claim). Concretely: in `_update(...)` calls that set `next_execute_at`, also pass `claimed_at=None`; in `_complete` add `"claimed_at": None`.

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_cadence_hardening_claim.py -v`
Expected: PASS. Also run `python -m pytest tests/test_automation_triggers.py tests/test_automation_followup_gate.py -v` (no regressions).

- [ ] **Step 6: Commit**

```bash
git add backend/app/campaigns/service.py backend/app/automation/engine.py tests/test_cadence_hardening_claim.py
git commit -m "fix(cadence): F1 atomic enrollment claim + F4 fair next_execute_at ordering"
```

---

## Task 3: F2 — node-level send idempotency + crash-recovery

**Files:**
- Modify: `backend/app/automation/engine.py` (`_execute_send`, `_execute_send_text`, advance clears marker), `process_due_enrollments` (recovery sweep at tick start)
- Modify: `backend/app/campaigns/service.py` (`recover_stale_enrollments`, `mark_enrollment_sent`)
- Test: `backend/tests/test_cadence_hardening_idempotency.py`

**Behavior:**
- Before a `send`/`send_text` executes, if `enrollment["last_sent_node_id"] == current_node_id` → the send already happened (crash after send, before advance): **skip the send**, proceed to advance.
- After a successful send, `mark_enrollment_sent(id, node_id, wamid)` persists `last_sent_node_id`+`last_sent_wamid` BEFORE advancing.
- On advance to the next node, clear `last_sent_node_id=None` (so a legitimate revisit re-sends).
- `recover_stale_enrollments(now)` at tick start clears `claimed_at` on active rows stale > 5 min (worker died) so they re-enter; idempotency guard prevents the resend.

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_cadence_hardening_idempotency.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_send_skipped_when_last_sent_node_matches_current():
    from app.automation import engine
    node = {"id": "n-send", "type": "send", "config": {"template_name": "t"}, "next_node_id": "n2"}
    enrollment = {"id": "e1", "lead_id": "l1", "last_sent_node_id": "n-send",
                  "campaign_nodes": node, "leads": {"id": "l1", "phone": "5511999999999", "ai_enabled": True}}
    campaign = {"status": "active", "channel_id": "ch1"}
    enrollment["campaigns"] = campaign

    send_node = AsyncMock()
    with patch("app.campaigns.worker._execute_send_node", send_node), \
         patch.object(engine, "check_frequency_cap", return_value=True), \
         patch.object(engine, "_is_within_window", return_value=True), \
         patch.object(engine, "record_daily_send"), \
         patch.object(engine, "_update") as upd:
        _run(engine._process_one(enrollment, datetime.now(timezone.utc)))

    send_node.assert_not_awaited()          # idempotent skip
    assert upd.called                       # still advanced past the node
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && python -m pytest tests/test_cadence_hardening_idempotency.py -v`
Expected: FAIL (send is currently always executed).

- [ ] **Step 3: Implement idempotency guard in `engine.py`**

In `_process_one`, inside the `send`/`send_text` branch, BEFORE calling `_execute_send`/`_execute_send_text`:

```python
already_sent = enrollment.get("last_sent_node_id") == node["id"]
if node_type == "send":
    if not already_sent:
        await _execute_send(enrollment, node, lead, now, campaign)
        mark_enrollment_sent(enrollment["id"], node["id"], _last_wamid(enrollment))
else:  # send_text
    if not already_sent:
        await _execute_send_text(enrollment, node, lead, now, campaign)
        mark_enrollment_sent(enrollment["id"], node["id"], None)
if not already_sent:
    record_daily_send(lead["id"])
```

Simplest robust wamid capture: have `_execute_send`/`_execute_send_text` return the wamid (or `None`) and pass it into `mark_enrollment_sent`. Update those two functions to `return wamid`. (`_execute_send_node` already computes `wamid`; return it up the chain.)

On advance, clear the marker — in the advance `_update`:

```python
_update(enrollment["id"], current_node_id=next_id, next_execute_at=now.isoformat(),
        retry_count=0, last_error=None, claimed_at=None, last_sent_node_id=None,
        step_count=(enrollment.get("step_count") or 0) + 1)
```

Add to `service.py`:

```python
def mark_enrollment_sent(enrollment_id: str, node_id: str, wamid: str | None) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update({
        "last_sent_node_id": node_id, "last_sent_wamid": wamid,
    }).eq("id", enrollment_id).execute()


def recover_stale_enrollments(now: datetime, stale_seconds: int = CLAIM_STALE_SECONDS) -> int:
    """Clear stale claims (worker died mid-tick) so rows re-enter. Idempotency guard
    (last_sent_node_id) prevents any resend. Mirrors follow_up._recover_stale_followup_jobs."""
    from datetime import timedelta
    try:
        sb = get_supabase()
        cutoff = (now - timedelta(seconds=stale_seconds)).isoformat()
        res = (
            sb.table("campaign_enrollments")
            .update({"claimed_at": None})
            .eq("status", "active")
            .eq("env_tag", _ENV_TAG)
            .lt("claimed_at", cutoff)
            .execute()
        )
        return len(res.data or [])
    except Exception:
        return 0
```

In `engine.py` `process_due_enrollments`, first line after `now = ...`:

```python
from app.campaigns.service import recover_stale_enrollments, claim_enrollment, mark_enrollment_sent
recover_stale_enrollments(now)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && python -m pytest tests/test_cadence_hardening_idempotency.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/engine.py backend/app/campaigns/service.py tests/test_cadence_hardening_idempotency.py
git commit -m "fix(cadence): F2 node-level send idempotency + stale-claim crash-recovery"
```

---

## Task 4: F5 + F10 — window-skip no phantom send; permanent-error cancel

**Files:**
- Modify: `backend/app/automation/retry.py` (move `decide_failure_update` + `_is_permanent_error` here)
- Modify: `backend/app/automation/engine.py` (`_execute_send_text` raises `WindowClosed`; `_process_one` uses shared failure logic; no `record_daily_send`/advance on window-skip)
- Test: `backend/tests/test_cadence_hardening_window_error.py`

**Behavior:**
- `_execute_send_text`, when the 24h window is closed, raises `WindowClosed` instead of silently returning. `_process_one` catches it → reschedule via backoff (`calculate_next_retry`), no `record_daily_send`, no advance, log an execution-log `skipped` row. On backoff cap → cancel.
- `_fail_enrollment` replaced by shared `decide_failure_update` (permanent Meta 4xx / embedded "rejected" → cancel immediately instead of 3 wasted retries).

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_cadence_hardening_window_error.py
from datetime import datetime, timezone
from app.automation.retry import decide_failure_update, _is_permanent_error


class _Resp:
    def __init__(self, status): self.status_code = status

class _HTTP(Exception):
    def __init__(self, status): self.response = _Resp(status); super().__init__(f"http {status}")


def test_permanent_meta_error_cancels_immediately():
    upd = decide_failure_update(_HTTP(400), retry_count=0, now=datetime.now(timezone.utc))
    assert upd["status"] == "cancelled"


def test_transient_error_backs_off():
    upd = decide_failure_update(RuntimeError("network blip"), 0, datetime.now(timezone.utc))
    assert "next_execute_at" in upd and upd.get("status") != "cancelled"


def test_embedded_rejected_is_permanent():
    assert _is_permanent_error(RuntimeError("template rejected (missing ...)")) is True
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && python -m pytest tests/test_cadence_hardening_window_error.py -v`
Expected: FAIL (`decide_failure_update` not in `retry.py`).

- [ ] **Step 3: Implement**

Move `_PERMANENT_STATUS`, `_is_permanent_error`, `decide_failure_update` from `campaigns/worker.py` into `automation/retry.py` (keep signatures identical; they already use `calculate_next_retry`). In `engine.py`:

```python
class WindowClosed(Exception):
    """24h Meta window closed for a free-text node — cannot send now."""
```

In `_execute_send_text`, replace the silent `_update(..., last_error="24h_window_expired"); return` with `raise WindowClosed()`. In `_process_one` `except` block:

```python
except WindowClosed:
    from app.automation.retry import calculate_next_retry
    nxt, new_count, final = calculate_next_retry(enrollment.get("retry_count", 0), now)
    if final:
        _update(enrollment["id"], status="cancelled", last_error="24h_window_expired", claimed_at=None)
    else:
        _update(enrollment["id"], retry_count=new_count, next_execute_at=nxt.isoformat(),
                last_error="24h_window_expired", claimed_at=None)
    _log_exec(enrollment, node, "skipped", "janela 24h fechada — reagendado")
    return
except Exception as e:
    logger.error("[AUTOMATION] enrollment=%s node=%s error=%s", enrollment["id"], node.get("id"), e, exc_info=True)
    from app.automation.retry import decide_failure_update
    _update(enrollment["id"], **decide_failure_update(e, enrollment.get("retry_count", 0), now), claimed_at=None)
    _log_exec(enrollment, node, "failed", str(e)[:300])
```

Delete the old `_fail_enrollment`. (`_log_exec` is added in Task 8 — for now define a no-op stub `def _log_exec(*a, **k): pass` and replace in Task 8. State this in the code comment.)

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_cadence_hardening_window_error.py tests/test_campaigns_worker_retry.py -v`
Expected: PASS (adapt `test_campaigns_worker_retry.py` imports if it imported `decide_failure_update` from `campaigns.worker` — re-export it there with `from app.automation.retry import decide_failure_update` to keep back-compat).

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/retry.py backend/app/automation/engine.py backend/app/campaigns/worker.py tests/test_cadence_hardening_window_error.py
git commit -m "fix(cadence): F5 no phantom send on closed window + F10 permanent-error cancel"
```

---

## Task 5: F6 — loop/step guard

**Files:**
- Modify: `backend/app/automation/engine.py` (`_process_one` checks `step_count` at entry)
- Test: `backend/tests/test_cadence_hardening_loop.py`

**Behavior:** at the top of `_process_one`, if `enrollment["step_count"] >= MAX_STEPS` (200), fail the enrollment (`status='failed'`, `last_error='max_steps_exceeded'`) and return. Every node advance increments `step_count` (already added in Task 3 advance; also increment in condition/action advances).

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_cadence_hardening_loop.py
import asyncio
from unittest.mock import patch
from datetime import datetime, timezone
from app.automation import engine


def test_enrollment_fails_when_step_count_exceeds_max():
    enr = {"id": "e1", "step_count": engine.MAX_STEPS, "campaign_nodes": {"id": "n", "type": "condition"},
           "leads": {"id": "l1", "ai_enabled": True}, "campaigns": {"status": "active"}}
    with patch.object(engine, "_update") as upd:
        asyncio.get_event_loop().run_until_complete(engine._process_one(enr, datetime.now(timezone.utc)))
    kwargs = upd.call_args.kwargs
    assert kwargs.get("status") == "failed" and "max_steps" in (kwargs.get("last_error") or "")
```

- [ ] **Step 2: Verify fail** — `cd backend && python -m pytest tests/test_cadence_hardening_loop.py -v` → FAIL (`MAX_STEPS` undefined).

- [ ] **Step 3: Implement** — add `MAX_STEPS = 200` module constant; at start of `_process_one` after fetching `node`:

```python
if (enrollment.get("step_count") or 0) >= MAX_STEPS:
    _update(enrollment["id"], status="failed", last_error="max_steps_exceeded", claimed_at=None)
    logger.error("[AUTOMATION] enrollment=%s excedeu MAX_STEPS (%d) — loop suspeito", enrollment["id"], MAX_STEPS)
    return
```

Ensure `_execute_condition` and `_execute_action` advances also bump `step_count` (add `step_count=(enrollment.get("step_count") or 0)+1` to their `_update` calls).

- [ ] **Step 4: Verify pass** — same pytest → PASS.
- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/engine.py tests/test_cadence_hardening_loop.py
git commit -m "fix(cadence): F6 per-enrollment step guard (anti infinite-loop)"
```

---

## Task 6: F7 + F8 — delete dead duplicate engine; weekend clamp

**Files:**
- Modify: `backend/app/campaigns/worker.py` (delete dead code)
- Modify: `backend/app/automation/engine.py` (`_is_within_window`/`_next_window_start` honor `skip_weekends`)
- Test: `backend/tests/test_cadence_hardening_window_weekend.py`

**F7 — delete from `campaigns/worker.py`:** `process_campaign_enrollments`, `check_campaign_triggers`, `_execute_condition_node`, `_execute_action_node`, `_execute_end_node`, and the now-unused `_is_within_window`/`_next_window_start`/`BRT_OFFSET` **if** nothing else in the file uses them. **KEEP:** `_execute_send_node`, `handle_campaign_reply`, and re-export `decide_failure_update = ...` (moved to retry.py) for back-compat. Verify no live importer references the deleted names: `grep -rn "process_campaign_enrollments\|check_campaign_triggers\|_execute_condition_node" backend/app` must return nothing (tests may — update them).

**F8 — weekend clamp (opt-in):** thread `skip_weekends` (from `campaign`) into the send-window check. When true, `_is_within_window` also requires `weekday() < 5`, and `_next_window_start` skips Sat/Sun (mirror `follow_up.service._clamp_to_business_window` weekend loop).

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_cadence_hardening_window_weekend.py
from datetime import datetime, timezone
from app.automation import engine


def test_window_rejects_weekend_when_skip_weekends():
    # 2026-07-11 is a Saturday; 12:00 BRT = 15:00 UTC.
    sat = datetime(2026, 7, 11, 15, 0, tzinfo=timezone.utc)
    assert engine._is_within_window(sat, 7, 18, skip_weekends=True) is False
    assert engine._is_within_window(sat, 7, 18, skip_weekends=False) is True
```

- [ ] **Step 2: Verify fail** — FAIL (`skip_weekends` kwarg unknown).
- [ ] **Step 3: Implement** — add `skip_weekends: bool = False` to `_is_within_window` and `_next_window_start`; in `_is_within_window` return `False` if `skip_weekends and brt.weekday() >= 5`; in `_next_window_start`, after computing `target`, `while (target + BRT_OFFSET).weekday() >= 5: target += timedelta(days=1)` when `skip_weekends`. Pass `campaign.get("skip_weekends", False)` at the two call sites in `_process_one` (send + wait branches).
- [ ] **Step 4: Verify pass**; also run full automation suite: `cd backend && python -m pytest tests/ -k "automation or cadence or campaign" -v`.
- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/worker.py backend/app/automation/engine.py tests/test_cadence_hardening_window_weekend.py
git commit -m "chore(cadence): F7 delete dead duplicate engine + F8 opt-in weekend clamp"
```

---

## Task 7: F9 + F11 — conversion cascade on deal-stage move; keyword word-boundary

**Files:**
- Modify: `backend/app/automation/engine.py` (`_execute_action` `move_deal_stage`/`mark_deal_won` fire conversion for the target stage)
- Modify: `backend/app/automation/triggers.py` (`message_received` keyword uses word-boundary regex)
- Test: `backend/tests/test_cadence_hardening_cascade.py`

**F9:** after `move_deal_stage`/`mark_deal_won` updates `deals.stage_id`, resolve the stage's `conversion_event`/`conversion_value` and call `fire_stage_conversion_background` (reuse `campaigns.triggers._maybe_fire_stage_conversion` logic — extract a shared helper `fire_conversion_for_deal_stage(lead_id, deal_id)` in `campaigns/conversions.py` and call it from both). Fail-soft.

**F11:** replace `any(k in message_body for k in keywords)` with a word-boundary match:

```python
import re
def _keyword_hit(body: str, keywords: list[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", body) for k in keywords if k)
```

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_cadence_hardening_cascade.py
from app.automation.triggers import _keyword_hit

def test_keyword_word_boundary_no_substring_false_positive():
    assert _keyword_hit("isso é assim mesmo", ["sim"]) is False
    assert _keyword_hit("sim, quero", ["sim"]) is True
```

- [ ] **Step 2: Verify fail** — FAIL (`_keyword_hit` undefined).
- [ ] **Step 3: Implement** both changes (add `_keyword_hit` + use it in `fire_trigger`; add `fire_conversion_for_deal_stage` helper + call in engine actions).
- [ ] **Step 4: Verify pass** — `cd backend && python -m pytest tests/test_cadence_hardening_cascade.py tests/test_automation_triggers_keyword.py -v`.
- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/engine.py backend/app/automation/triggers.py backend/app/campaigns/conversions.py tests/test_cadence_hardening_cascade.py
git commit -m "feat(cadence): F9 conversion cascade on deal-stage move + F11 keyword word-boundary"
```

---

## Task 8: F13 (backend) — per-node execution log

**Files:**
- Create: `backend/app/campaigns/execution_log.py`
- Modify: `backend/app/automation/engine.py` (`_log_exec` writes real rows; call after each node)
- Modify: `backend/app/campaigns/router.py` (GET recent logs for a campaign)
- Test: `backend/tests/test_cadence_hardening_execlog.py`

**Behavior:** after each node executes (done/failed/skipped), append a `campaign_execution_log` row (fail-soft, never breaks the tick). Expose `GET /api/campaigns/{id}/execution-log?limit=50`.

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_cadence_hardening_execlog.py
from unittest.mock import MagicMock, patch

def test_log_execution_inserts_row():
    from app.campaigns import execution_log
    sb = MagicMock()
    with patch.object(execution_log, "get_supabase", return_value=sb):
        execution_log.log_execution(
            enrollment_id="e1", campaign_id="c1", lead_id="l1",
            node_id="n1", node_type="send", status="done", log="Template enviado",
        )
    sb.table.assert_called_with("campaign_execution_log")
    sb.table.return_value.insert.assert_called_once()
```

- [ ] **Step 2: Verify fail** — FAIL (module missing).
- [ ] **Step 3: Implement** `execution_log.py`:

```python
import logging
from app.db.supabase import get_supabase
logger = logging.getLogger(__name__)

def log_execution(*, enrollment_id, campaign_id, lead_id=None, node_id=None,
                  node_type=None, status, log=None) -> None:
    """Fail-soft append to campaign_execution_log. Never raises."""
    try:
        get_supabase().table("campaign_execution_log").insert({
            "enrollment_id": enrollment_id, "campaign_id": campaign_id, "lead_id": lead_id,
            "node_id": node_id, "node_type": node_type, "status": status, "log": log,
        }).execute()
    except Exception as exc:
        logger.warning("[EXEC_LOG] falha ao registrar execução: %s", exc)
```

Replace the `_log_exec` stub in `engine.py` with a wrapper that pulls ids from the enrollment/node and calls `log_execution`. Call `_log_exec(enrollment, node, "done", <human summary>)` after each successful node in `_process_one`. Add the router endpoint (mirror `list_enrollments` shape).

- [ ] **Step 4: Verify pass** — pytest → PASS.
- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/execution_log.py backend/app/automation/engine.py backend/app/campaigns/router.py tests/test_cadence_hardening_execlog.py
git commit -m "feat(cadence): F13 per-node execution log + API"
```

---

## Task 9: F13 (frontend) — execution-log panel  *(parallelizable — independent files)*

**Files:**
- Create: `frontend/src/components/campaigns/cadence-execution-log.tsx`
- Modify: `frontend/src/app/(authenticated)/campanhas/cadencias/[id]/page.tsx` (mount the panel)
- Create: `frontend/src/app/api/campaigns/[id]/execution-log/route.ts` (proxy to backend)

**Behavior:** a collapsible panel on the cadence editor showing the latest execution-log rows (node type, status badge done/failed/skipped, timestamp, log text), subscribed to Supabase Realtime on `campaign_execution_log` filtered by `campaign_id`. **Invoke the `frontend-design` skill before writing UI** (project rule: always run frontend-design before frontend work). Follow existing patterns in `frontend/src/components/campaigns/` and the realtime hook patterns in `frontend/src/hooks/use-realtime-*.ts`.

- [ ] **Step 1:** Invoke `frontend-design` skill; read `campanhas/cadencias/[id]/page.tsx` + a sibling component + one `use-realtime-*` hook for conventions.
- [ ] **Step 2:** Build the API route proxy (`GET` → backend `/api/campaigns/{id}/execution-log`), matching auth pattern of neighboring routes under `frontend/src/app/api/`.
- [ ] **Step 3:** Build `cadence-execution-log.tsx` (fetch initial + subscribe realtime; status badges).
- [ ] **Step 4:** Mount it in the cadence page; manual check via `npm run dev` (or existing dev task).
- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/campaigns/cadence-execution-log.tsx "frontend/src/app/(authenticated)/campanhas/cadencias/[id]/page.tsx" "frontend/src/app/api/campaigns/[id]/execution-log/route.ts"
git commit -m "feat(cadence): F13 execution-log panel in cadence editor"
```

---

## Final verification (before handing back)

- [ ] `cd backend && python -m pytest tests/ -k "cadence or automation or campaign" -v` — all green.
- [ ] `grep -rn "process_campaign_enrollments\|_execute_condition_node" backend/app` — empty (dead code gone).
- [ ] Confirm the two live loops still import cleanly: `python -c "import app.automation.engine, app.automation.triggers, app.campaigns.worker, app.campaigns.service"` from `backend/`.
- [ ] **Tell the user:** migration `20260709_cadence_enrollment_hardening.sql` must be applied to Supabase (homolog → prod) BEFORE deploy, and the live end-to-end WhatsApp test (Arthur's number) still needs their number.

## Coverage vs findings
F1 T2 · F2 T3 · F3 T1 · F4 T2 · F5 T4 · F6 T5 · F7 T6 · F8 T6 · F9 T7 · F10 T4 · F11 T7 · F13 T8+T9. (F12 frequency-cap TOCTOU and F14/F15 low-value — folded: F12 mitigated by F1 claim serialization; F14/F15 deferred, noted here.)

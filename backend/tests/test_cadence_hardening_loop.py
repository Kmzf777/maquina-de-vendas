# backend/tests/test_cadence_hardening_loop.py
from unittest.mock import patch
from datetime import datetime, timezone
from app.automation import engine


async def test_enrollment_fails_when_step_count_exceeds_max():
    enr = {"id": "e1", "step_count": engine.MAX_STEPS, "campaign_nodes": {"id": "n", "type": "condition"},
           "leads": {"id": "l1", "ai_enabled": True}, "campaigns": {"status": "active"}}
    with patch.object(engine, "_update") as upd:
        await engine._process_one(enr, datetime.now(timezone.utc))
    kwargs = upd.call_args.kwargs
    assert kwargs.get("status") == "failed" and "max_steps" in (kwargs.get("last_error") or "")

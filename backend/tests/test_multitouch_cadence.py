from datetime import datetime, timezone, timedelta
import importlib


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_build_touch_jobs_creates_four_sequential_jobs():
    from app.follow_up.cadence import build_touch_jobs, CADENCE
    assert len(CADENCE) == 4
    # Monday 12:00 UTC = 09:00 BRT (inside window)
    now = _utc(2026, 6, 29, 12, 0)
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev")
    assert [j["sequence"] for j in jobs] == [1, 2, 3, 4]
    assert all(j["status"] == "pending" for j in jobs)
    assert all(j["env_tag"] == "dev" for j in jobs)
    assert all(j["conversation_id"] == "conv-1" for j in jobs)
    # objectives carried in metadata, in order
    assert [j["metadata"]["objetivo"] for j in jobs] == [
        "reengajar", "reforco_valor", "prova_social", "ultima_chamada"
    ]
    # contexto mirrors objective (for reopen reuse), objective_prompt present
    for j in jobs:
        assert j["metadata"]["contexto"] == j["metadata"]["objetivo"]
        assert j["metadata"]["objective_prompt"]


def test_build_touch_jobs_fire_at_monotonic_and_in_business_window():
    from app.follow_up.cadence import build_touch_jobs, MIN_GAP
    from app.follow_up.service import is_within_business_window
    # Friday 23:00 BRT = Saturday 02:00 UTC — the collision scenario (R2)
    now = _utc(2026, 6, 27, 2, 0)  # Sat 02:00 UTC = Fri 23:00 BRT
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev")
    fires = [datetime.fromisoformat(j["fire_at"]) for j in jobs]
    # strictly increasing with >= MIN_GAP spacing, all inside business window
    for earlier, later in zip(fires, fires[1:]):
        assert later >= earlier + MIN_GAP
    for f in fires:
        assert is_within_business_window(f)


def test_build_touch_jobs_t1_jitter_within_range():
    from app.follow_up.cadence import build_touch_jobs

    class _FixedRng:
        def randint(self, a, b):
            return a  # lower bound -> 90 min
    now = _utc(2026, 6, 29, 12, 0)  # Mon 09:00 BRT
    jobs = build_touch_jobs(now, "c", "l", "ch", "dev", rng=_FixedRng())
    t1_fire = datetime.fromisoformat(jobs[0]["fire_at"])
    # 09:00 BRT + 90 min = 10:30 BRT = 13:30 UTC, still in window
    assert t1_fire == _utc(2026, 6, 29, 13, 30)


def test_schedule_followup_inserts_four_jobs(monkeypatch):
    from app.follow_up import service

    inserted = {}

    class _Chain:
        @property
        def not_(self):
            return self

        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def update(self, payload): return self
        def insert(self, payload): inserted["rows"] = payload; return self
        def execute(self):
            return type("R", (), {"data": [{"id": "conv-1"}]})() if not inserted else type("R", (), {"data": []})()

    class _Tbl:
        def __init__(self, name): self.name = name
        def select(self, *a, **k): return _Chain()
        def eq(self, *a, **k): return _Chain()
        def update(self, payload): return _Chain()
        def insert(self, payload): inserted["rows"] = payload; return _Chain()
        def execute(self):
            if self.name == "conversations":
                return type("R", (), {"data": [{"id": "conv-1"}]})()
            return type("R", (), {"data": []})()

    class _SB:
        def table(self, name): return _Tbl(name)

    monkeypatch.setattr(service, "get_supabase", lambda: _SB())
    service.schedule_followup("conv-1", "lead-1", "chan-1")
    assert len(inserted["rows"]) == 4
    assert [r["sequence"] for r in inserted["rows"]] == [1, 2, 3, 4]
    assert inserted["rows"][3]["metadata"]["objetivo"] == "ultima_chamada"


# ---------------------------------------------------------------------------
# Task 3: fire_reopen_template helper
# ---------------------------------------------------------------------------
import pytest


def _reopen_job():
    return {"id": "job-1", "lead_id": "lead-1", "conversation_id": "conv-1", "metadata": {}}


@pytest.mark.asyncio
async def test_fire_reopen_template_success_marks_awaiting_reopen(monkeypatch):
    from app.follow_up import scheduler

    calls = {"awaiting": None, "saved": None, "meta": None}

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            calls["meta"] = (to, name, language_code)
            return {"messages": [{"id": "wamid-x"}]}

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: "utility")
    monkeypatch.setattr(scheduler, "save_message", lambda **kw: calls.__setitem__("saved", kw))
    monkeypatch.setattr(scheduler, "_mark_awaiting_reopen", lambda jid: calls.__setitem__("awaiting", jid))
    monkeypatch.setattr(scheduler, "extract_wamid", lambda r: "wamid-x")
    # store-metadata helper writes to DB; stub it to capture
    monkeypatch.setattr(scheduler, "_store_reopen_context", lambda jid, motivo, contexto: calls.__setitem__("ctx", (jid, motivo, contexto)))

    lead = {"id": "lead-1", "name": "Ana Silva", "phone": "5511999999999"}
    channel = {"provider_config": {}}
    ok = await scheduler.fire_reopen_template(
        _reopen_job(), lead, channel, "conv-1", motivo="ultima_chamada", contexto="ultima_chamada"
    )
    assert ok is True
    assert calls["awaiting"] == "job-1"
    assert calls["meta"][1] == scheduler._REOPEN_TEMPLATE_NAME
    assert calls["meta"][2] == "pt_BR"
    assert calls["ctx"] == ("job-1", "ultima_chamada", "ultima_chamada")


@pytest.mark.asyncio
async def test_fire_reopen_template_4xx_cancels(monkeypatch):
    import httpx
    from app.follow_up import scheduler

    cancelled = {}

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            req = httpx.Request("POST", "https://graph.facebook.com")
            resp = httpx.Response(400, request=req)
            raise httpx.HTTPStatusError("bad", request=req, response=resp)

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: "utility")
    monkeypatch.setattr(scheduler, "_cancel_job", lambda jid, reason: cancelled.update({"id": jid, "reason": reason}))

    lead = {"id": "lead-1", "name": "Ana", "phone": "5511999999999"}
    ok = await scheduler.fire_reopen_template(_reopen_job(), lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x")
    assert ok is False
    assert cancelled["reason"] == "reopen_template_error_400"


# ---------------------------------------------------------------------------
# Task 4: closed-window branch — template or context refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_closed_window_no_reopen_fires_template(monkeypatch):
    from app.follow_up import scheduler

    _RICH_PROMPT = "Reforce o valor do produto com urgência moderada — cite diferencial competitivo."
    fired = {}
    monkeypatch.setattr(scheduler, "get_due_followups", lambda now, limit=10: [{
        "id": "job-2", "conversation_id": "conv-1", "lead_id": "lead-1", "sequence": 2,
        "job_type": None, "metadata": {"objetivo": "reforco_valor", "objective_prompt": _RICH_PROMPT},
        "leads": {"id": "lead-1", "phone": "5511999999999", "name": "Ana",
                  "last_customer_message_at": "2026-06-01T00:00:00+00:00"},
        "channels": {"id": "chan-1", "mode": "ai", "provider_config": {}},
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": True,
                          "last_customer_message_at": "2026-06-01T00:00:00+00:00"},
    }])
    monkeypatch.setattr(scheduler, "_pending_reopen_job", lambda cid: None)
    async def _fake_fire(job, lead, channel, conv, *, motivo="", contexto=""):
        fired.update({"job": job["id"], "motivo": motivo, "contexto": contexto}); return True
    monkeypatch.setattr(scheduler, "fire_reopen_template", _fake_fire)

    await scheduler.process_due_followups(now=__import__("datetime").datetime(2026, 6, 29, 12, tzinfo=__import__("datetime").timezone.utc))
    assert fired["job"] == "job-2"
    assert fired["motivo"] == "reforco_valor"
    assert fired["contexto"] == _RICH_PROMPT


@pytest.mark.asyncio
async def test_closed_window_with_pending_reopen_refreshes_context(monkeypatch):
    from app.follow_up import scheduler

    _RICH_PROMPT = "Destaque prova social — mencionar casos de sucesso de clientes similares."
    refreshed, cancelled, fired = {}, {}, {"called": False}
    monkeypatch.setattr(scheduler, "get_due_followups", lambda now, limit=10: [{
        "id": "job-3", "conversation_id": "conv-1", "lead_id": "lead-1", "sequence": 3,
        "job_type": None, "metadata": {"objetivo": "prova_social", "objective_prompt": _RICH_PROMPT},
        "leads": {"id": "lead-1", "phone": "5511999999999", "name": "Ana",
                  "last_customer_message_at": "2026-06-01T00:00:00+00:00"},
        "channels": {"id": "chan-1", "mode": "ai", "provider_config": {}},
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": True,
                          "last_customer_message_at": "2026-06-01T00:00:00+00:00"},
    }])
    monkeypatch.setattr(scheduler, "_pending_reopen_job", lambda cid: {"id": "job-2"})
    monkeypatch.setattr(scheduler, "_store_reopen_context", lambda jid, motivo, contexto: refreshed.update({"id": jid, "motivo": motivo, "contexto": contexto}))
    monkeypatch.setattr(scheduler, "_cancel_job", lambda jid, reason: cancelled.update({"id": jid, "reason": reason}))
    async def _fake_fire(*a, **k):
        fired["called"] = True; return True
    monkeypatch.setattr(scheduler, "fire_reopen_template", _fake_fire)

    await scheduler.process_due_followups(now=__import__("datetime").datetime(2026, 6, 29, 12, tzinfo=__import__("datetime").timezone.utc))
    assert refreshed == {"id": "job-2", "motivo": "prova_social", "contexto": _RICH_PROMPT}
    assert cancelled == {"id": "job-3", "reason": "reopen_context_refreshed"}
    assert fired["called"] is False  # no 2nd template


# ---------------------------------------------------------------------------
# Task 3 (safety net): fire_reopen_template error-path contracts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fire_reopen_template_5xx_does_not_cancel(monkeypatch):
    """Transient 5xx must NOT cancel the job — it should retry on the next tick."""
    import httpx
    from app.follow_up import scheduler

    cancel_calls = []

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            req = httpx.Request("POST", "https://graph.facebook.com")
            resp = httpx.Response(503, request=req)
            raise httpx.HTTPStatusError("service unavailable", request=req, response=resp)

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: "utility")
    monkeypatch.setattr(scheduler, "_cancel_job", lambda jid, reason: cancel_calls.append((jid, reason)))

    lead = {"id": "lead-1", "name": "Ana", "phone": "5511999999999"}
    ok = await scheduler.fire_reopen_template(
        _reopen_job(), lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x"
    )
    assert ok is False
    assert cancel_calls == []


@pytest.mark.asyncio
async def test_fire_reopen_template_runtime_error_cancels_rejected(monkeypatch):
    """RuntimeError (template rejected) must cancel with reason 'reopen_template_rejected'."""
    from app.follow_up import scheduler

    cancelled = {}

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            raise RuntimeError("rejected")

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: "utility")
    monkeypatch.setattr(scheduler, "_cancel_job", lambda jid, reason: cancelled.update({"id": jid, "reason": reason}))

    lead = {"id": "lead-1", "name": "Ana", "phone": "5511999999999"}
    ok = await scheduler.fire_reopen_template(
        _reopen_job(), lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x"
    )
    assert ok is False
    assert cancelled["reason"] == "reopen_template_rejected"


# ---------------------------------------------------------------------------
# Compliance: reopen template MUST be UTILITY (never Marketing)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fire_reopen_template_blocks_non_utility(monkeypatch):
    """If the reopen template is not UTILITY, do NOT send: cancel + system_alert."""
    from app.follow_up import scheduler

    sent = {"called": False}
    cancelled, alerts = {}, []

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, *a, **k):
            sent["called"] = True
            return {"messages": [{"id": "x"}]}

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: "marketing")
    monkeypatch.setattr(scheduler, "_cancel_job", lambda jid, reason: cancelled.update({"id": jid, "reason": reason}))
    monkeypatch.setattr(scheduler, "create_system_alert", lambda *a, **k: alerts.append((a, k)))

    lead = {"id": "lead-1", "name": "Ana", "phone": "5511999999999"}
    ok = await scheduler.fire_reopen_template(
        _reopen_job(), lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x"
    )
    assert ok is False
    assert sent["called"] is False, "must NOT send a non-utility template"
    assert cancelled["reason"] == "reopen_template_not_utility"
    assert len(alerts) == 1, "must raise a system alert for the compliance block"


@pytest.mark.asyncio
async def test_fire_reopen_template_proceeds_when_category_unverifiable(monkeypatch):
    """Category can't be determined (None) → fail-open: proceed (hardcoded template is utility)."""
    from app.follow_up import scheduler

    sent = {"called": False}

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            sent["called"] = True
            return {"messages": [{"id": "wamid-x"}]}

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: None)
    monkeypatch.setattr(scheduler, "save_message", lambda **kw: None)
    monkeypatch.setattr(scheduler, "_mark_awaiting_reopen", lambda jid: None)
    monkeypatch.setattr(scheduler, "_store_reopen_context", lambda *a: None)
    monkeypatch.setattr(scheduler, "extract_wamid", lambda r: "wamid-x")

    lead = {"id": "lead-1", "name": "Ana", "phone": "5511999999999"}
    ok = await scheduler.fire_reopen_template(
        _reopen_job(), lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x"
    )
    assert ok is True
    assert sent["called"] is True

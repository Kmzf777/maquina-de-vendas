# backend/tests/test_reposicao.py
import app.leads.reposicao as rep


def test_ensure_reposicao_deal_creates_in_reposicao_pipeline(monkeypatch):
    calls = {}
    def fake_create_deal(lead_id, title, category=None, *, pipeline_name=None, stage_label=None, dedupe_open=False):
        calls.update(lead_id=lead_id, pipeline_name=pipeline_name, dedupe_open=dedupe_open)
        return {"id": "d1"}
    monkeypatch.setattr(rep, "create_deal", fake_create_deal)
    rep.ensure_reposicao_deal("lead-1")
    assert calls["lead_id"] == "lead-1"
    assert calls["pipeline_name"] == rep.REPOSICAO_PIPELINE_NAME
    assert calls["dedupe_open"] is True


def test_ensure_reposicao_deal_failsoft(monkeypatch):
    def boom(*a, **k): raise RuntimeError("db down")
    monkeypatch.setattr(rep, "create_deal", boom)
    # não deve levantar
    rep.ensure_reposicao_deal("lead-1")


class _FakeQ:
    def __init__(self, rows): self._rows = rows
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self):
        class R: pass
        r = R(); r.data = self._rows; return r


class _FakeSB:
    def __init__(self, deals, stages): self._d = deals; self._s = stages
    def table(self, name): return _FakeQ(self._d if name == "deals" else self._s)


def test_deal_is_won_true_when_stage_key_fechado_ganho(monkeypatch):
    sb = _FakeSB(deals=[{"stage_id": "s1"}], stages=[{"key": "fechado_ganho"}])
    monkeypatch.setattr(rep, "get_supabase", lambda: sb)
    assert rep.deal_is_won("d1") is True


def test_deal_is_won_false_other_stage(monkeypatch):
    sb = _FakeSB(deals=[{"stage_id": "s1"}], stages=[{"key": "qualificado"}])
    monkeypatch.setattr(rep, "get_supabase", lambda: sb)
    assert rep.deal_is_won("d1") is False


# ── Task 4 tests ──────────────────────────────────────────────────────────────
import asyncio
import app.automation.triggers as trg


def test_fire_trigger_deal_won_calls_ensure(monkeypatch):
    called = {}
    monkeypatch.setattr(trg, "ensure_reposicao_deal", lambda lid: called.setdefault("lead", lid))
    monkeypatch.setattr(trg, "deal_is_won", lambda did: True)
    monkeypatch.setattr(trg, "_maybe_fire_stage_conversion", lambda lid, data: None)
    monkeypatch.setattr(trg, "get_campaigns_with_trigger_type", lambda t: [])
    asyncio.run(trg.fire_trigger("deal_stage_enter", "lead-9", {"deal_id": "d1"}))
    assert called.get("lead") == "lead-9"


def test_fire_trigger_sale_created_calls_ensure(monkeypatch):
    called = {}
    monkeypatch.setattr(trg, "ensure_reposicao_deal", lambda lid: called.setdefault("lead", lid))
    monkeypatch.setattr(trg, "get_campaigns_with_trigger_type", lambda t: [])
    asyncio.run(trg.fire_trigger("sale_created", "lead-7", {"value": 100}))
    assert called.get("lead") == "lead-7"


def test_fire_trigger_non_won_stage_does_not_call_ensure(monkeypatch):
    called = {}
    monkeypatch.setattr(trg, "ensure_reposicao_deal", lambda lid: called.setdefault("lead", lid))
    monkeypatch.setattr(trg, "deal_is_won", lambda did: False)
    monkeypatch.setattr(trg, "_maybe_fire_stage_conversion", lambda lid, data: None)
    monkeypatch.setattr(trg, "get_campaigns_with_trigger_type", lambda t: [])
    asyncio.run(trg.fire_trigger("deal_stage_enter", "lead-1", {"deal_id": "d1"}))
    assert "lead" not in called

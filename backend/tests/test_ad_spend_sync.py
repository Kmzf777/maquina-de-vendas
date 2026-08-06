import app.campaigns.ad_spend_sync as s


def test_sync_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(s, "google_ads_enabled", lambda: False)
    import asyncio
    assert asyncio.run(s.sync_google_ads_spend(days=7)) == 0


def test_sync_upserts_mapped_rows(monkeypatch):
    captured = {}

    class _Q:
        def upsert(self, rows, on_conflict=None):
            captured["rows"] = rows
            captured["on_conflict"] = on_conflict
            return self
        def execute(self):
            class R: pass
            r = R(); r.data = captured["rows"]; return r

    class _SB:
        def table(self, name): return _Q()

    monkeypatch.setattr(s, "google_ads_enabled", lambda: True)
    monkeypatch.setattr(s, "get_supabase", lambda: _SB())

    async def fake_fetch(date_from, date_to):
        return [{"campaign_id": "1", "campaign_name": "Atacado", "date": "2026-08-01", "cost": 2.5}]
    monkeypatch.setattr(s, "fetch_campaign_spend", fake_fetch)

    import asyncio
    n = asyncio.run(s.sync_google_ads_spend(days=7))
    assert n == 1
    row = captured["rows"][0]
    assert row["platform"] == "google" and row["campaign_name"] == "Atacado" and row["cost"] == 2.5
    assert captured["on_conflict"] == "platform,campaign_id,date"


def test_worker_registers_ad_spend_sync_tick():
    from app.worker.main import TASK_SPECS
    names = {spec[0] for spec in TASK_SPECS}
    assert "ad-spend-sync" in names
    spec = next(s for s in TASK_SPECS if s[0] == "ad-spend-sync")
    # (name, kind, fn, interval)
    assert spec[1] == "periodic"
    assert callable(spec[2])
    assert spec[3] == 86400


def test_sync_endpoint_calls_sync(monkeypatch):
    import app.campaigns.traffic_router as tr_router
    called = {}
    async def fake_sync(days=30):
        called["days"] = days
        return 5
    monkeypatch.setattr(tr_router, "sync_google_ads_spend", fake_sync)
    import asyncio
    out = asyncio.run(tr_router.sync_google_ads_endpoint())
    assert out == {"synced": 5}
    assert called["days"] == 30

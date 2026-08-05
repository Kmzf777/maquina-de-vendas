import app.campaigns.google_ads as g


def test_parse_spend_rows_maps_cost_micros():
    results = [
        {"campaign": {"id": "111", "name": "Atacado"}, "segments": {"date": "2026-08-01"},
         "metrics": {"costMicros": "1500000"}},
        {"campaign": {"id": "222", "name": "Terceirizacao"}, "segments": {"date": "2026-08-02"},
         "metrics": {"costMicros": "0"}},
    ]
    out = g.parse_spend_rows(results)
    assert out[0] == {"campaign_id": "111", "campaign_name": "Atacado", "date": "2026-08-01", "cost": 1.5}
    assert out[1]["cost"] == 0.0


def test_parse_spend_rows_skips_malformed():
    out = g.parse_spend_rows([{"segments": {"date": "2026-08-01"}}])  # sem campaign/metrics
    assert out == []


def test_google_ads_enabled_false_when_missing(monkeypatch):
    for k in g._REQUIRED_ENV:
        monkeypatch.delenv(k, raising=False)
    assert g.google_ads_enabled() is False


def test_google_ads_enabled_true_when_all_present(monkeypatch):
    for k in g._REQUIRED_ENV:
        monkeypatch.setenv(k, "x")
    assert g.google_ads_enabled() is True


def test_fetch_campaign_spend_noop_when_disabled(monkeypatch):
    for k in g._REQUIRED_ENV:
        monkeypatch.delenv(k, raising=False)
    import asyncio
    assert asyncio.run(g.fetch_campaign_spend("2026-08-01", "2026-08-31")) == []

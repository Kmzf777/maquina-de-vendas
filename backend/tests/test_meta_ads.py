import app.campaigns.meta_ads as m


def test_parse_spend_rows_maps_spend():
    data = [
        {"campaign_id": "1", "campaign_name": "Atacado WA", "spend": "12.50", "date_start": "2026-08-01", "date_stop": "2026-08-01"},
        {"campaign_id": "2", "campaign_name": "Branding", "spend": "0", "date_start": "2026-08-02", "date_stop": "2026-08-02"},
    ]
    out = m.parse_spend_rows(data)
    assert out[0] == {"campaign_id": "1", "campaign_name": "Atacado WA", "date": "2026-08-01", "cost": 12.5}
    assert out[1]["cost"] == 0.0


def test_parse_spend_rows_skips_malformed():
    assert m.parse_spend_rows([{"date_start": "2026-08-01"}]) == []


def test_meta_ads_enabled_requires_token_and_account(monkeypatch):
    for k in ("META_ADS_ACCESS_TOKEN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"):
        monkeypatch.delenv(k, raising=False)
    assert m.meta_ads_enabled() is False
    monkeypatch.setenv("META_ADS_ACCESS_TOKEN", "t")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "123")
    assert m.meta_ads_enabled() is True


def test_fetch_campaign_spend_noop_when_disabled(monkeypatch):
    for k in ("META_ADS_ACCESS_TOKEN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"):
        monkeypatch.delenv(k, raising=False)
    import asyncio
    assert asyncio.run(m.fetch_campaign_spend("2026-08-01", "2026-08-31")) == []


def test_normalize_act_id():
    assert m._act("123456") == "act_123456"
    assert m._act("act_123456") == "act_123456"


def test_parse_ad_campaign_rows_maps_ad_to_campaign():
    data = [
        {"ad_id": "120250281981050163", "campaign_id": "120250281981040163", "campaign_name": "PL | WA"},
        {"ad_id": "120250281981050163", "campaign_id": "120250281981040163", "campaign_name": "PL | WA"},
        {"ad_id": "999", "campaign_id": "", "campaign_name": "sem campanha"},
    ]
    out = m.parse_ad_campaign_rows(data)
    assert out == [{"ad_id": "120250281981050163", "campaign_id": "120250281981040163",
                    "campaign_name": "PL | WA"}]


def test_fetch_ad_campaign_map_noop_when_disabled(monkeypatch):
    for k in ("META_ADS_ACCESS_TOKEN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"):
        monkeypatch.delenv(k, raising=False)
    import asyncio
    assert asyncio.run(m.fetch_ad_campaign_map("2026-08-01", "2026-08-31")) == []

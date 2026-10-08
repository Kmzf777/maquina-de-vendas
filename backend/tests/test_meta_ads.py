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


def _mock_client(monkeypatch, handler):
    import httpx
    real = httpx.AsyncClient
    monkeypatch.setattr(m.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def _env_on(monkeypatch):
    monkeypatch.setenv("META_ADS_ACCESS_TOKEN", "SEGREDO")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "123")


def test_token_vai_no_header_e_nunca_na_url(monkeypatch):
    """O httpx loga a URL completa em INFO; com `access_token=` na query o token ia para o log
    do worker. E a Graph devolve o `paging.next` com o token embutido: ele sai antes de seguir."""
    import asyncio

    import httpx
    _env_on(monkeypatch)
    urls, auths = [], []

    def handler(req: httpx.Request):
        urls.append(str(req.url))
        auths.append(req.headers.get("Authorization"))
        if len(urls) == 1:
            nxt = "https://graph.facebook.com/v21.0/act_123/insights?access_token=SEGREDO&after=CUR&limit=500"
            return httpx.Response(200, json={"data": [{"campaign_id": "1", "campaign_name": "A", "spend": "1",
                                                       "date_start": "2026-08-01"}], "paging": {"next": nxt}})
        return httpx.Response(200, json={"data": []})

    _mock_client(monkeypatch, handler)
    rows = asyncio.run(m.fetch_campaign_spend("2026-08-01", "2026-08-31"))
    assert len(rows) == 1 and len(urls) == 2
    assert all("SEGREDO" not in u and "access_token" not in u for u in urls)
    assert "after=CUR" in urls[1]
    assert auths == ["Bearer SEGREDO", "Bearer SEGREDO"]


def test_mapa_de_anuncios_tambem_usa_o_header(monkeypatch):
    import asyncio

    import httpx
    _env_on(monkeypatch)
    urls, auths = [], []

    def handler(req):
        urls.append(str(req.url))
        auths.append(req.headers.get("Authorization"))
        return httpx.Response(200, json={"data": [{"ad_id": "9", "campaign_id": "1", "campaign_name": "A"}]})

    _mock_client(monkeypatch, handler)
    assert asyncio.run(m.fetch_ad_campaign_map("2026-08-01", "2026-08-31"))[0]["ad_id"] == "9"
    assert "access_token" not in urls[0] and auths == ["Bearer SEGREDO"]


def test_erro_http_nao_carrega_o_token(monkeypatch):
    import asyncio

    import httpx
    import pytest as _pytest
    _env_on(monkeypatch)
    _mock_client(monkeypatch, lambda req: httpx.Response(400, json={"error": {"message": "x"}}))
    with _pytest.raises(m.AdsFetchError) as exc:
        asyncio.run(m.fetch_campaign_spend("2026-08-01", "2026-08-31"))
    assert "SEGREDO" not in str(exc.value)

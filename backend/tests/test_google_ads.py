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


def test_api_version_is_not_a_sunset_one():
    """v21 e anteriores foram descontinuadas: a URL responde 404 (HTML) e o gasto do Google
    parava de sincronizar em silêncio. Guarda contra voltar para uma versão morta."""
    assert g._DEFAULT_API_VERSION not in {"v17", "v18", "v19", "v20", "v21"}
    assert int(g._DEFAULT_API_VERSION.lstrip("v")) >= 22


def test_api_version_overridable_by_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_API_VERSION", "v23")
    assert g._api_version() == "v23"
    monkeypatch.delenv("GOOGLE_ADS_API_VERSION")
    assert g._api_version() == g._DEFAULT_API_VERSION


def test_api_version_padrao_e_v24(monkeypatch):
    """Trava a versão padrão: a próxima troca tem de ser consciente (mudar aqui e no código).
    Sem GOOGLE_ADS_API_VERSION no ambiente, o sync usa v24 (a v22 do código estava a um passo
    do sunset e produção só funcionava porque a env dizia v24)."""
    monkeypatch.delenv("GOOGLE_ADS_API_VERSION", raising=False)
    assert g._DEFAULT_API_VERSION == "v24"
    assert g._api_version() == "v24"
    monkeypatch.setenv("GOOGLE_ADS_API_VERSION", "")
    assert g._api_version() == "v24"


def test_token_que_falha_vira_erro_e_nao_zero_mudo(monkeypatch):
    """Refresh token vencido não pode parecer "dia sem gasto"."""
    import asyncio
    for k in g._REQUIRED_ENV:
        monkeypatch.setenv(k, "x")

    async def sem_token():
        return None
    monkeypatch.setattr(g, "_get_access_token", sem_token)
    import pytest
    with pytest.raises(g.AdsFetchError):
        asyncio.run(g.fetch_campaign_spend("2026-08-01", "2026-08-31"))

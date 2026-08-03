from app.campaigns.traffic_report import derive_channel, build_campaign_report


def test_derive_channel_google_by_gclid():
    assert derive_channel({"gclid": "abc"}) == "Google Ads"


def test_derive_channel_meta_by_fbclid():
    assert derive_channel({"fbclid": "x"}) == "Meta Ads"


def test_derive_channel_meta_by_ctwa():
    assert derive_channel({"ctwa_clid": "x"}) == "Meta Ads"


def test_derive_channel_gclid_wins_over_fbclid():
    assert derive_channel({"gclid": "g", "fbclid": "f"}) == "Google Ads"


def test_derive_channel_organic_by_traffic_type():
    assert derive_channel({"traffic_type": "organic"}) == "Orgânico"


def test_derive_channel_organic_by_utm_source():
    assert derive_channel({"utm_source": "instagram"}) == "Orgânico"


def test_derive_channel_direto_when_no_signal():
    assert derive_channel({}) == "Direto"


def test_derive_channel_ignores_empty_strings():
    assert derive_channel({"gclid": "", "fbclid": "  ", "utm_source": ""}) == "Direto"


# --- Task 2: build_campaign_report ---

def _lead(id, **kw):
    base = {"id": id, "utm_campaign": None, "gclid": "", "fbclid": "", "ctwa_clid": "",
            "utm_source": "", "traffic_type": None}
    base.update(kw)
    return base


def test_build_groups_by_channel_and_campaign():
    leads = [
        _lead("a", gclid="1", utm_campaign="black"),
        _lead("b", gclid="2", utm_campaign="black"),
        _lead("c", fbclid="3", utm_campaign="promo"),
    ]
    out = build_campaign_report(leads, set(), set(), {}, mode="lead", period="30d")
    rows = {(r["channel"], r["campaign"]): r for r in out["rows"]}
    assert rows[("Google Ads", "black")]["leads"] == 2
    assert rows[("Meta Ads", "promo")]["leads"] == 1


def test_build_null_campaign_becomes_placeholder():
    leads = [_lead("a", gclid="1")]
    out = build_campaign_report(leads, set(), set(), {}, mode="lead", period="30d")
    assert out["rows"][0]["campaign"] == "(sem campanha)"


def test_build_metrics_conversas_closer_vendas_receita():
    leads = [_lead("a", gclid="1", utm_campaign="black"),
             _lead("b", gclid="2", utm_campaign="black")]
    sales_by_lead = {"a": {"count": 1, "value": 100.0}}
    out = build_campaign_report(leads, {"a"}, {"a", "b"}, sales_by_lead, mode="lead", period="30d")
    row = out["rows"][0]
    assert row["conversas"] == 1
    assert row["closer"] == 2
    assert row["vendas"] == 1
    assert row["receita"] == 100.0
    assert row["ticket_medio"] == 100.0
    assert row["conversao"] == 0.5


def test_build_ticket_and_conversao_zero_safe():
    leads = [_lead("a", gclid="1", utm_campaign="x")]
    out = build_campaign_report(leads, set(), set(), {}, mode="lead", period="30d")
    row = out["rows"][0]
    assert row["ticket_medio"] == 0.0
    assert row["conversao"] == 0.0


def test_build_total_aggregates_all_rows():
    leads = [_lead("a", gclid="1", utm_campaign="x"),
             _lead("b", fbclid="2", utm_campaign="y")]
    sales_by_lead = {"a": {"count": 1, "value": 50.0}, "b": {"count": 2, "value": 30.0}}
    out = build_campaign_report(leads, {"a"}, {"a"}, sales_by_lead, mode="lead", period="30d")
    assert out["total"] == {"leads": 2, "conversas": 1, "closer": 1, "vendas": 3, "receita": 80.0}

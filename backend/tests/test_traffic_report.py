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
    # vendas conta leads distintos com >=1 venda (a e b => 2), receita soma tudo (80.0)
    assert out["total"] == {"leads": 2, "conversas": 1, "closer": 1, "vendas": 2, "receita": 80.0}


# --- Task 3: traffic_report e campaign_leads (I/O fail-soft) ---

import app.campaigns.traffic_report as tr


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def not_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def execute(self):
        class R: pass
        r = R(); r.data = self._rows; return r


class _FakeSupabase:
    def __init__(self, tables):
        self._tables = tables
    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


def test_traffic_report_lead_mode_end_to_end(monkeypatch):
    tables = {
        "leads": [
            {"id": "a", "gclid": "1", "fbclid": "", "ctwa_clid": "", "utm_source": "",
             "utm_campaign": "black", "traffic_type": "paid", "created_at": "2026-08-01T00:00:00Z"},
        ],
        "conversations": [{"lead_id": "a", "last_customer_message_at": "2026-08-02T00:00:00Z"}],
        "deals": [{"lead_id": "a", "stage_id": "s2", "pipeline_id": "p1"}],
        "pipeline_stages": [
            {"id": "s1", "pipeline_id": "p1", "key": "entrada", "order_index": 0},
            {"id": "s2", "pipeline_id": "p1", "key": "qualificado", "order_index": 1},
        ],
        "sales": [{"lead_id": "a", "value": 200.0, "sold_at": "2026-08-03T00:00:00Z"}],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    out = tr.traffic_report(period="30d", mode="lead")
    row = out["rows"][0]
    assert (row["channel"], row["campaign"]) == ("Google Ads", "black")
    assert row["conversas"] == 1 and row["closer"] == 1 and row["vendas"] == 1
    assert row["receita"] == 200.0


def test_traffic_report_sale_mode_end_to_end(monkeypatch):
    # No modo "sale", os leads são hidratados a partir dos lead_ids presentes em sales.
    tables = {
        "leads": [
            {"id": "a", "gclid": "1", "fbclid": "", "ctwa_clid": "", "utm_source": "",
             "utm_campaign": "black", "traffic_type": "paid", "created_at": "2026-01-01T00:00:00Z"},
        ],
        "conversations": [],
        "deals": [],
        "pipeline_stages": [],
        "sales": [{"lead_id": "a", "value": 350.0, "sold_at": "2026-08-03T00:00:00Z"}],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    out = tr.traffic_report(period="30d", mode="sale")
    row = out["rows"][0]
    assert (row["channel"], row["campaign"]) == ("Google Ads", "black")
    assert row["vendas"] == 1
    assert row["receita"] == 350.0


def test_closer_stage_before_qualificado_not_counted(monkeypatch):
    # Deal parado no estágio ANTES de qualificado (order_index 0) não conta como closer.
    tables = {
        "leads": [
            {"id": "a", "gclid": "1", "fbclid": "", "ctwa_clid": "", "utm_source": "",
             "utm_campaign": "black", "traffic_type": "paid", "created_at": "2026-08-01T00:00:00Z"},
        ],
        "conversations": [],
        "deals": [{"lead_id": "a", "stage_id": "s1", "pipeline_id": "p1"}],
        "pipeline_stages": [
            {"id": "s1", "pipeline_id": "p1", "key": "entrada", "order_index": 0},
            {"id": "s2", "pipeline_id": "p1", "key": "qualificado", "order_index": 1},
        ],
        "sales": [],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    out = tr.traffic_report(period="30d", mode="lead")
    assert out["rows"][0]["closer"] == 0


def test_closer_cross_pipeline_isolation(monkeypatch):
    # Cada pipeline tem seu próprio threshold de "qualificado".
    # Lead "a": deal no pipeline p1 com order_index 1 (abaixo do qualificado p1=2) -> NÃO closer,
    # mesmo que 1 atenderia o threshold do p2 (=1).
    tables = {
        "leads": [
            {"id": "a", "gclid": "1", "fbclid": "", "ctwa_clid": "", "utm_source": "",
             "utm_campaign": "black", "traffic_type": "paid", "created_at": "2026-08-01T00:00:00Z"},
        ],
        "conversations": [],
        "deals": [{"lead_id": "a", "stage_id": "p1s1", "pipeline_id": "p1"}],
        "pipeline_stages": [
            {"id": "p1s0", "pipeline_id": "p1", "key": "entrada", "order_index": 0},
            {"id": "p1s1", "pipeline_id": "p1", "key": "contato", "order_index": 1},
            {"id": "p1s2", "pipeline_id": "p1", "key": "qualificado", "order_index": 2},
            {"id": "p2s0", "pipeline_id": "p2", "key": "entrada", "order_index": 0},
            {"id": "p2s1", "pipeline_id": "p2", "key": "qualificado", "order_index": 1},
        ],
        "sales": [],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    out = tr.traffic_report(period="30d", mode="lead")
    assert out["rows"][0]["closer"] == 0


def test_traffic_report_failsoft_on_error(monkeypatch):
    class _Boom:
        def table(self, *a, **k): raise RuntimeError("db down")
    monkeypatch.setattr(tr, "get_supabase", lambda: _Boom())
    out = tr.traffic_report(period="30d", mode="lead")
    assert out["rows"] == [] and out["total"]["leads"] == 0


def test_campaign_leads_filters_by_channel_and_campaign(monkeypatch):
    tables = {
        "leads": [
            {"id": "a", "name": "Ana", "phone": "5511", "gclid": "1", "fbclid": "",
             "ctwa_clid": "", "utm_source": "", "utm_medium": "cpc", "utm_campaign": "black",
             "traffic_type": "paid", "created_at": "2026-08-01T00:00:00Z"},
            {"id": "b", "name": "Bob", "phone": "5512", "gclid": "", "fbclid": "2",
             "ctwa_clid": "", "utm_source": "", "utm_medium": "cpc", "utm_campaign": "black",
             "traffic_type": "paid", "created_at": "2026-08-01T00:00:00Z"},
        ],
        "conversations": [], "deals": [], "pipeline_stages": [], "sales": [],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    leads = tr.campaign_leads(channel="Google Ads", campaign="black", period="30d", mode="lead")
    assert [l["lead_id"] for l in leads] == ["a"]
    assert leads[0]["comprou"] is False


# --- Task 4: router ---

def test_router_exposes_expected_paths():
    from app.campaigns.traffic_router import router
    paths = {r.path for r in router.routes}
    assert "/api/traffic/report" in paths
    assert "/api/traffic/leads" in paths

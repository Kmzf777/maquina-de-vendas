import re
from app.campaigns.traffic_report import derive_channel, build_campaign_report, _resolve_window


def test_resolve_window_preset_30d_has_lower_no_upper():
    lo, hi = _resolve_window("30d", None, None)
    assert lo is not None and hi is None
    assert re.match(r"\d{4}-\d{2}-\d{2}T", lo)


def test_resolve_window_all_is_open():
    assert _resolve_window("all", None, None) == (None, None)


def test_resolve_window_explicit_range_takes_precedence():
    lo, hi = _resolve_window("30d", "2026-08-01", "2026-08-31")
    assert lo == "2026-08-01T00:00:00+00:00"
    assert hi == "2026-08-31T23:59:59.999999+00:00"


def test_resolve_window_ignores_malformed_dates():
    # datas inválidas → cai no preset
    lo, hi = _resolve_window("7d", "nao-e-data", "")
    assert lo is not None and hi is None


def test_resolve_window_only_from():
    lo, hi = _resolve_window("all", "2026-08-10", None)
    assert lo == "2026-08-10T00:00:00+00:00" and hi is None


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
    assert derive_channel({}) == "Sem rastreio"


def test_derive_channel_ignores_empty_strings():
    assert derive_channel({"gclid": "", "fbclid": "  ", "utm_source": ""}) == "Sem rastreio"


def test_derive_channel_meta_by_utm_source_metaads():
    # Campanhas Meta da gestora: utm_source=metaads, utm_medium=whatsapp, SEM click-id.
    assert derive_channel({"utm_source": "metaads", "utm_medium": "whatsapp",
                           "utm_campaign": "atacado_wa_01"}) == "Meta Ads"
    assert derive_channel({"utm_source": "MetaAds"}) == "Meta Ads"  # case-insensitive


def test_derive_channel_google_by_source_and_paid_medium():
    assert derive_channel({"utm_source": "google", "utm_medium": "cpc"}) == "Google Ads"
    assert derive_channel({"utm_source": "google", "utm_medium": "pmax"}) == "Google Ads"


def test_derive_channel_google_source_organic_medium_stays_organic():
    # SEO/orgânico do Google NÃO vira Google Ads (meio não-pago).
    assert derive_channel({"utm_source": "google", "utm_medium": "organic"}) == "Orgânico"


def test_derive_channel_instagram_bio_stays_organic():
    # Tráfego orgânico (link da bio) NÃO pode virar Meta Ads.
    assert derive_channel({"utm_source": "instagram", "utm_medium": "bio"}) == "Orgânico"


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


def test_build_metrics_clientes_pedidos_receita():
    leads = [_lead("a", gclid="1", utm_campaign="black"),
             _lead("b", gclid="2", utm_campaign="black")]
    sales_by_lead = {"a": {"count": 1, "value": 100.0}}
    out = build_campaign_report(leads, {"a"}, {"a", "b"}, sales_by_lead, mode="lead", period="30d")
    row = out["rows"][0]
    assert row["conversas"] == 1
    assert row["closer"] == 2
    assert row["clientes"] == 1
    assert row["pedidos"] == 1
    assert row["receita"] == 100.0
    assert row["ticket_medio"] == 100.0
    assert row["conversao"] == 0.5


def test_build_repeat_purchase_counts_pedidos_not_clientes():
    # 1 lead que comprou 2x: clientes=1, pedidos=2, ticket=receita/2, conversao=clientes/leads
    leads = [_lead("a", gclid="1", utm_campaign="x")]
    sales_by_lead = {"a": {"count": 2, "value": 300.0}}
    out = build_campaign_report(leads, set(), set(), sales_by_lead, mode="lead", period="30d")
    row = out["rows"][0]
    assert row["clientes"] == 1
    assert row["pedidos"] == 2
    assert row["receita"] == 300.0
    assert row["ticket_medio"] == 150.0
    assert row["conversao"] == 1.0


def test_build_ticket_and_conversao_zero_safe():
    leads = [_lead("a", gclid="1", utm_campaign="x")]
    out = build_campaign_report(leads, set(), set(), {}, mode="lead", period="30d")
    row = out["rows"][0]
    assert row["ticket_medio"] == 0.0
    assert row["conversao"] == 0.0


def test_build_total_and_subtotals_have_clientes_and_pedidos():
    leads = [_lead("a", gclid="1", utm_campaign="x"),
             _lead("b", fbclid="2", utm_campaign="y")]
    sales_by_lead = {"a": {"count": 1, "value": 50.0}, "b": {"count": 2, "value": 30.0}}
    out = build_campaign_report(leads, {"a"}, {"a"}, sales_by_lead, mode="lead", period="30d")
    assert out["total"] == {"leads": 2, "conversas": 1, "closer": 1,
                            "clientes": 2, "pedidos": 3, "receita": 80.0,
                            "investimento": 0.0, "roas": None}
    assert out["channel_subtotals"]["Google Ads"] == {
        "leads": 1, "conversas": 1, "closer": 1, "clientes": 1, "pedidos": 1, "receita": 50.0,
        "investimento": 0.0, "roas": None}
    assert out["channel_subtotals"]["Meta Ads"] == {
        "leads": 1, "conversas": 0, "closer": 0, "clientes": 1, "pedidos": 2, "receita": 30.0,
        "investimento": 0.0, "roas": None}


# --- Task 3: traffic_report e campaign_leads (I/O fail-soft) ---

import app.campaigns.traffic_report as tr


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
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
    assert row["conversas"] == 1 and row["closer"] == 1 and row["clientes"] == 1
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
    assert row["clientes"] == 1
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
    assert out["channel_subtotals"] == {}


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


def test_campaign_leads_includes_sold_at_and_created_at(monkeypatch):
    """campaign_leads deve expor sold_at (data da venda) e created_at (entrada no CRM) por lead."""
    tables = {
        "leads": [
            {"id": "a", "name": "Ana", "phone": "5511", "gclid": "1", "fbclid": "",
             "ctwa_clid": "", "utm_source": "", "utm_medium": "cpc", "utm_campaign": "black",
             "traffic_type": "paid", "created_at": "2026-07-10T00:00:00Z"},
        ],
        "conversations": [], "deals": [], "pipeline_stages": [],
        "sales": [
            {"lead_id": "a", "value": 300.0, "sold_at": "2026-07-15T00:00:00Z"},
            {"lead_id": "a", "value": 150.0, "sold_at": "2026-07-20T00:00:00Z"},  # latest
        ],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    leads = tr.campaign_leads(channel="Google Ads", campaign="black", period="30d", mode="lead")
    assert len(leads) == 1
    lead = leads[0]
    assert lead["created_at"] == "2026-07-10T00:00:00Z"
    assert lead["comprou"] is True
    # sold_at deve ser a data mais recente entre as vendas do lead.
    assert lead["sold_at"] == "2026-07-20T00:00:00Z"


def test_campaign_leads_sold_at_none_when_no_sale(monkeypatch):
    """sold_at deve ser None para leads sem venda."""
    tables = {
        "leads": [
            {"id": "a", "name": "Ana", "phone": "5511", "gclid": "1", "fbclid": "",
             "ctwa_clid": "", "utm_source": "", "utm_medium": "cpc", "utm_campaign": "black",
             "traffic_type": "paid", "created_at": "2026-07-10T00:00:00Z"},
        ],
        "conversations": [], "deals": [], "pipeline_stages": [], "sales": [],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    leads = tr.campaign_leads(channel="Google Ads", campaign="black", period="30d", mode="lead")
    assert leads[0]["sold_at"] is None


# --- Task 4: router ---

def test_router_exposes_expected_paths():
    from app.campaigns.traffic_router import router
    paths = {r.path for r in router.routes}
    assert "/api/traffic/report" in paths
    assert "/api/traffic/leads" in paths


def test_router_report_forwards_dates(monkeypatch):
    import app.campaigns.traffic_router as tr_router
    captured = {}
    def fake_report(period, mode, date_from=None, date_to=None):
        captured.update(period=period, mode=mode, date_from=date_from, date_to=date_to)
        return {"ok": True}
    monkeypatch.setattr(tr_router, "traffic_report", fake_report)
    import asyncio
    asyncio.run(tr_router.traffic_report_endpoint(period="30d", mode="lead",
                                                  date_from="2026-08-01", date_to="2026-08-31"))
    assert captured["date_from"] == "2026-08-01" and captured["date_to"] == "2026-08-31"


# --- Task 5 (plan): ROAS tests for build_campaign_report ---

from app.campaigns.traffic_report import build_campaign_report as _bcr


def test_build_roas_only_for_google_rows():
    leads = [_lead("a", gclid="1", utm_campaign="Atacado"),
             _lead("b", fbclid="2", utm_campaign="MetaCamp")]
    sales = {"a": {"count": 1, "value": 300.0}, "b": {"count": 1, "value": 100.0}}
    spend = {"atacado": 100.0}  # normalizado (trim+lower)
    out = _bcr(leads, set(), set(), sales, mode="lead", period="30d", spend_by_campaign=spend)
    rows = {(r["channel"], r["campaign"]): r for r in out["rows"]}
    g = rows[("Google Ads", "Atacado")]
    assert g["investimento"] == 100.0 and g["roas"] == 3.0
    m = rows[("Meta Ads", "MetaCamp")]
    assert m["investimento"] == 0.0 and m["roas"] is None
    # Total ROAS considera só receita das linhas Google / investimento total
    assert out["total"]["investimento"] == 100.0
    assert out["total"]["roas"] == 3.0


def test_build_roas_none_when_no_spend():
    leads = [_lead("a", gclid="1", utm_campaign="SemSpend")]
    sales = {"a": {"count": 1, "value": 50.0}}
    out = _bcr(leads, set(), set(), sales, mode="lead", period="30d", spend_by_campaign={})
    row = out["rows"][0]
    assert row["investimento"] == 0.0 and row["roas"] is None


# --- Task 1 (plan 2026-08-06): campaign_detail + timeseries ---

from datetime import date
from app.campaigns.traffic_report import build_campaign_timeseries, _empty_summary


def test_empty_summary_has_all_keys():
    s = _empty_summary("Google Ads", "atacado")
    for k in ("channel","campaign","leads","conversas","closer","clientes","pedidos",
              "receita","ticket_medio","conversao","investimento","roas"):
        assert k in s
    assert s["channel"] == "Google Ads" and s["campaign"] == "atacado"
    assert s["leads"] == 0 and s["roas"] is None


def test_build_campaign_timeseries_buckets_by_day():
    days = [date(2026, 8, 1), date(2026, 8, 2)]
    leads = [{"created_at": "2026-08-01T10:00:00+00:00"},
             {"created_at": "2026-08-01T12:00:00+00:00"},
             {"created_at": "2026-08-02T09:00:00+00:00"}]
    sales = [{"value": 100.0, "sold_at": "2026-08-02T15:00:00+00:00"}]
    ts = build_campaign_timeseries(days, leads, sales)
    by = {p["date"]: p for p in ts}
    assert by["2026-08-01"]["leads"] == 2 and by["2026-08-01"]["vendas"] == 0
    assert by["2026-08-02"]["leads"] == 1 and by["2026-08-02"]["vendas"] == 1
    assert by["2026-08-02"]["receita"] == 100.0


def test_campaign_detail_end_to_end(monkeypatch):
    import app.campaigns.traffic_report as tr
    tables = {
        "leads": [{"id": "a", "gclid": "1", "fbclid": "", "ctwa_clid": "", "utm_source": "",
                   "utm_campaign": "atacado", "traffic_type": "paid", "name": "Ana", "phone": "5511",
                   "created_at": "2026-08-01T10:00:00+00:00"}],
        "conversations": [], "deals": [], "pipeline_stages": [], "ad_spend": [],
        "sales": [{"lead_id": "a", "value": 200.0, "sold_at": "2026-08-02T10:00:00+00:00"}],
    }
    # Fake supabase reutilizando o _FakeSupabase já existente nos testes deste arquivo.
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    out = tr.campaign_detail("Google Ads", "atacado", period="30d", mode="lead")
    assert out["summary"]["channel"] == "Google Ads"
    assert out["summary"]["leads"] == 1
    assert isinstance(out["leads"], list) and out["leads"][0]["lead_id"] == "a"
    assert isinstance(out["timeseries"], list)


# --- Task 2 (plan 2026-08-06): endpoint /api/traffic/campaign ---

def test_router_exposes_campaign_path():
    from app.campaigns.traffic_router import router
    assert "/api/traffic/campaign" in {r.path for r in router.routes}

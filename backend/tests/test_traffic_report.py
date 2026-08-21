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
        self._range = None

    def select(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def not_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def range(self, start, end):
        # Fatia de verdade (inclusiva nas duas pontas, como o PostgREST) — um fake que
        # ignorasse o range faria a paginação parecer certa mesmo quebrada.
        self._range = (start, end)
        return self

    def execute(self):
        class R: pass
        r = R()
        rows = self._rows
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        r.data = rows
        return r


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
    spend_by_channel = {"Google Ads": [{"campaign_id": "c1", "campaign_name": "Atacado", "cost": 100.0}]}
    out = _bcr(leads, set(), set(), sales, mode="lead", period="30d", spend_by_channel=spend_by_channel)
    rows = {(r["channel"], r["campaign"]): r for r in out["rows"]}
    g = rows[("Google Ads", "Atacado")]
    assert g["investimento"] == 100.0 and g["roas"] == 3.0
    m = rows[("Meta Ads", "MetaCamp")]
    assert m["investimento"] == 0.0 and m["roas"] is None
    # Total ROAS considera só receita das linhas com canal em spend_by_channel / investimento total
    assert out["total"]["investimento"] == 100.0
    assert out["total"]["roas"] == 3.0


def test_build_roas_none_when_no_spend():
    leads = [_lead("a", gclid="1", utm_campaign="SemSpend")]
    sales = {"a": {"count": 1, "value": 50.0}}
    out = _bcr(leads, set(), set(), sales, mode="lead", period="30d", spend_by_channel={})
    row = out["rows"][0]
    assert row["investimento"] == 0.0 and row["roas"] is None


def test_build_roas_google_and_meta_rows():
    leads = [_lead("a", gclid="1", utm_campaign="atacado"),
             _lead("b", fbclid="2", utm_campaign="pl_wa_01")]
    sales = {"a": {"count": 1, "value": 300.0}, "b": {"count": 1, "value": 200.0}}
    spend_by_channel = {
        "Google Ads": [{"campaign_id": "c1", "campaign_name": "Atacado", "cost": 100.0}],
        "Meta Ads": [{"campaign_id": "m1", "campaign_name": "pl_wa_01", "cost": 50.0}],
    }
    out = build_campaign_report(leads, set(), set(), sales, mode="lead", period="30d",
                                spend_by_channel=spend_by_channel)
    rows = {(r["channel"], r["campaign"]): r for r in out["rows"]}
    # O rótulo agora é o nome da campanha na plataforma, não o slug de utm.
    g = rows[("Google Ads", "Atacado")]
    assert g["investimento"] == 100.0 and g["roas"] == 3.0
    mrow = rows[("Meta Ads", "pl_wa_01")]
    assert mrow["investimento"] == 50.0 and mrow["roas"] == 4.0
    # total ROAS = (receita Google 300 + receita Meta 200) / investimento 150 = 500/150
    assert out["total"]["investimento"] == 150.0
    assert out["total"]["roas"] == round(500.0 / 150.0, 2)


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


# ---------------------------------------------------------------------------------------
# Atribuição de investimento ancorada na CAMPANHA (regressões dos bugs do /trafego).
# ---------------------------------------------------------------------------------------

_GADS = [
    {"campaign_id": "c_terc", "campaign_name": "Leads-Search | Terceirização | 20.03.24", "cost": 948.10},
    {"campaign_id": "c_atac", "campaign_name": "Leads-Search | Atacado | 12.07.22 | LP Vídeo", "cost": 692.40},
    {"campaign_id": "c_pmax", "campaign_name": "PMAX | Atacado", "cost": 654.50},
]


def _gads_report(leads):
    return _bcr(leads, set(), set(), {}, mode="lead", period="30d",
                spend_by_channel={"Google Ads": _GADS})


def test_spend_not_duplicated_across_utm_variants():
    """Dois slugs da MESMA campanha viram UMA linha e o custo entra uma vez só.

    Era o bug principal: 'terceirizacao' e 'leads_search_terceirizacao' cobravam R$ 948,10
    cada um, então o investimento do Google aparecia inflado (R$ 5.974,81 vs R$ 2.295,00)."""
    leads = [_lead("a", gclid="1", utm_campaign="terceirizacao"),
             _lead("b", gclid="2", utm_campaign="leads_search_terceirizacao")]
    out = _gads_report(leads)
    terc = [r for r in out["rows"] if r["campaign"].startswith("Leads-Search | Terceiriza")]
    assert len(terc) == 1, "slugs da mesma campanha têm de colapsar numa linha"
    assert terc[0]["leads"] == 2
    assert terc[0]["investimento"] == 948.10


def test_channel_investment_equals_real_platform_spend():
    """Invariante central: o subtotal do canal é EXATAMENTE o gasto da plataforma na janela."""
    leads = [_lead("a", gclid="1", utm_campaign="terceirizacao"),
             _lead("b", gclid="2", utm_campaign="leads_search_terceirizacao"),
             _lead("c", gclid="3", utm_campaign="atacado_video"),
             _lead("d", gclid="4", utm_campaign="lp_video"),
             _lead("e", gclid="5", utm_campaign="leads_search_atacado_sitelink_02"),
             _lead("f", gclid="6", utm_campaign="pmax_atacado_sitelink_03")]
    out = _gads_report(leads)
    assert out["channel_subtotals"]["Google Ads"]["investimento"] == 2295.00
    assert sum(r["investimento"] for r in out["rows"]) == 2295.00


def test_utm_medium_breaks_ambiguity_instead_of_zeroing():
    """'atacado' cabe na Search e na PMAX; o medium decide. Antes virava investimento 0,00."""
    leads = [_lead("a", gclid="1", utm_campaign="atacado", utm_medium="pmax")]
    out = _gads_report(leads)
    row = next(r for r in out["rows"] if r["leads"] == 1)
    assert row["campaign"] == "PMAX | Atacado"
    assert row["investimento"] == 654.50


def test_campaign_with_spend_and_no_leads_still_appears():
    """Campanha que gastou sem gerar lead não pode sumir — sumir subestima o investimento."""
    out = _gads_report([_lead("a", gclid="1", utm_campaign="terceirizacao")])
    pmax = next(r for r in out["rows"] if r["campaign"] == "PMAX | Atacado")
    assert pmax["leads"] == 0 and pmax["investimento"] == 654.50
    assert pmax["roas"] == 0.0


def test_unresolved_slug_goes_to_unattributed_row_with_no_spend():
    """Sem casamento confiável, o lead vai para '(não atribuído)' — nunca para a campanha errada."""
    out = _gads_report([_lead("a", gclid="1", utm_campaign="campanha_que_nao_existe")])
    un = next(r for r in out["rows"] if r["campaign"].startswith("(não atribuído)"))
    assert un["leads"] == 1 and un["investimento"] == 0.0
    assert "campanha_que_nao_existe" in un["campaign"]


def test_meta_lead_attributed_by_ad_id():
    """Lead de CTWA não tem utm_campaign: a campanha vem do anúncio (meta_ad_id)."""
    meta = [{"campaign_id": "m_pl", "campaign_name": "PL | WA | 10.07.26", "cost": 674.98}]
    leads = [_lead("a", ctwa_clid="x", utm_campaign="")]
    out = _bcr(leads, set(), set(), {"a": {"count": 1, "value": 1000.0}}, mode="lead", period="30d",
               spend_by_channel={"Meta Ads": meta}, campaign_id_by_lead={"a": "m_pl"})
    row = next(r for r in out["rows"] if r["campaign"] == "PL | WA | 10.07.26")
    assert row["leads"] == 1 and row["investimento"] == 674.98
    assert row["roas"] == round(1000.0 / 674.98, 2)


def test_meta_channel_roas_correct_even_without_per_lead_attribution():
    """Sem meta_ad_id (leads antigos) a campanha fica '(não atribuído)', mas o ROAS do CANAL
    continua certo — o investimento vem do lado da campanha, não do lead."""
    meta = [{"campaign_id": "m_pl", "campaign_name": "PL | WA", "cost": 100.0},
            {"campaign_id": "m_br", "campaign_name": "Branding", "cost": 100.0}]
    leads = [_lead("a", ctwa_clid="x", utm_campaign="")]
    out = _bcr(leads, set(), set(), {"a": {"count": 1, "value": 400.0}}, mode="lead", period="30d",
               spend_by_channel={"Meta Ads": meta})
    sub = out["channel_subtotals"]["Meta Ads"]
    assert sub["investimento"] == 200.0
    assert sub["roas"] == 2.0


def test_resolve_campaign_id_prefers_exact_name():
    campaigns = tr._index_campaigns([
        {"campaign_id": "a", "campaign_name": "Atacado", "cost": 1.0},
        {"campaign_id": "b", "campaign_name": "Atacado | LP", "cost": 1.0},
    ])
    assert tr.resolve_campaign_id("atacado", "", campaigns) == "a"


def test_resolve_campaign_id_returns_none_when_truly_ambiguous():
    campaigns = tr._index_campaigns([
        {"campaign_id": "a", "campaign_name": "Search | Atacado", "cost": 1.0},
        {"campaign_id": "b", "campaign_name": "Display | Atacado", "cost": 1.0},
    ])
    assert tr.resolve_campaign_id("atacado", "", campaigns) is None


def test_resolve_campaign_id_ignores_sitelink_and_dates():
    campaigns = tr._index_campaigns(
        [{"campaign_id": "a", "campaign_name": "PMAX | Atacado", "cost": 1.0}])
    assert tr.resolve_campaign_id("pmax_atacado_sitelink_03", "", campaigns) == "a"


def test_fetch_all_pages_past_the_postgrest_cap():
    """O PostgREST corta em 1.000 linhas sem avisar; _fetch_all tem de percorrer tudo.

    Era o motivo de o /trafego reportar 1.000 leads numa janela que tinha 2.324."""
    rows = [{"id": str(i)} for i in range(2324)]
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return _FakeQuery(rows)

    out = tr._fetch_all(build)
    assert len(out) == 2324
    assert calls["n"] == 3  # 1000 + 1000 + 324


def test_traffic_report_reads_every_lead_not_just_first_page(monkeypatch):
    tables = {
        "leads": [{"id": str(i), "gclid": "g", "utm_campaign": "black",
                   "created_at": "2026-08-01T00:00:00Z"} for i in range(1500)],
        "conversations": [], "deals": [], "pipeline_stages": [], "sales": [], "ad_spend": [],
    }
    monkeypatch.setattr(tr, "get_supabase", lambda: _FakeSupabase(tables))
    out = tr.traffic_report(period="30d", mode="lead")
    assert out["total"]["leads"] == 1500


def test_drilldown_selects_by_platform_campaign_not_raw_utm():
    """O rótulo da linha é o nome da campanha na plataforma; o lead guarda o slug de utm.

    Comparar rótulo com utm_campaign cru acharia ZERO lead e o drill-down abriria vazio."""
    campaigns = tr._index_campaigns(_GADS)
    leads = [_lead("a", gclid="1", utm_campaign="terceirizacao"),
             _lead("b", gclid="2", utm_campaign="leads_search_terceirizacao"),
             _lead("c", gclid="3", utm_campaign="pmax_atacado")]
    got = tr.select_campaign_leads(leads, "Google Ads",
                                   "Leads-Search | Terceirização | 20.03.24", campaigns)
    assert {l["id"] for l in got} == {"a", "b"}


def test_drilldown_unattributed_row_selects_its_own_slug():
    campaigns = tr._index_campaigns(_GADS)
    leads = [_lead("a", gclid="1", utm_campaign="campanha_fantasma"),
             _lead("b", gclid="2", utm_campaign="terceirizacao")]
    got = tr.select_campaign_leads(leads, "Google Ads",
                                   "(não atribuído) · campanha_fantasma", campaigns)
    assert [l["id"] for l in got] == ["a"]


def test_drilldown_uses_meta_ad_id_when_present():
    campaigns = tr._index_campaigns(
        [{"campaign_id": "m_pl", "campaign_name": "PL | WA | 10.07.26", "cost": 10.0}])
    leads = [_lead("a", ctwa_clid="x"), _lead("b", ctwa_clid="y")]
    got = tr.select_campaign_leads(leads, "Meta Ads", "PL | WA | 10.07.26", campaigns,
                                   {"a": "m_pl"})
    assert [l["id"] for l in got] == ["a"]


def test_drilldown_non_paid_channel_still_matches_raw_utm():
    leads = [_lead("a", utm_source="instagram", utm_campaign="bio"),
             _lead("b", utm_source="instagram", utm_campaign="outra")]
    got = tr.select_campaign_leads(leads, "Orgânico", "bio", {})
    assert [l["id"] for l in got] == ["a"]

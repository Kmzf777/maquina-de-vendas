"""Relatório geral do /trafego (bloco acima da tabela) — build_report_summary é puro."""
import app.campaigns.traffic_report as tr
from app.campaigns.traffic_report import (
    build_campaign_report, build_report_summary, _empty_report, _sales_by_lead,
)


def _t(leads=0, conversas=0, closer=0, clientes=0, pedidos=0, receita=0.0, investimento=0.0, roas=None):
    return {"leads": leads, "conversas": conversas, "closer": closer, "clientes": clientes,
            "pedidos": pedidos, "receita": receita, "investimento": investimento, "roas": roas}


def _report(total, subtotals=None, rows=None, mode="lead"):
    return {"mode": mode, "period": "30d", "rows": rows or [], "total": total,
            "channel_subtotals": subtotals or {}}


def test_empty_report_carries_summary_with_nulls():
    s = _empty_report("lead", "30d")["summary"]
    assert s["funnel"]["leads"] == 0
    assert s["funnel"]["taxa_conversa"] is None
    assert s["funnel"]["gargalo"] is None
    assert s["cost"]["cpl"] is None and s["cost"]["roas"] is None
    assert s["channels"] == []
    assert s["timing_quality"]["dias_ate_compra_mediana"] is None
    assert s["timing_quality"]["amostra_dias"] == 0


def test_funnel_rates_and_bottleneck():
    s = build_report_summary(_report(_t(leads=100, conversas=50, closer=10, clientes=5)), [], {})
    f = s["funnel"]
    assert (f["taxa_conversa"], f["taxa_closer"], f["taxa_cliente"], f["taxa_total"]) == (0.5, 0.2, 0.5, 0.05)
    assert f["gargalo"] == "closer"


def test_bottleneck_tie_picks_first_stage():
    s = build_report_summary(_report(_t(leads=100, conversas=50, closer=25, clientes=20)), [], {})
    assert s["funnel"]["gargalo"] == "conversa"


def test_cost_divides_by_paid_leads_only():
    subs = {
        "Google Ads": _t(leads=10, conversas=5, closer=2, clientes=1, receita=300.0, investimento=100.0),
        "Orgânico": _t(leads=90, conversas=60, closer=20, clientes=9, receita=900.0),
    }
    s = build_report_summary(_report(_t(leads=100, conversas=65, closer=22, clientes=10), subs), [], {})
    c = s["cost"]
    assert c["leads"] == 10 and c["clientes"] == 1
    assert (c["cpl"], c["custo_conversa"], c["custo_closer"], c["cac"]) == (10.0, 20.0, 50.0, 100.0)
    assert c["investimento"] == 100.0 and c["receita"] == 300.0 and c["roas"] == 3.0


def test_cost_is_null_without_spend():
    subs = {"Orgânico": _t(leads=5, conversas=3, closer=1, clientes=1, receita=50.0)}
    c = build_report_summary(_report(_t(leads=5, conversas=3, closer=1, clientes=1), subs), [], {})["cost"]
    assert c["investimento"] == 0.0
    assert c["cpl"] is None and c["cac"] is None and c["roas"] is None


def test_channels_fixed_order_and_empty_channel_omitted():
    subs = {
        "Sem rastreio": _t(leads=1),
        "Outro": _t(leads=1),
        "Orgânico": _t(leads=1),
        "Meta Ads": _t(),
        "Google Ads": _t(leads=2, conversas=1),
    }
    chans = build_report_summary(_report(_t(leads=5), subs), [], {})["channels"]
    assert [c["channel"] for c in chans] == ["Google Ads", "Orgânico", "Sem rastreio", "Outro"]
    assert chans[0]["taxa_conversa"] == 0.5


def test_paid_channel_with_spend_and_no_leads_is_kept():
    subs = {"Meta Ads": _t(investimento=40.0)}
    chans = build_report_summary(_report(_t(), subs), [], {})["channels"]
    assert [c["channel"] for c in chans] == ["Meta Ads"]
    assert chans[0]["taxa_conversa"] is None


def test_channel_leads_sum_to_funnel_total():
    leads = [
        {"id": "g", "gclid": "x", "created_at": "2026-09-01T12:00:00+00:00"},
        {"id": "m", "fbclid": "y", "created_at": "2026-09-01T12:00:00+00:00"},
        {"id": "n", "created_at": "2026-09-01T12:00:00+00:00"},
    ]
    report = build_campaign_report(leads, {"g", "n"}, {"g"}, {}, "lead", "30d")
    s = build_report_summary(report, leads, {})
    assert sum(c["leads"] for c in s["channels"]) == s["funnel"]["leads"] == 3


def test_days_to_purchase_median_drops_negative_and_invalid():
    leads = [
        {"id": "a", "created_at": "2026-09-01T12:00:00+00:00"},
        {"id": "b", "created_at": "2026-09-01T12:00:00Z"},
        # importado do Bling: created_at = data da importação, compra ANTERIOR -> descartado
        {"id": "c", "created_at": "2026-09-20T12:00:00+00:00"},
        {"id": "d", "created_at": "nao-e-data"},
        {"id": "e", "created_at": "2026-09-01T12:00:00+00:00"},  # sem venda
    ]
    sales = {
        "a": {"count": 1, "value": 10.0, "first_sold_at": "2026-09-11T12:00:00+00:00"},
        "b": {"count": 1, "value": 10.0, "first_sold_at": "2026-09-05T12:00:00+00:00"},
        "c": {"count": 1, "value": 10.0, "first_sold_at": "2026-08-01T12:00:00+00:00"},
        "d": {"count": 1, "value": 10.0, "first_sold_at": "2026-09-05T12:00:00+00:00"},
    }
    tq = build_report_summary(_report(_t(leads=5, clientes=4, pedidos=4)), leads, sales)["timing_quality"]
    assert tq["dias_ate_compra_mediana"] == 7.0
    assert tq["amostra_dias"] == 2


def test_repurchase_and_orders_per_client():
    leads = [{"id": "a"}, {"id": "b"}]
    sales = {"a": {"count": 2, "value": 20.0}, "b": {"count": 1, "value": 10.0}}
    tq = build_report_summary(_report(_t(leads=2, clientes=2, pedidos=3)), leads, sales)["timing_quality"]
    assert tq["pedidos_por_cliente"] == 1.5
    assert tq["recompra_pct"] == 0.5


def test_tracking_quality_percentages():
    rows = [
        {"channel": "Google Ads", "campaign": "(não atribuído) · x", "leads": 3},
        {"channel": "Google Ads", "campaign": "Search Atacado", "leads": 7},
        {"channel": "Sem rastreio", "campaign": "(sem campanha)", "leads": 5},
        {"channel": "Orgânico", "campaign": "(não atribuído) · nao-conta", "leads": 5},
    ]
    subs = {"Google Ads": _t(leads=10), "Sem rastreio": _t(leads=5), "Orgânico": _t(leads=5)}
    tq = build_report_summary(_report(_t(leads=20), subs, rows), [], {})["timing_quality"]
    assert tq["nao_atribuido_pct"] == 0.3
    assert tq["sem_rastreio_pct"] == 0.25


def test_sales_by_lead_tracks_first_sold_at(monkeypatch):
    rows = [
        {"lead_id": "a", "value": 10, "sold_at": "2026-09-10T10:00:00+00:00"},
        {"lead_id": "a", "value": 5, "sold_at": "2026-09-02T10:00:00+00:00"},
        {"lead_id": "a", "value": 1, "sold_at": "2026-09-20T10:00:00+00:00"},
    ]
    monkeypatch.setattr(tr, "_fetch_all", lambda build, page=1000: rows)
    out = _sales_by_lead(None, ["a"], None, None, "lead")
    assert out["a"]["first_sold_at"] == "2026-09-02T10:00:00+00:00"
    assert out["a"]["last_sold_at"] == "2026-09-20T10:00:00+00:00"
    assert out["a"]["count"] == 3


def test_traffic_report_includes_summary(monkeypatch):
    leads = [{"id": "a", "created_at": "2026-09-01T12:00:00+00:00"}]
    monkeypatch.setattr(tr, "get_supabase", lambda: None)
    monkeypatch.setattr(tr, "_fetch_leads", lambda sb, mode, lo, hi: leads)
    monkeypatch.setattr(tr, "_conversed_ids", lambda sb, ids: {"a"})
    monkeypatch.setattr(tr, "_closer_ids", lambda sb, ids: set())
    monkeypatch.setattr(tr, "_sales_by_lead", lambda sb, ids, lo, hi, mode: {})
    monkeypatch.setattr(tr, "_spend_by_channel", lambda sb, lo, hi: {})
    monkeypatch.setattr(tr, "_meta_campaign_by_lead", lambda sb, ls: {})
    out = tr.traffic_report("30d", "lead")
    assert out["summary"]["funnel"]["leads"] == 1
    assert out["summary"]["funnel"]["taxa_conversa"] == 1.0

from datetime import date
from unittest.mock import patch
from app.campaigns import conversion_analytics as ca


def test_build_timeseries_fills_zero_days_and_groups_by_event():
    events = [
        {"event": "qualified", "created_at": "2026-07-02T13:00:00+00:00"},
        {"event": "purchase", "created_at": "2026-07-02T20:00:00+00:00"},
        {"event": "opportunity", "created_at": "2026-06-30T12:00:00+00:00"},
        {"event": "lead", "created_at": "2026-07-02T10:00:00+00:00"},  # 'lead' ignorado no gráfico
    ]
    series = ca.build_timeseries(events, days=3, today=date(2026, 7, 2))
    # 3 dias: 30/06, 01/07, 02/07 (America/Sao_Paulo)
    assert [d["date"] for d in series] == ["2026-06-30", "2026-07-01", "2026-07-02"]
    d0630 = next(d for d in series if d["date"] == "2026-06-30")
    d0702 = next(d for d in series if d["date"] == "2026-07-02")
    assert d0630 == {"date": "2026-06-30", "qualified": 0, "opportunity": 1, "purchase": 0}
    # 02/07: qualified 1, purchase 1 (13:00Z=10:00 BRT e 20:00Z=17:00 BRT caem em 02/07)
    assert d0702["qualified"] == 1 and d0702["purchase"] == 1 and d0702["opportunity"] == 0


def test_aggregate_value_by_traffic():
    rows = [
        {"value": 500, "leads": {"traffic_type": "paid"}},
        {"value": 300, "leads": {"traffic_type": "organic"}},
        {"value": 200, "leads": {"traffic_type": "paid"}},
        {"value": 100, "leads": None},              # sem lead → unknown
        {"value": None, "leads": {"traffic_type": "paid"}},  # sem valor → ignora
        {"value": 50, "leads": {"traffic_type": "weird"}},   # tipo não previsto → unknown
    ]
    out = ca.aggregate_value_by_traffic(rows)
    assert out == {"paid": 700.0, "organic": 300.0, "unknown": 150.0}


def test_aggregate_value_by_traffic_empty():
    assert ca.aggregate_value_by_traffic([]) == {"paid": 0.0, "organic": 0.0, "unknown": 0.0}

from datetime import date
from unittest.mock import MagicMock, patch
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


# ── Fonte: ad_conversions ────────────────────────────────────────────────────────────

def test_dedupe_conversions_conta_meta_e_google_uma_vez():
    rows = [
        {"lead_id": "L1", "stage": "qualified", "sale_id": None, "platform": "meta"},
        {"lead_id": "L1", "stage": "qualified", "sale_id": None, "platform": "google"},
        {"lead_id": "L1", "stage": "purchase", "sale_id": "S1", "platform": "meta"},
        {"lead_id": "L1", "stage": "purchase", "sale_id": "S1", "platform": "google"},
        {"lead_id": "L1", "stage": "purchase", "sale_id": "S2", "platform": "meta"},  # outra venda
        {"lead_id": "L2", "stage": "qualified", "sale_id": None, "platform": "google"},
    ]
    out = ca.dedupe_conversions(rows)
    assert [(r["lead_id"], r["stage"], r["sale_id"]) for r in out] == [
        ("L1", "qualified", None), ("L1", "purchase", "S1"), ("L1", "purchase", "S2"),
        ("L2", "qualified", None),
    ]


def test_to_timeseries_events_mapeia_stage_e_event_at():
    rows = [
        {"lead_id": "L1", "stage": "opportunity", "sale_id": None, "event_at": "2026-10-07T12:00:00+00:00"},
        {"lead_id": "L1", "stage": "opportunity", "sale_id": None, "event_at": "2026-10-07T12:00:00+00:00"},
    ]
    assert ca.to_timeseries_events(rows) == [
        {"event": "opportunity", "created_at": "2026-10-07T12:00:00+00:00"},
    ]


class _FakeQuery:
    def __init__(self, rows, log):
        self._rows = list(rows)
        self._count = None
        self._range = None
        self._log = log

    def select(self, cols, count=None):
        self._log.append(("select", cols))
        self._count = count
        return self

    def eq(self, k, v):
        self._rows = [r for r in self._rows if r.get(k) == v]
        return self

    def gte(self, k, v):
        self._rows = [r for r in self._rows if (r.get(k) or "") >= v]
        return self

    def order(self, k):
        self._rows.sort(key=lambda r: r[k])
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def execute(self):
        rows = self._rows
        if self._range:
            rows = rows[self._range[0]:self._range[1] + 1]
        return MagicMock(data=rows, count=len(self._rows) if self._count else None)


class _FakeSb:
    def __init__(self, rows):
        self.rows = rows
        self.tables: list[str] = []
        self.log: list = []

    def table(self, name):
        self.tables.append(name)
        return _FakeQuery(self.rows if name == "ad_conversions" else [], self.log)


def _row(i, lead, platform, stage, status="enviado", sale=None, value=None, tt="paid", event_at=None):
    from datetime import datetime, timedelta, timezone
    ev = event_at or (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return {"id": f"{i:04d}", "lead_id": lead, "platform": platform, "stage": stage,
            "status": status, "sale_id": sale, "value": value, "event_at": ev,
            "leads": {"traffic_type": tt}}


def test_conversion_dashboard_le_ad_conversions_enviadas_sem_dobrar():
    rows = [
        _row(1, "L1", "meta", "qualified"),
        _row(2, "L1", "google", "qualified"),
        _row(3, "L1", "meta", "purchase", sale="S1", value=500),
        _row(4, "L1", "google", "purchase", sale="S1", value=500),
        _row(5, "L2", "google", "purchase", sale="S2", value=200, tt="organic"),
        _row(6, "L3", "meta", "opportunity", status="pendente"),
        _row(7, "L3", "google", "opportunity", status="erro"),
        _row(8, "L4", "meta", "purchase", status="fora_da_janela", sale="S4", value=999),
    ]
    sb = _FakeSb(rows)
    with patch.object(ca, "get_supabase", return_value=sb), \
         patch.object(ca, "traffic_split", return_value={"paid": 1, "organic": 0, "unknown": 0}):
        out = ca.conversion_dashboard()

    assert "conversion_events" not in sb.tables
    assert out["kpis"] == {"meta_sent": 2, "google_sent": 3, "pending": 1, "purchase_value": 700.0}
    assert out["value_by_traffic"] == {"paid": 500.0, "organic": 200.0, "unknown": 0.0}
    totais = {k: sum(d[k] for d in out["timeseries"]) for k in ("qualified", "opportunity", "purchase")}
    # qualified e purchase de L1 contam 1x cada (não 2x); pendente/erro/fora da janela não contam.
    assert totais == {"qualified": 1, "opportunity": 0, "purchase": 2}
    assert len(out["timeseries"]) == 30
    assert out["traffic_split"] == {"paid": 1, "organic": 0, "unknown": 0}


def test_conversion_dashboard_pagina_alem_de_mil_linhas():
    rows = [_row(i, f"L{i}", "meta", "qualified") for i in range(1, 1201)]
    sb = _FakeSb(rows)
    with patch.object(ca, "get_supabase", return_value=sb), \
         patch.object(ca, "traffic_split", return_value={"paid": 0, "organic": 0, "unknown": 0}):
        out = ca.conversion_dashboard()
    assert sum(d["qualified"] for d in out["timeseries"]) == 1200


def test_conversion_dashboard_fail_soft():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("relation ad_conversions does not exist")
    with patch.object(ca, "get_supabase", return_value=sb), \
         patch.object(ca, "traffic_split", return_value={"paid": 0, "organic": 0, "unknown": 0}):
        out = ca.conversion_dashboard()
    assert out["kpis"] == {"meta_sent": 0, "google_sent": 0, "pending": 0, "purchase_value": 0.0}
    assert out["value_by_traffic"] == {"paid": 0.0, "organic": 0.0, "unknown": 0.0}
    assert all(d["qualified"] == 0 for d in out["timeseries"])


def test_analytics_usa_o_paginador_compartilhado():
    from app.db.paginacao import paginar
    assert ca.paginar is paginar
    assert not hasattr(ca, "_fetch_all")

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.conversions import router as router_mod
from app.conversions.router import summarize


def test_summarize_conta_por_etapa_plataforma_status():
    rows = [
        {"stage": "qualified", "platform": "meta", "status": "enviado"},
        {"stage": "qualified", "platform": "meta", "status": "enviado"},
        {"stage": "purchase", "platform": "google", "status": "erro"},
    ]
    assert summarize(rows) == [
        {"stage": "purchase", "platform": "google", "status": "erro", "n": 1},
        {"stage": "qualified", "platform": "meta", "status": "enviado", "n": 2},
    ]


def test_endpoint(monkeypatch):
    class Q:
        def __getattr__(self, n): return lambda *a, **k: self
        def execute(self): return MagicMock(data=[{"id": "R1", "stage": "lead", "platform": "meta", "status": "enviado",
                                                   "lead": {"name": "Ana"}}])
    sb = MagicMock(); sb.table.return_value = Q()
    monkeypatch.setattr(router_mod, "get_supabase", lambda: sb)
    from app.main import app
    r = TestClient(app).get("/api/conversions/ads?period=30d")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"][0]["lead"]["name"] == "Ana"
    assert body["counts"] == [{"stage": "lead", "platform": "meta", "status": "enviado", "n": 1}]
    assert body["truncated"] is False


def test_range_datas_em_sao_paulo_fim_exclusivo():
    ini, fim = router_mod._range("30d", "2026-10-01", "2026-10-07")
    assert ini.startswith("2026-10-01T00:00:00-03:00")
    assert fim.startswith("2026-10-08T00:00:00-03:00")

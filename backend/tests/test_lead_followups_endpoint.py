from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class _Resp:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, rows): self._rows = rows
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def order(self, *a, **k): return self
    def execute(self): return _Resp(self._rows)


class _SB:
    def __init__(self, rows): self._rows = rows
    def table(self, name): return _Query(self._rows)


def test_followups_endpoint_flattens_objetivo_and_selects_fields():
    rows = [
        {"sequence": 1, "job_type": None, "status": "sent",
         "fire_at": "2026-06-29T12:00:00+00:00", "sent_at": "2026-06-29T12:00:01+00:00",
         "cancel_reason": None, "metadata": {"objetivo": "reengajar", "objective_prompt": "x"}},
        {"sequence": 2, "job_type": None, "status": "cancelled",
         "fire_at": "2026-06-30T12:00:00+00:00", "sent_at": None,
         "cancel_reason": "reopen_context_refreshed", "metadata": {"objetivo": "reforco_valor"}},
        {"sequence": 3, "job_type": None, "status": "pending",
         "fire_at": "2026-07-02T12:00:00+00:00", "sent_at": None,
         "cancel_reason": None, "metadata": None},
    ]
    with patch("app.leads.router.get_supabase", return_value=_SB(rows)):
        r = client.get("/api/leads/lead-1/followups")
    assert r.status_code == 200
    data = r.json()["data"]
    assert [d["sequence"] for d in data] == [1, 2, 3]
    assert data[0]["objetivo"] == "reengajar"
    assert data[1]["objetivo"] == "reforco_valor"
    assert data[1]["cancel_reason"] == "reopen_context_refreshed"
    assert data[2]["objetivo"] is None
    # objective_prompt (heavy text) must NOT leak through
    assert "objective_prompt" not in data[0]
    assert "metadata" not in data[0]

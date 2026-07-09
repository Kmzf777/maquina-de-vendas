# backend/tests/test_recoalesce_timestamp_tie.py
from unittest.mock import MagicMock
import app.buffer.processor as proc


class _FakeMsgQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def gt(self, col, val): self._filters.append(("gt", col, val)); return self
    def or_(self, expr): self._filters.append(("or", expr)); return self
    def limit(self, _n): return self
    def execute(self):
        # Reproduz o desempate: "mais nova" = created_at > wm OU (created_at == wm E id > wm_id).
        res = MagicMock()
        res.data = self._rows
        return res


def test_timestamp_tie_is_resolved_by_id(monkeypatch):
    # msg irmã tem MESMO created_at do watermark, mas id maior → deve contar como mais nova.
    sibling = {"id": "id-002"}
    fake_q = _FakeMsgQuery([sibling])
    fake_sb = MagicMock()
    fake_sb.table.return_value = fake_q
    monkeypatch.setattr(proc, "get_supabase", lambda: fake_sb)

    watermark = {"created_at": "2026-07-01T00:00:00", "id": "id-001"}
    assert proc._has_newer_inbound("conv-1", watermark) is True


def test_no_newer_inbound_returns_false(monkeypatch):
    fake_q = _FakeMsgQuery([])  # nada mais novo
    fake_sb = MagicMock()
    fake_sb.table.return_value = fake_q
    monkeypatch.setattr(proc, "get_supabase", lambda: fake_sb)

    watermark = {"created_at": "2026-07-01T00:00:00", "id": "id-001"}
    assert proc._has_newer_inbound("conv-1", watermark) is False

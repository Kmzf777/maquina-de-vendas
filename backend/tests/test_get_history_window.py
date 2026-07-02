from unittest.mock import MagicMock
import app.conversations.service as svc


class _FakeQuery:
    """Captura a cadeia de chamadas do supabase-py e devolve dados controlados."""
    def __init__(self, rows):
        self._rows = rows
        self.desc_used = None
        self.limit_used = None

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def order(self, _col, desc=False):
        self.desc_used = desc
        return self
    def limit(self, n):
        self.limit_used = n
        return self
    def execute(self):
        # Simula o DB devolvendo, na ordem pedida, a fatia dos dados.
        rows = list(reversed(self._rows)) if self.desc_used else list(self._rows)
        result = MagicMock()
        result.data = rows[: self.limit_used] if self.limit_used else rows
        return result


def test_get_history_returns_most_recent_in_chronological_order(monkeypatch):
    # 70 mensagens, created_at crescente "msg-00".."msg-69"
    all_rows = [{"role": "user", "content": f"m{i}", "created_at": f"2026-07-01T00:{i:02d}:00"} for i in range(70)]
    fake_q = _FakeQuery(all_rows)
    fake_sb = MagicMock()
    fake_sb.table.return_value = fake_q
    monkeypatch.setattr(svc, "get_supabase", lambda: fake_sb)

    out = svc.get_history("conv-1", limit=60)

    # Deve trazer as 60 MAIS RECENTES (m10..m69), em ordem CRONOLÓGICA (m10 primeiro).
    assert len(out) == 60
    assert out[0]["content"] == "m10"
    assert out[-1]["content"] == "m69"

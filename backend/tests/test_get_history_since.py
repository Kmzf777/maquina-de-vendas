"""leads.service.get_history ganha o parâmetro `since` (delta — D4 da Camada de Memória)."""
from unittest.mock import patch


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store):
        self.store = store

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def gt(self, key, value):
        self.store["gt"] = (key, value)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return _Resp([{"role": "user", "content": "x"}])


class _FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Query(self.store)


def test_get_history_without_since_does_not_filter_created_at():
    from app.leads.service import get_history

    store = {}
    with patch("app.leads.service.get_supabase", return_value=_FakeSupabase(store)):
        rows = get_history("lead-1")

    assert rows == [{"role": "user", "content": "x"}]
    assert "gt" not in store  # sem since → sem filtro de delta


def test_get_history_with_since_filters_created_at_gt():
    from app.leads.service import get_history

    store = {}
    since = "2026-06-26T10:00:00+00:00"
    with patch("app.leads.service.get_supabase", return_value=_FakeSupabase(store)):
        get_history("lead-1", since=since)

    assert store["gt"] == ("created_at", since)

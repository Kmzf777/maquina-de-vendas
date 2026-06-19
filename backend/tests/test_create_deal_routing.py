"""Unit tests for create_deal pipeline/stage routing and the dedupe_open guard.

Uses a fake Supabase client so the resolution logic is exercised without a real DB
(the Valeria pipelines only exist in prod, not in the homolog DB the tests point to).
"""
from unittest.mock import patch
import pytest


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, fake):
        self.table = table
        self.fake = fake
        self.filters = {}
        self.op = "select"
        self.payload = None

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def is_(self, key, value):
        self.filters[("is", key)] = value
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return _Resp(self.fake.resolve(self))


class FakeSupabase:
    def __init__(self, resolver, inserted, updated=None):
        self._resolver = resolver
        self.inserted = inserted
        self.updated = updated if updated is not None else []

    def table(self, name):
        return _Query(name, self)

    def resolve(self, q):
        if q.op == "insert":
            self.inserted.append((q.table, q.payload))
            row = dict(q.payload)
            row["id"] = f"{q.table}-new"
            return [row]
        if q.op == "update":
            self.updated.append((q.table, q.payload, q.filters))
            row = {**q.payload, "id": q.filters.get("id")}
            return [row]
        return self._resolver(q.table, q.filters)


def test_create_deal_routes_by_explicit_pipeline_and_stage_label():
    """pipeline_name + stage_label resolvem para o pipeline_id e stage_id corretos."""
    from app.leads.service import create_deal

    def resolver(table, filters):
        if table == "pipelines":
            return [{"id": "pl-pl"}] if filters.get("name") == "Valeria - Private Label" else []
        if table == "pipeline_stages":
            if filters.get("pipeline_id") == "pl-pl" and filters.get("label") == "Entrada":
                return [{"id": "st-entrada"}]
            return []
        return []

    inserted = []
    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver, inserted)):
        create_deal(
            "lead-1", "Landing Page - terceirizacao",
            pipeline_name="Valeria - Private Label", stage_label="Entrada",
        )

    assert len(inserted) == 1
    _, payload = inserted[0]
    assert payload["pipeline_id"] == "pl-pl"
    assert payload["stage_id"] == "st-entrada"


def test_create_deal_falls_back_when_named_pipeline_missing():
    """Pipeline inexistente (ex.: homolog) → fallback p/ 1º pipeline e 1ª coluna não-protegida."""
    from app.leads.service import create_deal

    def resolver(table, filters):
        if table == "pipelines":
            # Busca por nome falha; fallback (sem 'name' nos filtros) retorna o pipeline padrão.
            return [] if "name" in filters else [{"id": "pl-default"}]
        if table == "pipeline_stages":
            if "label" in filters:
                return []  # stage_label não existe nesse pipeline
            if "is_protected" in filters:
                return [{"id": "st-fallback"}]
            return []
        return []

    inserted = []
    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver, inserted)):
        create_deal(
            "lead-1", "x",
            pipeline_name="Valeria - Atacado", stage_label="Entrada",
        )

    assert len(inserted) == 1
    _, payload = inserted[0]
    assert payload["pipeline_id"] == "pl-default"
    assert payload["stage_id"] == "st-fallback"


def test_create_deal_dedupe_open_reuses_existing_and_does_not_insert():
    """dedupe_open=True: lead com deal aberto → reaproveita e NÃO insere outro."""
    from app.leads.service import create_deal

    def resolver(table, filters):
        if table == "deals" and ("is", "closed_at") in filters:
            return [{"id": "deal-existing", "pipeline_id": "pl-x", "stage_id": "st-x"}]
        return []

    inserted = []
    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver, inserted)):
        result = create_deal("lead-1", "x", dedupe_open=True)

    assert result["id"] == "deal-existing"
    assert inserted == []  # nenhum card novo criado


def test_create_deal_dedupe_open_creates_when_no_open_deal():
    """dedupe_open=True sem deal aberto → cria normalmente."""
    from app.leads.service import create_deal

    def resolver(table, filters):
        if table == "deals":
            return []  # nenhum deal aberto
        if table == "pipelines":
            return [{"id": "pl-default"}] if "name" not in filters else []
        if table == "pipeline_stages":
            return [{"id": "st-novo"}]
        return []

    inserted = []
    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver, inserted)):
        create_deal("lead-1", "x", dedupe_open=True)

    assert len(inserted) == 1


# ---------------------------------------------------------------------------
# move_open_deal_for_handoff — move do card de LP para o funil de fechamento
# ---------------------------------------------------------------------------

def test_move_open_deal_for_handoff_moves_lp_card_to_seller_funnel():
    """Card aberto em 'Valeria - Atacado' → UPDATE para 'João - Atacado' / 'Novo'."""
    from app.leads.service import move_open_deal_for_handoff

    def resolver(table, filters):
        if table == "deals" and ("is", "closed_at") in filters:
            return [{"id": "deal-lp", "pipeline_id": "pl-valeria-atacado", "stage_id": "st-entrada"}]
        if table == "pipelines":
            if "id" in filters:  # nome do pipeline atual do card
                return [{"name": "Valeria - Atacado"}] if filters["id"] == "pl-valeria-atacado" else []
            if filters.get("name") == "João - Atacado":
                return [{"id": "pl-joao-atacado"}]
            return []
        if table == "pipeline_stages":
            if filters.get("pipeline_id") == "pl-joao-atacado" and filters.get("is_protected") is False:
                return [{"id": "st-joao-novo"}]
            return []
        return []

    inserted, updated = [], []
    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver, inserted, updated)):
        result = move_open_deal_for_handoff("lead-1", title="João - qualificado")

    assert result is not None
    assert len(updated) == 1
    table, payload, filters = updated[0]
    assert table == "deals"
    assert filters["id"] == "deal-lp"
    assert payload["pipeline_id"] == "pl-joao-atacado"
    assert payload["stage_id"] == "st-joao-novo"
    assert payload["title"] == "João - qualificado"
    assert inserted == []  # move = UPDATE, nunca INSERT


def test_move_open_deal_for_handoff_ignores_non_lp_card():
    """Card aberto fora dos funis de entrada de LP → None, sem UPDATE (não é de LP)."""
    from app.leads.service import move_open_deal_for_handoff

    def resolver(table, filters):
        if table == "deals" and ("is", "closed_at") in filters:
            return [{"id": "deal-other", "pipeline_id": "pl-joao-recuperacao"}]
        if table == "pipelines" and "id" in filters:
            return [{"name": "João - Recuperação"}]  # não está em LP_HANDOFF_PIPELINE_ROUTES
        return []

    inserted, updated = [], []
    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver, inserted, updated)):
        result = move_open_deal_for_handoff("lead-1")

    assert result is None
    assert updated == []


def test_move_open_deal_for_handoff_returns_none_without_open_deal():
    """Sem deal aberto → None (chamador segue para create_deal)."""
    from app.leads.service import move_open_deal_for_handoff

    def resolver(table, filters):
        return []  # nenhum deal aberto

    inserted, updated = [], []
    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver, inserted, updated)):
        result = move_open_deal_for_handoff("lead-1")

    assert result is None
    assert updated == []

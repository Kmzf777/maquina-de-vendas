"""Reflexo de sistema (sem LLM): 'Disparo feito' → 'Respondeu' quando o lead responde.

Causa-raiz da auditoria 2026-06-25: cards empilhados em 'Disparo feito' no funil
'Valeria - Importação Leads Frios' porque nada os movia quando o lead respondia.
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
    def __init__(self, resolver, updated):
        self._resolver = resolver
        self.updated = updated

    def table(self, name):
        return _Query(name, self)

    def resolve(self, q):
        if q.op == "update":
            self.updated.append((q.table, q.payload, q.filters))
            return [{**q.payload, "id": q.filters.get("id")}]
        return self._resolver(q.table, q.filters)


# Stage ids do funil frio (espelham o prod pós-migration).
DISPARO_ID = "stage-disparo"
RESPONDEU_ID = "stage-respondeu"
PIPELINE_ID = "pl-frio"


def _stage_resolver(table, filters):
    if table == "pipeline_stages":
        if filters.get("pipeline_id") == PIPELINE_ID and filters.get("key") == "disparo_feito":
            return [{"id": DISPARO_ID}]
        if filters.get("pipeline_id") == PIPELINE_ID and filters.get("key") == "respondeu":
            return [{"id": RESPONDEU_ID}]
    return []


def test_advance_moves_disparo_feito_to_respondeu():
    from app.leads.service import advance_deal_on_reply

    deal = {"id": "deal-1", "pipeline_id": PIPELINE_ID, "stage_id": DISPARO_ID}
    updated = []
    with patch("app.leads.service.get_open_deal", return_value=deal), \
         patch("app.leads.service.get_supabase", return_value=FakeSupabase(_stage_resolver, updated)):
        result = advance_deal_on_reply("lead-1")

    assert result is True
    assert len(updated) == 1
    table, payload, filters = updated[0]
    assert table == "deals"
    assert filters["id"] == "deal-1"
    assert payload["stage_id"] == RESPONDEU_ID


def test_advance_noop_when_already_respondeu():
    """Não regride status conquistado: card já em Respondeu/Qualificado/Encerrado não é tocado."""
    from app.leads.service import advance_deal_on_reply

    deal = {"id": "deal-2", "pipeline_id": PIPELINE_ID, "stage_id": RESPONDEU_ID}
    updated = []
    with patch("app.leads.service.get_open_deal", return_value=deal), \
         patch("app.leads.service.get_supabase", return_value=FakeSupabase(_stage_resolver, updated)):
        result = advance_deal_on_reply("lead-2")

    assert result is False
    assert updated == []


def test_advance_noop_outside_cold_funnel():
    """Pipeline sem stage 'disparo_feito' (ex.: funil do vendedor) → no-op."""
    from app.leads.service import advance_deal_on_reply

    deal = {"id": "deal-3", "pipeline_id": "pl-joao-atacado", "stage_id": "st-novo"}
    updated = []
    with patch("app.leads.service.get_open_deal", return_value=deal), \
         patch("app.leads.service.get_supabase", return_value=FakeSupabase(lambda t, f: [], updated)):
        result = advance_deal_on_reply("lead-3")

    assert result is False
    assert updated == []


def test_advance_noop_without_open_deal():
    from app.leads.service import advance_deal_on_reply

    updated = []
    with patch("app.leads.service.get_open_deal", return_value=None), \
         patch("app.leads.service.get_supabase", return_value=FakeSupabase(lambda t, f: [], updated)):
        result = advance_deal_on_reply("lead-4")

    assert result is False
    assert updated == []


def test_advance_fail_soft_on_error():
    """Erro de DB nunca levanta (não pode derrubar o processamento do inbound)."""
    from app.leads.service import advance_deal_on_reply

    def boom(lead_id):
        raise RuntimeError("db down")

    with patch("app.leads.service.get_open_deal", side_effect=boom):
        result = advance_deal_on_reply("lead-5")

    assert result is False

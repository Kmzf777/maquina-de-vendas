"""Autonomia de pipeline da IA: marcar_interesse → Qualificado; encerrado como destino de perda."""
from unittest.mock import patch
import pytest


@pytest.mark.asyncio
async def test_marcar_interesse_move_card_para_qualificado(monkeypatch):
    """marcar_interesse, além do flag de follow-up, qualifica o card (create-or-move) usando o
    segmento do lead."""
    from app.agent.tools import execute_tool, pop_interest_marked

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lid: {"id": lid, "stage": "atacado"})
    calls = []
    monkeypatch.setattr(
        "app.agent.tools.mark_deal_qualificado",
        lambda lead_id, segment=None: calls.append((lead_id, segment)) or True,
    )

    result = await execute_tool(
        "marcar_interesse",
        {"nivel": "quente", "motivo": "pediu preço e prazo"},
        lead_id="lead-1",
        phone="5511999999999",
        conversation_id="conv-1",
    )

    # Qualificou o card com o segmento do lead
    assert calls == [("lead-1", "atacado")]
    # E o flag de follow-up continua sendo setado (comportamento legado preservado)
    assert pop_interest_marked("conv-1") == {"nivel": "quente", "motivo": "pediu preço e prazo"}
    assert "quente" in result.lower()


@pytest.mark.asyncio
async def test_marcar_interesse_failsoft_quando_move_levanta(monkeypatch):
    """Falha ao qualificar o card não derruba a tool (o flag de interesse ainda vale)."""
    from app.agent.tools import execute_tool, pop_interest_marked

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lid: {"id": lid, "stage": "atacado"})
    monkeypatch.setattr("app.agent.tools.mark_deal_qualificado", boom)

    result = await execute_tool(
        "marcar_interesse",
        {"nivel": "morno"},
        lead_id="lead-2",
        phone="5511999999999",
        conversation_id="conv-2",
    )

    assert "morno" in result.lower()
    assert pop_interest_marked("conv-2") == {"nivel": "morno", "motivo": ""}


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, fake):
        self.table = table
        self.fake = fake
        self.filters = {}

    def select(self, *a, **k):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def in_(self, key, values):
        self.filters[("in", key)] = values
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return _Resp(self.fake.resolve(self))


class FakeSupabase:
    def __init__(self, resolver):
        self._resolver = resolver

    def table(self, name):
        return _Query(name, self)

    def resolve(self, q):
        return self._resolver(q.table, q.filters)


def test_perdido_stage_id_reconhece_encerrado():
    """Funil frio (só tem 'Encerrado', sem 'Perdido') → _perdido_stage_id resolve via key encerrado."""
    from app.leads.service import _perdido_stage_id

    def resolver(table, filters):
        if table == "pipeline_stages" and ("in", "key") in filters:
            keys = filters[("in", "key")]
            assert "encerrado" in keys  # a key nova foi incluída na busca
            return [{"id": "st-encerrado", "key": "encerrado"}]
        return []

    sb = FakeSupabase(resolver)
    assert _perdido_stage_id(sb, "pl-frio") == "st-encerrado"

"""D7 (cartao 1e6381fe), Tarefa 3: automacao, cliente consolidado e conversoes
ignoram venda cancelada e tiram o frete do valor."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)

# Ordem do banco por sold_at desc: a cancelada e a mais recente.
VENDAS = [
    {"id": "S2", "lead_id": "L1", "product": "Cafe B", "value": 300, "freight": 0,
     "status": "cancelada", "sold_at": (NOW - timedelta(days=2)).isoformat()},
    {"id": "S1", "lead_id": "L1", "product": "Cafe A", "value": 500, "freight": 50,
     "status": "registrada", "sold_at": (NOW - timedelta(days=10)).isoformat()},
]
SO_CANCELADA = [VENDAS[0]]


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.selected = ""
        self.n = None

    def select(self, cols="*", **k):
        self.selected = cols
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self.n = n
        return self

    def execute(self):
        rows = self.rows if self.n is None else self.rows[: self.n]
        return _Resp(list(rows), count=len(rows))


class FakeSB:
    def __init__(self, sales, tables=None):
        self.sales = sales
        self.tables = tables or {}
        self.queries: list[_Query] = []

    def table(self, name):
        q = _Query(self.sales if name == "sales" else self.tables.get(name, []))
        if name == "sales":
            self.queries.append(q)
        return q


# -- engine -------------------------------------------------------------------

def _engine(cond, operator, value, sales):
    from app.automation import engine
    sb = FakeSB(sales)
    node = {"config": {"condition_type": cond, "operator": operator, "value": value},
            "yes_node_id": "Y", "no_node_id": "N"}
    with patch.object(engine, "get_supabase", return_value=sb), \
            patch.object(engine, "_update") as upd, patch.object(engine, "_complete"):
        engine._execute_condition({"id": "E1", "lead_id": "L1"}, node, {"phone": "55"}, NOW)
    return upd.call_args.kwargs["current_node_id"], sb


@pytest.mark.parametrize("cond,operator,value,esperado", [
    ("sale_count", "eq", 1, "Y"),
    ("sale_count", "gte", 2, "N"),
    ("total_spend", "eq", 450, "Y"),
    ("last_sale_value", "eq", 450, "Y"),
    ("repurchase_days", "gte", 10, "Y"),
])
def test_engine_ignora_cancelada_e_frete(cond, operator, value, esperado):
    destino, sb = _engine(cond, operator, value, VENDAS)
    assert destino == esperado
    assert all("status" in q.selected and "freight" in q.selected for q in sb.queries)


# -- test_runner --------------------------------------------------------------

@pytest.mark.parametrize("cond,operator,value,esperado", [
    ("sale_count", "eq", 1, "yes"),
    ("total_spend", "eq", 450, "yes"),
    ("last_sale_value", "eq", 450, "yes"),
    ("repurchase_days", "gte", 10, "yes"),
])
def test_test_runner_ignora_cancelada_e_frete(cond, operator, value, esperado):
    from app.automation import test_runner
    sb = FakeSB(VENDAS)
    with patch.object(test_runner, "get_supabase", return_value=sb):
        r = test_runner._eval_condition(
            {"condition_type": cond, "operator": operator, "value": value},
            {"id": "L1"}, {"lead_id": "L1"}, NOW)
    assert r == esperado


# -- variables ----------------------------------------------------------------

def test_valor_ultima_venda_ignora_a_cancelada_mais_recente():
    from app.automation import variables
    sb = FakeSB(VENDAS)
    with patch.object(variables, "get_supabase", return_value=sb):
        out = variables.substitute_variables(
            "{{produto}} {{valor_ultima_venda}}", {"id": "L1"}, None)
    assert out == "Cafe A R$ 450,00"
    assert "freight" in sb.queries[0].selected and "status" in sb.queries[0].selected


def test_variaveis_vazias_se_so_ha_cancelada():
    from app.automation import variables
    with patch.object(variables, "get_supabase", return_value=FakeSB(SO_CANCELADA)):
        out = variables.substitute_variables("[{{valor_ultima_venda}}]", {"id": "L1"}, None)
    assert out == "[]"


# -- leads/service ------------------------------------------------------------

def test_so_venda_cancelada_nao_e_cliente_consolidado():
    from app.leads import service
    with patch.object(service, "get_supabase", return_value=FakeSB(SO_CANCELADA)), \
            patch.object(service, "_won_stage_ids", return_value=[]):
        assert service.lead_is_customer("L1") is False


def test_venda_valida_e_cliente_consolidado():
    from app.leads import service
    with patch.object(service, "get_supabase", return_value=FakeSB(VENDAS)), \
            patch.object(service, "_won_stage_ids", return_value=[]):
        assert service.lead_is_customer("L1") is True


def test_cliente_ativo_usa_ultima_valida_sem_frete():
    from app.leads import service
    with patch.object(service, "get_supabase", return_value=FakeSB(VENDAS)):
        txt = service.get_relationship_summary("L1")
    assert "CLIENTE ATIVO" in txt and "Cafe A" in txt and "R$ 450,00" in txt


def test_resumo_com_so_cancelada_nao_e_cliente_ativo_por_venda():
    from app.leads import service
    with patch.object(service, "get_supabase", return_value=FakeSB(SO_CANCELADA)), \
            patch.object(service, "lead_has_active_relationship", return_value=False):
        txt = service.get_relationship_summary("L1")
    assert "Última compra" not in txt


# -- conversions/sweep --------------------------------------------------------

def test_candidato_de_conversao_sai_sem_frete():
    from app.conversions.sweep import build_candidates
    click = NOW - timedelta(days=2)
    lead = {"id": "L1", "stage": "atacado", "ja_era_cliente": None, "metadata": {},
            "created_at": click.isoformat(), "ctwa_clid": "C1", "gclid": None,
            "gbraid": None, "wbraid": None}
    entradas = [{"occurred_at": click.isoformat(), "metadata": {"ctwa_clid": "C1"}}]
    sales = [{"id": "S1", "lead_id": "L1", "sold_at": (click + timedelta(days=1)).isoformat(),
              "value": 200, "freight": 20, "status": "registrada"}]
    rows = build_candidates(lead=lead, entradas=entradas, sales=sales, opportunity_at=None,
                            values={}, now=NOW)
    compras = [r for r in rows if r["stage"] == "purchase"]
    assert compras and all(r["value"] == 180.0 for r in compras)

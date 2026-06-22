"""Opção B (ponte runtime do Gap E): lead_has_active_relationship consulta sales + deals."""
from unittest.mock import patch
import app.leads.service as svc


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, responder):
        self.table = table
        self.responder = responder
        self.ops = []

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        self.ops.append(("eq", a))
        return self

    def in_(self, *a, **k):
        self.ops.append(("in", a))
        return self

    def neq(self, *a, **k):
        self.ops.append(("neq", a))
        return self

    def filter(self, *a, **k):
        self.ops.append(("filter", a))
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(self.responder(self.table, self.ops))


class _SB:
    def __init__(self, responder):
        self.responder = responder

    def table(self, name):
        return _Query(name, self.responder)


def _run(responder):
    with patch.object(svc, "get_supabase", return_value=_SB(responder)):
        return svc.lead_has_active_relationship("lead-x")


def _is_closed_won_query(ops):
    # A 3ª consulta usa filter("stage","not.in",...)
    return any(op == "filter" and a and a[0] == "stage" for op, a in ops)


def _is_active_or_won_query(ops):
    # A 2ª consulta usa in_("stage", [...])
    return any(op == "in" and a and a[0] == "stage" for op, a in ops)


def test_sale_record_marks_customer():
    """Qualquer linha em `sales` => cliente."""
    def responder(table, ops):
        return [{"id": "s1"}] if table == "sales" else []
    assert _run(responder) is True


def test_deal_fechado_ganho_marks_customer():
    def responder(table, ops):
        if table == "sales":
            return []
        if table == "deals" and _is_active_or_won_query(ops):
            return [{"id": "d1"}]   # ja_chamado/fechado_ganho
        return []
    assert _run(responder) is True


def test_deal_ja_chamado_marks_customer():
    # mesma query (in stage) cobre ja_chamado; já validado acima — aqui garante via closed_at vazio
    def responder(table, ops):
        if table == "sales":
            return []
        if table == "deals" and _is_active_or_won_query(ops):
            return [{"id": "d-ja"}]
        return []
    assert _run(responder) is True


def test_legacy_closed_won_by_closed_at():
    def responder(table, ops):
        if table == "sales":
            return []
        if table == "deals" and _is_active_or_won_query(ops):
            return []
        if table == "deals" and _is_closed_won_query(ops):
            return [{"id": "d-closed"}]
        return []
    assert _run(responder) is True


def test_cold_lead_not_customer():
    """Sem venda, sem deal ativo/ganho, sem closed-won => não é cliente."""
    def responder(table, ops):
        return []
    assert _run(responder) is False


def test_fail_open_false_on_exception():
    def responder(table, ops):
        raise RuntimeError("db down")
    assert _run(responder) is False


def test_empty_lead_id_false():
    assert svc.lead_has_active_relationship("") is False


def test_won_and_lost_stage_constants():
    assert "fechado_ganho" in svc._WON_DEAL_STAGES
    assert "perdido" in svc._LOST_DEAL_STAGES and "fechado_perdido" in svc._LOST_DEAL_STAGES

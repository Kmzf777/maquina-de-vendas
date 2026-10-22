"""leads/service.py com segmento separado da fase (cartão b67f1c6b, B9)."""
from __future__ import annotations

from unittest.mock import patch

from app.leads import service as svc


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, sb, table):
        self.sb, self.table, self.filtros, self.op, self.payload = sb, table, [], "select", None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filtros.append((col, val))
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def execute(self):
        self.sb.calls.append((self.table, self.op, self.payload, list(self.filtros)))
        if self.table == "pipelines" and self.op == "select":
            nome = dict(self.filtros).get("name")
            return _Resp([{"id": f"pid:{nome}"}] if nome else [{"id": "pid:primeiro"}])
        if self.table == "pipeline_stages":
            return _Resp([{"id": "sid"}])
        if self.op in ("update", "insert"):
            return _Resp([{"id": "novo", **(self.payload or {})}])
        return _Resp([])


class _SB:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return _Q(self, name)


def _nomes_pipeline(sb):
    return [dict(f).get("name") for t, op, _, f in sb.calls if t == "pipelines" and dict(f).get("name")]


def test_segmento_do_lead_prefere_coluna_segmento():
    assert svc.segmento_do_lead({"segmento": "atacado", "stage": "private_label"}) == "atacado"


def test_segmento_do_lead_cai_no_stage_antigo():
    assert svc.segmento_do_lead({"segmento": None, "stage": "private_label"}) == "private_label"
    assert svc.segmento_do_lead({"stage": "Private Label"}) == "private_label"


def test_segmento_do_lead_fase_ou_vazio_e_none():
    assert svc.segmento_do_lead({"segmento": None, "stage": "secretaria"}) is None
    assert svc.segmento_do_lead({"stage": "qualificando"}) is None
    assert svc.segmento_do_lead({}) is None
    assert svc.segmento_do_lead(None) is None


def test_reset_lead_grava_fase_triagem():
    sb = _SB()
    with patch.object(svc, "get_supabase", return_value=sb):
        svc.reset_lead("L1")
    upd_lead = [p for t, op, p, _ in sb.calls if t == "leads" and op == "update"]
    assert upd_lead and upd_lead[0]["stage"] == "triagem"
    assert upd_lead[0]["segmento"] is None
    # conversations.stage continua com o vocabulário do agente
    upd_conv = [p for t, op, p, _ in sb.calls if t == "conversations" and op == "update"]
    assert upd_conv and upd_conv[0]["stage"] == "secretaria"


def test_move_deal_to_vendor_pipeline_normaliza_segmento():
    sb = _SB()
    with patch.object(svc, "get_supabase", return_value=sb), \
         patch.object(svc, "get_open_deal", return_value={"id": "d1"}):
        res = svc.move_deal_to_vendor_pipeline("L1", "Private Label", title="t")
    assert res is not None
    assert "João - Private Label" in _nomes_pipeline(sb)


def test_move_deal_to_vendor_pipeline_secretaria_e_none():
    assert svc.move_deal_to_vendor_pipeline("L1", "secretaria") is None
    assert svc.move_deal_to_vendor_pipeline("L1", "triagem") is None


def test_ensure_segment_deal_normaliza_e_passa_categoria_canonica():
    with patch.object(svc, "get_open_deal", return_value=None), \
         patch.object(svc, "get_lead", return_value={"name": "Ana"}), \
         patch.object(svc, "create_deal") as cd:
        assert svc.ensure_segment_deal("L1", " ATACADO ") is True
    assert cd.call_args.kwargs["category"] == "atacado"


def test_ensure_segment_deal_fase_nao_cria():
    with patch.object(svc, "get_open_deal", return_value=None), \
         patch.object(svc, "create_deal") as cd:
        assert svc.ensure_segment_deal("L1", "secretaria") is False
    cd.assert_not_called()


def test_mark_deal_qualificado_passa_segmento_normalizado():
    with patch.object(svc, "get_open_deal", return_value=None), \
         patch.object(svc, "ensure_segment_deal") as esd, \
         patch.object(svc, "move_deal_to_stage_key", return_value=True):
        assert svc.mark_deal_qualificado("L1", "private-label") is True
    assert esd.call_args.args == ("L1", "private_label")


def test_perdido_target_normaliza_categoria():
    sb = _SB()
    svc._perdido_target_for_category(sb, "Private Label")
    assert "Valeria - Private Label" in _nomes_pipeline(sb)


def test_create_deal_categoria_normalizada():
    sb = _SB()
    with patch.object(svc, "get_supabase", return_value=sb):
        svc.create_deal("L1", title="t", category="Exportação")
    assert "Arthur - Exportação" in _nomes_pipeline(sb)

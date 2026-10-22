"""Contrato Onda 0 (b67f1c6b): segmento do lead separado da fase."""
from app.leads import segmento as s


def test_normaliza():
    assert s.normalizar_segmento("Private Label") == "private_label"
    assert s.normalizar_segmento("private-label") == "private_label"
    assert s.normalizar_segmento(" ATACADO ") == "atacado"
    assert s.normalizar_segmento("exportação") == "exportacao"
    for v in (None, "", "secretaria", "pending", "perdido", "novo", "xyz"):
        assert s.normalizar_segmento(v) is None


def test_fase():
    assert s.fase_valida("triagem") and s.fase_valida("qualificando")
    assert not s.fase_valida("atacado") and not s.fase_valida("secretaria") and not s.fase_valida(None)


def test_constantes():
    assert s.SEGMENTOS == ("atacado", "private_label", "consumo", "exportacao")
    assert s.FASES == ("pending", "novo", "triagem", "qualificando", "perdido")
    assert s.SEGMENTOS_B2B == ("atacado", "private_label")


def test_b2b_failsoft(monkeypatch):
    class Boom:
        def rpc(self, *a, **k): raise RuntimeError("x")
    monkeypatch.setattr(s, "get_supabase", lambda: Boom())
    assert s.lead_e_b2b("l1") is False


def test_b2b_rpc(monkeypatch):
    class R:
        def __init__(self, d): self.data = d
    class Q:
        def __init__(self, d): self.d = d
        def execute(self): return R(self.d)
    class SB:
        def rpc(self, nome, args):
            assert nome == "fn_lead_b2b" and args == {"p_lead": "l1"}
            return Q(True)
    monkeypatch.setattr(s, "get_supabase", lambda: SB())
    assert s.lead_e_b2b("l1") is True

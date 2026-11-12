"""Backfill do score barrado pela trava B2B (F3): critérios a partir do flow_state v2."""
from unittest.mock import MagicMock

from scripts import backfill_score_ramo_f3 as bf


def _v2(**kw):
    return {"flow": "valeria_botoes_v2", **kw}


def test_criterios_do_atacado_completo():
    ramo, crit = bf.criterios_do_estado(_v2(
        node="T_HANDOFF", ramo="atacado", interesse="classico",
        respostas={"QA1": "cafeteria", "QA2": "ate100"}))
    assert ramo == "atacado"
    assert crit == {"segment": "cafeteria", "monthly_volume_kg": 65,
                    "purchase_intent": "clear"}


def test_fazer_pedido_e_intencao_clara():
    _, crit = bf.criterios_do_estado(_v2(node="QA1", ramo="atacado", respostas={"VA": "pedido"}))
    assert crit == {"purchase_intent": "clear"}


def test_so_viu_a_vitrine_nao_tem_criterio():
    assert bf.criterios_do_estado(_v2(node="VA", ramo="atacado")) == ("atacado", {})


def test_v1_e_estado_estranho_nao_quebram():
    assert bf.criterios_do_estado({"flow": "valeria_botoes_v1", "node": "N3"}) == (None, {})
    assert bf.criterios_do_estado(None) == (None, {})
    _, crit = bf.criterios_do_estado(_v2(ramo="atacado", respostas={"QA1": ["x"], "ZZ": "a"}))
    assert crit == {}


def _rodar(monkeypatch, conversas, **kw):
    monkeypatch.setattr(bf, "_conversas", lambda desde: iter(conversas))
    salvar = MagicMock(return_value={"final_score": 6, "is_provisional": False})
    qualif = MagicMock(return_value=True)
    monkeypatch.setattr(bf, "save_score_evidence", salvar)
    monkeypatch.setattr(bf, "registrar_qualificado", qualif)
    return bf.run(**kw), salvar, qualif


_CONVS = [
    {"id": "c1", "lead_id": "l1", "flow_state": _v2(node="QA2", ramo="atacado",
                                                    respostas={"QA1": "loja"})},
    {"id": "c2", "lead_id": "l2", "flow_state": _v2(node="C1", ramo="consumo")},
    {"id": "c3", "lead_id": "l3", "flow_state": {"flow": "valeria_botoes_v1", "node": "N2"}},
]


def test_ensaio_nao_escreve(monkeypatch):
    res, salvar, qualif = _rodar(monkeypatch, _CONVS)
    assert res["com_criterio"] == 1 and res["sem_respostas_v1"] == 1
    salvar.assert_not_called()
    qualif.assert_not_called()


def test_aplicar_grava_como_backfill_sem_qualificado_por_padrao(monkeypatch):
    res, salvar, qualif = _rodar(monkeypatch, _CONVS, aplicar=True)
    assert res["gravados"] == 1
    assert salvar.call_args.kwargs["source"] == "backfill"
    assert salvar.call_args.kwargs["updates"] == {"segment": "emporio"}
    qualif.assert_not_called()


def test_registrar_qualificado_so_com_a_flag(monkeypatch):
    res, _, qualif = _rodar(monkeypatch, _CONVS, aplicar=True, registrar_qualif=True)
    assert res["qualificados"] == 1
    assert qualif.call_args.kwargs["segmento"] == "atacado"

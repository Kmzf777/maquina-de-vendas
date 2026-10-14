"""Mesclagem de leads duplicados por telefone canonico (spec 2026-10-13).

Caso real: Douglas com `4999170363`, `554999170363` e `5549999170363` — tres leads para a
mesma pessoa. O script agrupa pelo telefone canonico (55 + DDD + 9 + 8 digitos, a mesma
regra do backend e do `normalizePhoneBR` do front) e mescla no lead mais antigo.
"""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "leads" / "mesclar_duplicados_telefone.py"


def _script():
    spec = importlib.util.spec_from_file_location("mesclar_duplicados_telefone", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


def _lead(id_, phone, created_at, name=None):
    return {"id": id_, "phone": phone, "name": name, "created_at": created_at}


def test_canonico():
    m = _script()
    assert m.canonico("4999170363") == "5549999170363"
    assert m.canonico("554999170363") == "5549999170363"
    assert m.canonico("5549999170363") == "5549999170363"
    assert m.canonico("(31) 8301-6991") == "5531983016991"
    assert m.canonico("031983016991") == "5531983016991"
    assert m.canonico("554934415750") == "5549934415750"   # fixo: mesma regra do backend
    for lixo in ("bling-123", "US.1349120865", "", None, "123", "123456789012"):
        assert m.canonico(lixo) is None


def test_agrupar_escolhe_o_mais_antigo_e_ignora_unicos():
    m = _script()
    grupos = m.agrupar([
        _lead(B, "5549999170363", "2026-06-15T10:00:00+00:00"),
        _lead(A, "4999170363", "2026-05-08T10:00:00+00:00"),
        _lead(C, "5531983016991", "2026-01-01T10:00:00+00:00"),
    ])
    assert len(grupos) == 1
    g = grupos[0]
    assert g["canonico"] == "5549999170363"
    assert g["sobrevivente"]["id"] == A
    assert [d["id"] for d in g["duplicados"]] == [B]


def test_agrupar_empate_de_created_at_fica_o_menor_id():
    m = _script()
    mesma_hora = "2026-05-08T10:00:00+00:00"
    g = m.agrupar([_lead(B, "4999170363", mesma_hora), _lead(A, "5549999170363", mesma_hora)])[0]
    assert g["sobrevivente"]["id"] == A
    assert [d["id"] for d in g["duplicados"]] == [B]


def test_agrupar_ignora_bling_e_lixo():
    m = _script()
    assert m.agrupar([_lead(A, "bling-1", "2026-01-01"), _lead(B, "bling-1", "2026-01-02"),
                      _lead(C, None, "2026-01-03"), _lead(D, "", "2026-01-04")]) == []


def _grupo(nome_s, nome_d, canonico="5549999170363", extras=()):
    return {"canonico": canonico,
            "sobrevivente": _lead(A, "4999170363", "2026-05-08", nome_s),
            "duplicados": [_lead(B, canonico, "2026-06-15", nome_d), *extras]}


def test_classificar_mesmo_primeiro_nome_e_automatico():
    m = _script()
    assert m.classificar(_grupo("Douglas Silva", "DOUGLAS")) == ("automatico", "")
    assert m.classificar(_grupo("José", "jose maria")) == ("automatico", "")


def test_classificar_nome_vazio_e_automatico():
    m = _script()
    assert m.classificar(_grupo("Douglas", None)) == ("automatico", "")
    assert m.classificar(_grupo("  ", "Douglas")) == ("automatico", "")


def test_classificar_primeiro_nome_diferente_vai_para_revisar():
    m = _script()
    assert m.classificar(_grupo("Douglas", "Francine")) == ("revisar", "nomes diferentes")


def test_classificar_3_leads_vai_para_revisar():
    m = _script()
    g = _grupo("Douglas", "Douglas", extras=[_lead(C, "554999170363", "2026-09-04", "Douglas")])
    assert m.classificar(g) == ("revisar", "3 leads no grupo")


def test_classificar_fixo_com_9_injetado_vai_para_revisar():
    m = _script()
    assert m.classificar(_grupo("Loja", "Loja", canonico="5549934415750")) == \
        ("revisar", "telefone fixo (9 injetado)")

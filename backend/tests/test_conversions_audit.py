from unittest.mock import MagicMock

from app.conversions.audit import find_duplicates
from scripts.conversoes import checar_duplicatas as cd


def _r(i, lead="L1", platform="google", stage="qualified", event_id=None, sale_id=None, status="enviado"):
    return {"id": i, "lead_id": lead, "platform": platform, "stage": stage,
            "event_id": event_id or f"e{i}", "sale_id": sale_id, "status": status}


def test_sem_duplicata_listas_vazias():
    rows = [_r("1"), _r("2", lead="L2"), _r("3", platform="meta"), _r("4", stage="opportunity")]
    d = find_duplicates(rows)
    assert d == {"lead_stage": [], "sale": [], "event_id": []}


def test_mesmo_lead_etapa_plataforma_e_duplicata():
    d = find_duplicates([_r("1"), _r("2")])
    assert len(d["lead_stage"]) == 1
    g = d["lead_stage"][0]
    assert g["key"] == ("google", "qualified", "L1") and g["n"] == 2
    assert sorted(x["id"] for x in g["rows"]) == ["1", "2"]


def test_mesmo_event_id_e_duplicata():
    d = find_duplicates([_r("1", event_id="X"), _r("2", lead="L2", event_id="X")])
    assert [g["key"] for g in d["event_id"]] == [("google", "X")]
    assert d["lead_stage"] == []


def test_mesma_venda_duas_vezes_e_duplicata_mas_duas_vendas_do_lead_nao():
    d = find_duplicates([_r("1", stage="purchase", sale_id="S1"), _r("2", stage="purchase", sale_id="S1")])
    assert [g["key"] for g in d["sale"]] == [("google", "S1")]
    d2 = find_duplicates([_r("1", stage="purchase", sale_id="S1"), _r("2", stage="purchase", sale_id="S2")])
    assert d2 == {"lead_stage": [], "sale": [], "event_id": []}


def test_linhas_nunca_enviadas_nao_contam():
    for st in ("ignorado", "fora_da_janela"):
        assert find_duplicates([_r("1"), _r("2", status=st)])["lead_stage"] == []


def test_mesmo_lead_em_plataformas_diferentes_nao_e_duplicata():
    assert find_duplicates([_r("1", platform="meta"), _r("2", platform="google")])["lead_stage"] == []


def test_cli_sai_com_1_quando_ha_duplicata(monkeypatch, capsys):
    monkeypatch.setattr(cd, "_ler", lambda: [_r("1"), _r("2")])
    assert cd.main([]) == 1
    assert "duplicad" in capsys.readouterr().out.lower()


def test_cli_sai_com_0_sem_duplicata(monkeypatch, capsys):
    monkeypatch.setattr(cd, "_ler", lambda: [_r("1")])
    assert cd.main([]) == 0
    assert "0 duplicatas" in capsys.readouterr().out

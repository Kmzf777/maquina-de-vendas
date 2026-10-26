"""Helper da D7: receita = valor - frete, zero se cancelada (cartao 1e6381fe)."""
from app.utils.receita_venda import frete_da_venda, receita_da_venda, venda_cancelada


def test_cancelada_por_status():
    assert venda_cancelada({"status": " Cancelada "})
    assert not venda_cancelada({"status": "registrada"})
    assert not venda_cancelada({"status": None})
    assert not venda_cancelada({})


def test_receita_tira_o_frete():
    assert receita_da_venda({"value": 500, "freight": 50, "status": "registrada"}) == 450.0
    assert receita_da_venda({"value": "100.10", "freight": None}) == 100.1
    assert receita_da_venda({"value": 80}) == 80.0


def test_cancelada_nao_e_receita_nem_frete():
    venda = {"value": 300, "freight": 20, "status": "cancelada"}
    assert receita_da_venda(venda) == 0.0
    assert frete_da_venda(venda) == 0.0


def test_frete():
    assert frete_da_venda({"value": 500, "freight": 50}) == 50.0
    assert frete_da_venda({"value": 500}) == 0.0

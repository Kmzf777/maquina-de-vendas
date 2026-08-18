import asyncio
from decimal import Decimal

import pytest

import app.bling.orders as orders
from app.bling.errors import BlingValidationError


# ---------- parcelas ----------

def test_a_vista_gera_uma_parcela_na_data_da_venda():
    p = orders.build_installments(Decimal("500.00"), [0], 45, "2026-08-18")
    assert p == [{"dataVencimento": "2026-08-18", "valor": 500.0,
                  "formaPagamento": {"id": 45}}]


def test_30_60_divide_em_duas_e_soma_datas():
    p = orders.build_installments(Decimal("500.00"), [30, 60], 45, "2026-08-18")
    assert [x["dataVencimento"] for x in p] == ["2026-09-17", "2026-10-17"]
    assert [x["valor"] for x in p] == [250.0, 250.0]


def test_ultima_parcela_absorve_o_arredondamento():
    """100,00 em 3x = 33,33 + 33,33 + 33,34. A soma tem que fechar EXATO —
    se sobrar 1 centavo, o Bling recusa o pedido."""
    p = orders.build_installments(Decimal("100.00"), [30, 60, 90], 45, "2026-08-18")
    assert [x["valor"] for x in p] == [33.33, 33.33, 33.34]
    assert round(sum(x["valor"] for x in p), 2) == 100.00


def test_arredondamento_para_baixo_tambem_fecha():
    p = orders.build_installments(Decimal("10.00"), [0, 30, 60], 45, "2026-08-18")
    assert round(sum(x["valor"] for x in p), 2) == 10.00


def test_parcelas_exige_forma_de_pagamento():
    with pytest.raises(BlingValidationError):
        orders.build_installments(Decimal("100.00"), [0], None, "2026-08-18")


def test_parcelas_exige_pelo_menos_um_prazo():
    with pytest.raises(BlingValidationError):
        orders.build_installments(Decimal("100.00"), [], 45, "2026-08-18")


def test_parse_terms_aceita_string_do_bling():
    assert orders.parse_terms("30/60/90") == [30, 60, 90]
    assert orders.parse_terms("0") == [0]
    assert orders.parse_terms("") == [0]
    assert orders.parse_terms("a vista") == [0]


# ---------- total e itens ----------

def test_total_do_item_aplica_desconto_percentual():
    total = orders.item_total({"quantidade": 10, "valor_unitario": 26.70,
                               "desconto_percentual": 10})
    assert total == Decimal("240.30")


def test_total_do_pedido_soma_itens():
    itens = [
        {"quantidade": 10, "valor_unitario": 26.70, "desconto_percentual": 0},
        {"quantidade": 2, "valor_unitario": 50.00, "desconto_percentual": 0},
    ]
    assert orders.order_total(itens) == Decimal("367.00")


def test_resumo_de_produto_para_a_coluna_product():
    assert orders.product_summary([{"descricao": "Cafe Classico 250g"}]) == "Cafe Classico 250g"
    assert orders.product_summary([
        {"descricao": "Cafe Classico 250g"}, {"descricao": "Cafe Suave 500g"},
        {"descricao": "Drip Coffee"},
    ]) == "Cafe Classico 250g +2 itens"
    assert orders.product_summary([]) == "Pedido Bling"


# ---------- payload ----------

def test_payload_tem_os_campos_obrigatorios_do_bling(monkeypatch):
    monkeypatch.setattr(orders.config, "store_id", lambda: 203455519)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: 6)

    payload = orders.build_order_payload(
        contact_id=5845664414,
        sold_at="2026-08-18",
        itens=[{"bling_product_id": 123, "codigo": "CAN-250", "descricao": "Cafe 250g",
                "unidade": "UN", "quantidade": 10, "valor_unitario": 26.70,
                "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [30]},
        seller_id=7,
        notes="obs do cliente",
        internal_notes="CRM lead L1",
    )

    # obrigatorios segundo o OpenAPI: contato, data, dataSaida, dataPrevista, itens, parcelas
    assert payload["contato"] == {"id": 5845664414}
    assert payload["data"] == payload["dataSaida"] == payload["dataPrevista"] == "2026-08-18"
    assert payload["itens"][0]["produto"] == {"id": 123}
    assert payload["itens"][0]["descricao"] == "Cafe 250g"
    assert payload["itens"][0]["quantidade"] == 10
    assert payload["itens"][0]["valor"] == 26.70
    assert payload["parcelas"][0]["formaPagamento"] == {"id": 45}
    assert payload["vendedor"] == {"id": 7}
    assert payload["loja"] == {"id": 203455519}
    assert payload["situacao"]["id"] == 6
    assert payload["observacoes"] == "obs do cliente"
    assert payload["observacoesInternas"] == "CRM lead L1"


def test_payload_omite_loja_e_situacao_quando_nao_configurados(monkeypatch):
    monkeypatch.setattr(orders.config, "store_id", lambda: None)
    monkeypatch.setattr(orders.config, "order_situacao_id", lambda: None)

    payload = orders.build_order_payload(
        contact_id=1, sold_at="2026-08-18",
        itens=[{"bling_product_id": 1, "descricao": "X", "quantidade": 1,
                "valor_unitario": 10.0, "desconto_percentual": 0}],
        payment={"method_id": 45, "terms": [0]}, seller_id=None,
    )
    assert "loja" not in payload
    assert "situacao" not in payload
    assert "vendedor" not in payload


def test_payload_recusa_pedido_sem_itens():
    with pytest.raises(BlingValidationError):
        orders.build_order_payload(contact_id=1, sold_at="2026-08-18", itens=[],
                                   payment={"method_id": 45, "terms": [0]}, seller_id=None)

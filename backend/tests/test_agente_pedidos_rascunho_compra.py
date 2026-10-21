import asyncio
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.agente_pedidos import leitura, rascunhos
from app.bling.errors import BlingServerError
from tests.agente_pedidos_fakes import ESPELHO, FakeBling, FakeSupabase

AUTOR = {"discord_id": "123", "nome": "Ana"}


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_FABRICA_CONTATO_ID", "900")
    monkeypatch.delenv("BLING_SECUNDARIA_FABRICA_CONTATO_ID", raising=False)
    sb = FakeSupabase(ESPELHO)
    monkeypatch.setattr(leitura, "get_supabase", lambda: sb)
    monkeypatch.setattr(rascunhos, "hoje", lambda: "2026-10-21")


def corpo(**extra):
    base = {"conta": "default",
            "itens": [{"produto_id": 1, "quantidade": 100}, {"produto_id": 2, "quantidade": 20}],
            "autor": AUTOR}
    base.update(extra)
    return rascunhos.RascunhoCompraIn(**base)


def custos(tabela):
    chamadas = []

    async def custo(conta, produto_id):
        chamadas.append((conta, produto_id))
        return tabela.get(produto_id)
    custo.chamadas = chamadas
    return custo


def preparar(c, custo):
    return asyncio.run(rascunhos.preparar_compra(c, custo))


def test_fabrica_nao_configurada_422():
    with pytest.raises(HTTPException) as e:
        preparar(corpo(conta="secundaria", itens=[{"produto_id": 5, "quantidade": 1}]),
                 custos({5: Decimal("10")}))
    assert e.value.status_code == 422
    assert "BLING_SECUNDARIA_FABRICA_CONTATO_ID" in e.value.detail["mensagem"]


def test_custo_ao_vivo_e_total():
    custo = custos({1: Decimal("20.50"), 2: Decimal("30")})
    r = preparar(corpo(), custo)
    assert custo.chamadas == [("default", 1), ("default", 2)]
    p = r["payload"]
    assert p["fornecedor"] == {"id": 900}
    assert p["data"] == "2026-10-21" and p["dataPrevista"] == "2026-10-21"
    assert p["itens"][0] == {"produto": {"id": 1, "codigo": "GOU-M500"},
                             "descricao": "Gourmet Moído 500g", "unidade": "UN",
                             "quantidade": 100.0, "valor": 20.5}
    assert p["observacoesInternas"] == "Criado pelo agente de pedidos (Discord: Ana)"
    assert "situacao" not in p and "parcelas" not in p
    s = r["resumo"]
    assert s["parte"] == {"nome": "Fábrica Canastra", "documento": "11.444.777/0001-61"}
    assert [l["total"] for l in s["linhas"]] == [2050.0, 600.0]
    assert s["subtotal"] == s["total"] == 2650.0
    assert s["parcelas"] == [] and s["vendedor"] is None and s["forma_pagamento"] is None
    assert s["data_prevista"] == "2026-10-21"
    assert r["tipo"] == "compra"


def test_valor_digitado_prevalece_sem_consultar_o_bling():
    custo = custos({1: Decimal("20.50")})
    r = preparar(corpo(itens=[{"produto_id": 1, "quantidade": 10, "valor_unitario": 18}],
                       data_prevista="2026-10-30", observacoes="lote novo"), custo)
    assert custo.chamadas == []
    assert r["payload"]["itens"][0]["valor"] == 18.0
    assert r["payload"]["dataPrevista"] == "2026-10-30"
    assert r["payload"]["observacoes"] == "lote novo"
    assert r["resumo"]["linhas"][0]["preco_alterado"] is True
    assert r["resumo"]["total"] == 180.0


def test_sem_custo_e_sem_valor_422():
    with pytest.raises(HTTPException) as e:
        preparar(corpo(itens=[{"produto_id": 2, "quantidade": 1}]), custos({}))
    assert e.value.status_code == 422
    assert e.value.detail["mensagem"] == "sem preço de custo para Especial Grão 1kg: informe o valor"


def test_produto_inexistente_404():
    with pytest.raises(HTTPException) as e:
        preparar(corpo(itens=[{"produto_id": 999, "quantidade": 1}]), custos({}))
    assert e.value.status_code == 404


def test_falha_ao_ler_custo_vira_422():
    async def custo(_c, _p):
        raise BlingServerError("timeout")
    with pytest.raises(HTTPException) as e:
        preparar(corpo(itens=[{"produto_id": 1, "quantidade": 1}]), custo)
    assert e.value.status_code == 422
    assert "informe o valor" in e.value.detail["mensagem"]


def test_fabrica_fora_do_espelho_vira_fabrica(monkeypatch):
    monkeypatch.setenv("BLING_FABRICA_CONTATO_ID", "4242")
    r = preparar(corpo(itens=[{"produto_id": 1, "quantidade": 1, "valor_unitario": 5}]), custos({}))
    assert r["resumo"]["parte"] == {"nome": "Fábrica", "documento": None}


def test_custo_ao_vivo_padrao_le_fornecedor_e_depois_preco_custo(monkeypatch):
    bling = FakeBling({
        ("GET", "/produtos/1"): {"data": {"id": 1, "fornecedor": {"precoCusto": 21.3},
                                          "precoCusto": 5}},
        ("GET", "/produtos/2"): {"data": {"id": 2, "fornecedor": {"precoCusto": 0},
                                          "precoCusto": 7.5}},
        ("GET", "/produtos/3"): {"data": {"id": 3}},
    })
    monkeypatch.setattr(rascunhos, "novo_cliente_bling", lambda conta: bling)
    assert asyncio.run(rascunhos.custo_ao_vivo("default", 1)) == Decimal("21.3")
    assert asyncio.run(rascunhos.custo_ao_vivo("default", 2)) == Decimal("7.5")
    assert asyncio.run(rascunhos.custo_ao_vivo("default", 3)) is None

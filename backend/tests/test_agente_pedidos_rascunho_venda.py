import asyncio
import json

import pytest
from fastapi import HTTPException

from app.agente_pedidos import leitura, rascunhos
from tests.agente_pedidos_fakes import ESPELHO, FakeRedis, FakeSupabase

AUTOR = {"discord_id": "123", "nome": "Ana"}


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    sb = FakeSupabase(ESPELHO)
    monkeypatch.setattr(leitura, "get_supabase", lambda: sb)
    monkeypatch.setattr(rascunhos, "hoje", lambda: "2026-10-21")
    return sb


def corpo(**extra):
    base = {"conta": "default", "cliente_id": 10,
            "itens": [{"produto_id": 1, "quantidade": 10}, {"produto_id": 2, "quantidade": 5}],
            "forma_pagamento_id": 100, "prazos": [0], "vendedor_id": 50, "autor": AUTOR}
    base.update(extra)
    return rascunhos.RascunhoVendaIn(**base)


def test_preco_vem_do_espelho():
    r = rascunhos.preparar_venda(corpo())
    assert r["tipo"] == "venda" and r["conta"] == "default"
    linhas = r["resumo"]["linhas"]
    assert linhas[0] == {"descricao": "Gourmet Moído 500g", "codigo": "GOU-M500",
                         "quantidade": 10.0, "unidade": "UN", "valor_unitario": 45.0,
                         "desconto_percentual": 0.0, "total": 450.0, "preco_alterado": False}
    assert r["resumo"]["subtotal"] == 765.0
    assert r["resumo"]["total"] == 765.0
    assert r["resumo"]["avisos"] == []
    assert r["resumo"]["rotulo_conta"] == "Bling Boaventura"
    assert r["resumo"]["parte"] == {"nome": "Empório X Ltda", "documento": "11.222.333/0001-81"}
    assert r["resumo"]["vendedor"] == "João"
    assert r["resumo"]["forma_pagamento"] == "Boleto"
    assert r["payload"]["itens"][0]["valor"] == 45.0
    assert r["payload"]["data"] == "2026-10-21"


def test_preco_digitado_marca_alterado_e_avisa():
    r = rascunhos.preparar_venda(corpo(itens=[{"produto_id": 1, "quantidade": 2,
                                                "valor_unitario": 40}]))
    linha = r["resumo"]["linhas"][0]
    assert linha["preco_alterado"] is True and linha["valor_unitario"] == 40.0
    assert r["resumo"]["avisos"] == ["Preço de Gourmet Moído 500g alterado: R$ 40,00 (Bling: R$ 45,00)"]
    assert r["payload"]["itens"][0]["valor"] == 40.0


def test_preco_digitado_igual_nao_avisa():
    r = rascunhos.preparar_venda(corpo(itens=[{"produto_id": 1, "quantidade": 2,
                                                "valor_unitario": 45}]))
    assert r["resumo"]["linhas"][0]["preco_alterado"] is False
    assert r["resumo"]["avisos"] == []


def test_desconto_percentual_no_total_e_frete():
    r = rascunhos.preparar_venda(corpo(desconto={"valor": 15, "unidade": "PERCENTUAL"}, frete=25))
    s = r["resumo"]
    assert s["subtotal"] == 765.0
    assert s["desconto"] == {"valor": 15.0, "unidade": "PERCENTUAL"}
    assert s["desconto_valor"] == 114.75
    assert s["frete"] == 25.0
    assert s["total"] == 675.25  # 765 * 0,85 + 25
    assert r["payload"]["desconto"] == {"valor": 15.0, "unidade": "PERCENTUAL"}
    assert r["payload"]["transporte"] == {"frete": 25.0}


def test_desconto_no_item():
    r = rascunhos.preparar_venda(corpo(itens=[{"produto_id": 1, "quantidade": 10,
                                                "desconto_percentual": 10}]))
    assert r["resumo"]["linhas"][0]["total"] == 405.0
    assert r["resumo"]["linhas"][0]["desconto_percentual"] == 10.0
    assert r["payload"]["itens"][0]["desconto"] == 10.0


def test_parcelas_fecham_o_total():
    r = rascunhos.preparar_venda(corpo(prazos=[30, 60], frete=10.01))
    parcelas = r["resumo"]["parcelas"]
    assert [p["data"] for p in parcelas] == ["2026-11-20", "2026-12-20"]
    assert round(sum(p["valor"] for p in parcelas), 2) == r["resumo"]["total"] == 775.01


def test_produto_inativo_404():
    with pytest.raises(HTTPException) as e:
        rascunhos.preparar_venda(corpo(itens=[{"produto_id": 3, "quantidade": 1}]))
    assert e.value.status_code == 404
    assert e.value.detail["erro"] == "produto"


def test_produto_de_outra_conta_404():
    with pytest.raises(HTTPException) as e:
        rascunhos.preparar_venda(corpo(itens=[{"produto_id": 5, "quantidade": 1}]))
    assert e.value.status_code == 404


def test_cliente_de_outra_conta_404():
    with pytest.raises(HTTPException) as e:
        rascunhos.preparar_venda(corpo(cliente_id=20))
    assert e.value.status_code == 404
    assert e.value.detail["erro"] == "cliente"


def test_forma_e_vendedor_inexistentes_404():
    with pytest.raises(HTTPException) as e:
        rascunhos.preparar_venda(corpo(forma_pagamento_id=999))
    assert e.value.detail["erro"] == "forma_pagamento"
    with pytest.raises(HTTPException) as e:
        rascunhos.preparar_venda(corpo(vendedor_id=60))
    assert e.value.status_code == 404 and e.value.detail["erro"] == "vendedor"


def test_vendedor_opcional():
    r = rascunhos.preparar_venda(corpo(vendedor_id=None))
    assert "vendedor" not in r["payload"]
    assert r["resumo"]["vendedor"] is None


def test_conta_desconhecida_400():
    with pytest.raises(HTTPException) as e:
        rascunhos.preparar_venda(corpo(conta="outra"))
    assert e.value.status_code == 400


def test_desconto_maior_que_o_total_422():
    with pytest.raises(HTTPException) as e:
        rascunhos.preparar_venda(corpo(desconto={"valor": 5000, "unidade": "REAL"}))
    assert e.value.status_code == 422


def test_payload_sem_loja_nem_situacao_e_cita_o_autor(monkeypatch):
    monkeypatch.setenv("BLING_STORE_ID", "777")
    monkeypatch.setenv("BLING_ORDER_SITUACAO_ID", "9")
    r = rascunhos.preparar_venda(corpo(observacoes="entregar sexta",
                                        observacoes_internas="cliente pediu nota"))
    p = r["payload"]
    assert "loja" not in p and "situacao" not in p
    assert p["observacoesInternas"] == ("Criado pelo agente de pedidos (Discord: Ana)\n"
                                        "cliente pediu nota")
    assert p["observacoes"] == "entregar sexta"
    assert r["resumo"]["observacoes"] == "entregar sexta"
    assert r["autor"] == AUTOR
    assert p["contato"] == {"id": 10}


def test_data_informada():
    r = rascunhos.preparar_venda(corpo(data="2026-10-25"))
    assert r["payload"]["data"] == "2026-10-25"


def test_validacao_do_corpo():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        corpo(itens=[])
    with pytest.raises(ValidationError):
        corpo(itens=[{"produto_id": 1, "quantidade": 0}])
    with pytest.raises(ValidationError):
        corpo(data="25/10/2026")


def test_guardar_carregar_apagar(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(rascunhos, "get_redis", lambda: redis)
    r = rascunhos.preparar_venda(corpo())

    salvo = asyncio.run(rascunhos.guardar(r))
    assert len(salvo["id"]) == 12 and salvo["expira_em"]
    chave = f"agente_pedidos:rascunho:{salvo['id']}"
    assert redis.ttls[chave] == 30 * 60
    assert json.loads(redis.dados[chave])["payload"] == r["payload"]

    assert asyncio.run(rascunhos.carregar(salvo["id"]))["resumo"] == r["resumo"]
    assert rascunhos.resposta(salvo) == {"id": salvo["id"], "tipo": "venda", "conta": "default",
                                          "expira_em": salvo["expira_em"], "resumo": r["resumo"]}
    asyncio.run(rascunhos.apagar(salvo["id"]))
    assert asyncio.run(rascunhos.carregar(salvo["id"])) is None


def test_carregar_id_estranho_nao_consulta(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(rascunhos, "get_redis", lambda: redis)
    assert asyncio.run(rascunhos.carregar("../x")) is None

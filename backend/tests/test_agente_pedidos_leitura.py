import pytest

from app.agente_pedidos import leitura
from tests.agente_pedidos_fakes import ESPELHO, FakeSupabase


@pytest.fixture
def sb(monkeypatch):
    fake = FakeSupabase(ESPELHO)
    monkeypatch.setattr(leitura, "get_supabase", lambda: fake)
    return fake


def test_busca_por_nome_so_da_conta_pedida(sb):
    out = leitura.clientes("default", "empório x")
    assert [c["id"] for c in out] == [10]
    c = out[0]
    assert c == {"id": 10, "nome": "Empório X Ltda", "fantasia": "Empório X",
                 "documento": "11.222.333/0001-81", "telefone": "5534999998888",
                 "cidade": "Uberlândia", "uf": "MG"}
    assert [c["id"] for c in leitura.clientes("secundaria", "empório")] == [20]


def test_busca_ignora_inativo(sb):
    assert leitura.clientes("default", "velho") == []


def test_cnpj_formatado_busca_por_digitos(sb):
    out = leitura.clientes("default", "11.222.333/0001-90")
    assert out == []  # dígitos diferentes do cadastro: nada
    out = leitura.clientes("default", "11.222.333/0001-81")
    assert [c["id"] for c in out] == [10]
    assert any("doc_digits.ilike.%11222333000181%" in e for q in sb.queries for e in q.ors)


def test_busca_por_telefone(sb):
    out = leitura.clientes("default", "(34) 99999-8888")
    assert [c["id"] for c in out] == [10]


def test_termo_vazio_devolve_lista_vazia(sb):
    assert leitura.clientes("default", "") == []
    assert leitura.clientes("default", "   ") == []
    assert leitura.produtos("default", "") == []
    assert sb.queries == []


def test_termo_com_virgula_e_parentese_nao_quebra_o_filtro(sb):
    assert leitura.clientes("default", "Empório, (X)") == []


def test_produtos_ativos_da_conta(sb):
    out = leitura.produtos("default", "gourmet")
    assert out == [{"id": 1, "codigo": "GOU-M500", "nome": "Gourmet Moído 500g",
                    "preco": 45.0, "unidade": "UN", "saldo": 30}]
    assert [p["id"] for p in leitura.produtos("default", "GOU-M500")] == [1]
    assert [p["id"] for p in leitura.produtos("secundaria", "gourmet")] == [5]


def test_vendedores_ativos(sb):
    assert leitura.vendedores("default") == [{"id": 50, "nome": "João"}]


def test_formas_de_venda_e_de_compra(sb):
    venda = leitura.formas_pagamento("default", "venda")
    assert venda == [{"id": 100, "descricao": "Boleto"}, {"id": 101, "descricao": "Pix"}]
    compra = leitura.formas_pagamento("default", "compra")
    assert [f["id"] for f in compra] == [101, 102]


def test_lookup_por_id_respeita_a_conta(sb):
    assert leitura.cliente("default", 10)["nome"] == "Empório X Ltda"
    assert leitura.cliente("secundaria", 10) is None
    assert leitura.produto("default", 3)["situacao"] == "I"
    assert leitura.produto("secundaria", 1) is None
    assert leitura.vendedor("default", 50)["nome"] == "João"
    assert leitura.vendedor("default", 60) is None
    assert leitura.forma("default", 100)["descricao"] == "Boleto"
    assert leitura.forma("default", 999) is None

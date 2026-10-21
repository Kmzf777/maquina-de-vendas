import asyncio

import pytest
from fastapi import HTTPException

import app.bling.contacts as ct
from app.agente_pedidos import leitura, rascunhos
from tests.agente_pedidos_fakes import ESPELHO, FakeBling, FakeSupabase

AUTOR = {"discord_id": "123", "nome": "Ana"}
CNPJ_NOVO = "45.723.174/0001-10"


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    sb = FakeSupabase(ESPELHO)
    monkeypatch.setattr(leitura, "get_supabase", lambda: sb)
    return sb


def corpo(**extra):
    base = {"conta": "default", "nome": "Café do Ponto Ltda", "documento": CNPJ_NOVO,
            "email": "compras@ponto.com.br", "telefone": "(34) 3222-1111",
            "endereco": {"endereco": "Rua A", "numero": "10", "bairro": "Centro",
                         "cep": "38400-000", "municipio": "Uberlândia", "uf": "MG"},
            "autor": AUTOR}
    base.update(extra)
    return rascunhos.RascunhoContatoIn(**base)


def test_documento_invalido_422():
    with pytest.raises(HTTPException) as e:
        rascunhos.preparar_contato(corpo(documento="11.111.111/1111-11"))
    assert e.value.status_code == 422
    assert e.value.detail["erro"] == "documento"


def test_documento_ja_existe_409_com_o_contato():
    with pytest.raises(HTTPException) as e:
        rascunhos.preparar_contato(corpo(documento="11.222.333/0001-81"))
    assert e.value.status_code == 409
    assert e.value.detail["erro"] == "contato_existe"
    assert e.value.detail["contato"] == {"id": 10, "nome": "Empório X Ltda"}


def test_documento_de_outra_conta_nao_conflita():
    # 52998224725 existe só na default.
    r = rascunhos.preparar_contato(corpo(conta="secundaria", documento="529.982.247-25",
                                         endereco=None))
    assert r["conta"] == "secundaria"
    assert r["resumo"]["contato"]["tipo"] == "F"


def test_resumo_e_payload_do_contato():
    r = rascunhos.preparar_contato(corpo())
    assert r["tipo"] == "contato"
    s = r["resumo"]
    assert s["rotulo_conta"] == "Bling Boaventura"
    assert s["parte"] == {"nome": "Café do Ponto Ltda", "documento": "45.723.174/0001-10"}
    assert s["contato"] == {
        "nome": "Café do Ponto Ltda", "documento": "45.723.174/0001-10", "tipo": "J",
        "email": "compras@ponto.com.br", "telefone": "(34) 3222-1111", "celular": None,
        "endereco_texto": "Rua A, 10 - Centro - Uberlândia/MG - CEP 38400-000",
    }
    assert s["linhas"] == [] and s["total"] is None and s["avisos"] == []
    p = r["payload"]
    assert p["numeroDocumento"] == "45723174000110"
    assert p["tipo"] == "J" and p["nome"] == "Café do Ponto Ltda"
    assert p["endereco"] == {"geral": {"endereco": "Rua A", "numero": "10", "bairro": "Centro",
                                       "cep": "38400-000", "municipio": "Uberlândia",
                                       "uf": "MG"}}
    assert "celular" not in p


# --- criar_contato_sem_lead -------------------------------------------------

def _fake_lock(_key):
    class _Ctx:
        async def __aenter__(self):
            return True

        async def __aexit__(self, *_a):
            return False
    return _Ctx()


def test_criar_contato_sem_lead_cria_e_nao_vincula(monkeypatch):
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _fake_lock)
    vinculos = []
    monkeypatch.setattr(ct, "_link", lambda *a: vinculos.append(a))
    bling = FakeBling({("GET", "/contatos"): {"data": []},
                       ("POST", "/contatos"): {"data": {"id": 777}}})

    out = asyncio.run(ct.criar_contato_sem_lead(
        bling, {"nome": "Café do Ponto", "numeroDocumento": "45723174000110", "tipo": "J"},
        account="secundaria"))

    assert out == 777
    assert vinculos == []
    assert bling.posts("/contatos")[0][2]["numeroDocumento"] == "45723174000110"
    espelho = [e for e in sb.escritas if e[1] == "bling_contacts"]
    assert espelho and espelho[0][2]["account"] == "secundaria" and espelho[0][2]["id"] == 777
    assert not any(e[1] in ("lead_bling_contacts", "leads") for e in sb.escritas)


def test_criar_contato_sem_lead_reaproveita_o_existente_ao_vivo(monkeypatch):
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _fake_lock)
    bling = FakeBling({("GET", "/contatos"): {"data": [
        {"id": 31, "nome": "Já existia", "numeroDocumento": "45.723.174/0001-10"}]}})

    out = asyncio.run(ct.criar_contato_sem_lead(
        bling, {"nome": "Café do Ponto", "numeroDocumento": "45723174000110"},
        account="default"))

    assert out == 31
    assert bling.posts() == []


def test_create_contact_antigo_ainda_vincula(monkeypatch):
    sb = FakeSupabase()
    monkeypatch.setattr(ct, "get_supabase", lambda: sb)
    monkeypatch.setattr(ct, "_lock", _fake_lock)
    vinculos = []
    monkeypatch.setattr(ct, "_link", lambda *a: vinculos.append(a))
    monkeypatch.setattr(ct, "_preencher_lead_com_contato", lambda *a: {})
    monkeypatch.setattr(ct, "_preencher_endereco_do_lead", lambda *a: {})
    bling = FakeBling({("GET", "/contatos"): {"data": []},
                       ("POST", "/contatos"): {"data": {"id": 778}}})

    out = asyncio.run(ct.create_contact(bling, {"id": "L1", "name": "Lead Nome"},
                                        {"numeroDocumento": "45723174000110"}))

    assert out == 778
    assert vinculos == [("L1", 778, "default")]
    assert bling.posts("/contatos")[0][2]["nome"] == "Lead Nome"

"""Endereco do lead no CRM -> endereco do contato vinculado no Bling.

O que estes testes protegem: o vendedor salva o endereco na ficha e ele nao
chega ao Bling (a reclamacao do cartao b3788533) — ou chega apagando o resto do
cadastro, porque o PUT do Bling v3 substitui o contato inteiro.
"""
import asyncio

import pytest

import app.bling.contacts as ct
from app.bling.errors import BlingServerError, BlingValidationError
from tests.test_bling_contacts import FakeSupabase

LEAD = {"id": "L1", "cep": "38400-100", "logradouro": " Av. Rondon Pacheco ", "numero": "100",
        "complemento": "", "bairro": "Centro", "municipio": "Uberlândia", "uf": "mg"}


# ==========================================================================
# endereco_do_lead
# ==========================================================================
def test_endereco_do_lead_completo_normaliza():
    g = ct.endereco_do_lead(LEAD)
    assert g == {"endereco": "Av. Rondon Pacheco", "numero": "100", "complemento": "",
                 "bairro": "Centro", "cep": "38400100", "municipio": "Uberlândia", "uf": "MG"}


def test_endereco_do_lead_incompleto_devolve_none():
    for falta in ("cep", "logradouro", "numero", "municipio", "uf"):
        assert ct.endereco_do_lead({**LEAD, falta: ""}) is None
        assert ct.endereco_do_lead({**LEAD, falta: None}) is None
    assert ct.endereco_do_lead({**LEAD, "cep": "3840"}) is None


def test_endereco_do_lead_bairro_e_complemento_sao_opcionais():
    g = ct.endereco_do_lead({**LEAD, "bairro": None, "complemento": None})
    assert g["bairro"] == "" and g["complemento"] == ""


# ==========================================================================
# atualizar_endereco
# ==========================================================================
class Cliente:
    def __init__(self, contato, erro=None):
        self.contato, self.erro, self.puts = contato, erro, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, path, params=None):
        if self.erro:
            raise self.erro
        return {"data": dict(self.contato) if self.contato else {}}

    async def put(self, path, json=None):
        self.puts.append((path, json))
        return {}


def _contato(**extra):
    return {"id": 9, "nome": "X", "numeroDocumento": "1", "email": "a@b.c",
            "endereco": {"geral": {"endereco": "Velha", "numero": "1", "cep": "1",
                                   "complemento": "Sala 2"},
                         "cobranca": {"endereco": "Cob"}},
            **extra}


def test_atualizar_endereco_troca_so_o_endereco():
    c = Cliente(_contato())
    out = asyncio.run(ct.atualizar_endereco(c, 9, ct.endereco_do_lead(LEAD)))
    path, corpo = c.puts[0]
    assert path == "/contatos/9" and "id" not in corpo
    assert corpo["nome"] == "X" and corpo["email"] == "a@b.c"
    assert corpo["endereco"]["geral"]["endereco"] == "Av. Rondon Pacheco"
    assert corpo["endereco"]["geral"]["cep"] == "38400100"
    assert corpo["endereco"]["cobranca"] == {"endereco": "Cob"}
    assert out["id"] == 9


def test_atualizar_endereco_complemento_vazio_nao_apaga_o_do_bling():
    c = Cliente(_contato())
    asyncio.run(ct.atualizar_endereco(c, 9, ct.endereco_do_lead(LEAD)))
    _path, corpo = c.puts[0]
    assert corpo["endereco"]["geral"]["complemento"] == "Sala 2"


def test_atualizar_endereco_sem_mudanca_nao_faz_put():
    geral = ct.endereco_do_lead(LEAD)
    c = Cliente(_contato(endereco={"geral": {k: v for k, v in geral.items() if v}}))
    out = asyncio.run(ct.atualizar_endereco(c, 9, geral))
    assert c.puts == []
    assert out["id"] == 9


def test_atualizar_endereco_contato_inexistente_levanta_404():
    c = Cliente({})
    with pytest.raises(BlingValidationError) as exc:
        asyncio.run(ct.atualizar_endereco(c, 9, ct.endereco_do_lead(LEAD)))
    assert exc.value.status == 404
    assert c.puts == []


def test_atualizar_endereco_erro_do_bling_propaga():
    c = Cliente(_contato(), erro=BlingServerError("fora do ar"))
    with pytest.raises(BlingServerError):
        asyncio.run(ct.atualizar_endereco(c, 9, ct.endereco_do_lead(LEAD)))


# ==========================================================================
# sync_lead_address
# ==========================================================================
VINCULOS = [{"account": "default", "bling_contact_id": 9},
            {"account": "secundaria", "bling_contact_id": 77}]


def _supabase(monkeypatch, lead=LEAD, vinculos=VINCULOS):
    fake = FakeSupabase({
        "leads": lambda f: [lead] if lead and f.get("id") == lead["id"] else [],
        "lead_bling_contacts": lambda f: list(vinculos) if f.get("lead_id") == "L1" else [],
    })
    monkeypatch.setattr(ct, "get_supabase", lambda: fake)
    return fake


def _fabrica(clientes):
    criados = []

    def factory(account):
        criados.append(account)
        return clientes[account]
    factory.criados = criados
    return factory


def test_sync_lead_inexistente(monkeypatch):
    _supabase(monkeypatch, lead=None)
    fab = _fabrica({})
    assert asyncio.run(ct.sync_lead_address("L1", client_factory=fab)) == {
        "status": "lead_not_found"}
    assert fab.criados == []


def test_sync_endereco_incompleto_nao_chama_o_bling(monkeypatch):
    _supabase(monkeypatch, lead={**LEAD, "numero": ""})
    fab = _fabrica({})
    assert asyncio.run(ct.sync_lead_address("L1", client_factory=fab)) == {
        "status": "incomplete"}
    assert fab.criados == []


def test_sync_sem_vinculo(monkeypatch):
    _supabase(monkeypatch, vinculos=[])
    fab = _fabrica({})
    assert asyncio.run(ct.sync_lead_address("L1", client_factory=fab)) == {
        "status": "not_linked"}
    assert fab.criados == []


def test_sync_atualiza_as_duas_contas_e_o_espelho(monkeypatch):
    fake = _supabase(monkeypatch)
    c1, c2 = Cliente(_contato()), Cliente(_contato(id=77))
    fab = _fabrica({"default": c1, "secundaria": c2})
    out = asyncio.run(ct.sync_lead_address("L1", client_factory=fab))
    assert out == {"status": "updated", "contas": [
        {"account": "default", "contact_id": 9, "status": "updated"},
        {"account": "secundaria", "contact_id": 77, "status": "updated"},
    ]}
    assert c1.puts[0][0] == "/contatos/9" and c2.puts[0][0] == "/contatos/77"
    espelhos = [q.filters["upsert"] for q in fake.queries
                if q.name == "bling_contacts" and "upsert" in q.filters]
    assert [(e["account"], e["id"]) for e in espelhos] == [("default", 9), ("secundaria", 77)]


def test_sync_uma_conta_falhar_nao_impede_a_outra(monkeypatch):
    fake = _supabase(monkeypatch)
    c1 = Cliente(_contato(), erro=BlingServerError("Bling fora do ar"))
    c2 = Cliente(_contato(id=77))
    fab = _fabrica({"default": c1, "secundaria": c2})
    out = asyncio.run(ct.sync_lead_address("L1", client_factory=fab))
    assert out["status"] == "partial"
    assert out["contas"][0]["account"] == "default"
    assert out["contas"][0]["status"] == "error"
    assert "Bling fora do ar" in out["contas"][0]["message"]
    assert out["contas"][1] == {"account": "secundaria", "contact_id": 77, "status": "updated"}
    espelhos = [q.filters["upsert"] for q in fake.queries
                if q.name == "bling_contacts" and "upsert" in q.filters]
    assert [e["account"] for e in espelhos] == ["secundaria"]


def test_sync_todas_as_contas_falham(monkeypatch):
    _supabase(monkeypatch, vinculos=VINCULOS[:1])
    fab = _fabrica({"default": Cliente(_contato(), erro=BlingServerError("x"))})
    out = asyncio.run(ct.sync_lead_address("L1", client_factory=fab))
    assert out["status"] == "error"
    assert out["contas"][0]["status"] == "error"

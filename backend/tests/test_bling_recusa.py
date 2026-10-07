"""Motivo real da recusa do Bling (`error.fields`) e log sem dado do cliente.

O caso que motivou: 11 POST /contatos com 400 em 06/10 e o vendedor so viu
"Nao foi possivel salvar o contato. O contato nao pode ser salvo pois
ocorreram problemas com sua validacao." — a frase generica de `message` +
`description`. O motivo de verdade (CEP invalido, CPF invalido...) vinha em
`error.fields` e era jogado fora.
"""
import asyncio
import logging

import pytest

import app.bling.client as bc
from app.bling.errors import BlingValidationError, campos_da_recusa


def _payload(fields):
    return {"error": {
        "type": "VALIDATION_ERROR",
        "message": "Não foi possível salvar o contato",
        "description": "O contato não pode ser salvo pois ocorreram problemas com sua validação.",
        "fields": fields,
    }}


# ==========================================================================
# Parser
# ==========================================================================
def test_lista_de_fields_vira_campo_e_mensagem_com_rotulo_em_portugues():
    out = campos_da_recusa(_payload([
        {"code": 49, "msg": "O CEP informado é inválido", "element": "cep",
         "namespace": "CONTATO.ENDERECO.GERAL"},
        {"code": 3, "msg": "número inválido", "element": "numeroDocumento",
         "namespace": "CONTATO"},
    ]))
    assert out == [
        {"campo": "CEP", "mensagem": "O CEP informado é inválido"},
        {"campo": "CPF/CNPJ", "mensagem": "número inválido"},
    ]


@pytest.mark.parametrize("element,rotulo", [
    ("numeroDocumento", "CPF/CNPJ"), ("email", "E-mail"), ("cep", "CEP"),
    ("uf", "UF"), ("municipio", "Município"), ("endereco", "Endereço"),
    ("numero", "Número"), ("bairro", "Bairro"), ("telefone", "Telefone"),
    ("celular", "Celular"), ("nome", "Nome"), ("ie", "Inscrição estadual"),
    ("indicadorIe", "Indicador de IE"),
])
def test_rotulos_conhecidos(element, rotulo):
    out = campos_da_recusa(_payload([{"msg": "x", "element": element}]))
    assert out == [{"campo": rotulo, "mensagem": "x"}]


def test_element_desconhecido_fica_como_veio():
    out = campos_da_recusa(_payload([{"msg": "valor invalido", "element": "dataNascimento"}]))
    assert out == [{"campo": "dataNascimento", "mensagem": "valor invalido"}]


def test_element_com_caminho_usa_a_ultima_parte_para_o_rotulo():
    out = campos_da_recusa(_payload([{"msg": "x", "element": "endereco.geral.cep"}]))
    assert out == [{"campo": "CEP", "mensagem": "x"}]


def test_sem_element_devolve_campo_vazio_e_mantem_a_mensagem():
    out = campos_da_recusa(_payload([{"code": 1, "msg": "Contato duplicado"}]))
    assert out == [{"campo": "", "mensagem": "Contato duplicado"}]


def test_item_sem_msg_e_descartado():
    out = campos_da_recusa(_payload([{"element": "cep"}, {"msg": "  ", "element": "uf"},
                                     {"msg": "ok", "element": "nome"}]))
    assert out == [{"campo": "Nome", "mensagem": "ok"}]


def test_msg_com_html_e_entidades_e_limpa():
    out = campos_da_recusa(_payload([
        {"msg": "O <b>CEP</b> informado &eacute; inv&aacute;lido<br/>  confira",
         "element": "cep"},
    ]))
    assert out == [{"campo": "CEP", "mensagem": "O CEP informado é inválido confira"}]


@pytest.mark.parametrize("payload", [
    None, {}, {"error": None}, {"error": {}}, {"error": {"fields": None}},
    {"error": {"fields": []}}, {"error": {"fields": "texto solto"}},
    {"error": {"fields": [None, 3, "x"]}}, {"error": "string"},
])
def test_formatos_sem_fields_uteis_devolvem_lista_vazia(payload):
    assert campos_da_recusa(payload) == []


def test_fields_como_objeto_indexado_tambem_e_lido():
    out = campos_da_recusa(_payload({"0": {"msg": "inválido", "element": "uf"}}))
    assert out == [{"campo": "UF", "mensagem": "inválido"}]


def test_erro_expoe_fields_a_partir_do_payload():
    exc = BlingValidationError("x", payload=_payload([{"msg": "inválido", "element": "uf"}]))
    assert exc.fields == [{"campo": "UF", "mensagem": "inválido"}]
    assert BlingValidationError("sem payload").fields == []


# ==========================================================================
# Log da recusa no client — uma linha, sem dado do cliente
# ==========================================================================
class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _HTTP:
    def __init__(self, resp):
        self.resp = resp

    async def request(self, *_a, **_k):
        return self.resp

    async def aclose(self):
        pass


@pytest.fixture
def _client_sem_rede(monkeypatch):
    async def noop(*_a, **_k):
        return None

    async def token(_account):
        return "jwt"

    monkeypatch.setattr(bc.ratelimit, "acquire", noop)
    monkeypatch.setattr(bc.auth, "get_access_token", token)


def test_recusa_loga_uma_linha_warning_com_campos_e_sem_pii(_client_sem_rede, caplog):
    payload = _payload([
        {"code": 49, "msg": "O CEP informado é inválido", "element": "cep"},
        {"code": 3, "msg": "O CPF 123.456.789-09 é inválido", "element": "numeroDocumento"},
        {"code": 5, "msg": "O e-mail fulano@cliente.com.br é inválido", "element": "email"},
        {"code": 7, "msg": "Telefone (34) 99876-5432 inválido", "element": "telefone"},
    ])
    # Dados do cliente que viajam no corpo enviado — nunca podem aparecer no log.
    corpo = {"nome": "Maria da Silva Cafeteria", "numeroDocumento": "12345678909",
             "email": "fulano@cliente.com.br", "telefone": "(34) 99876-5432"}
    client = bc.BlingClient(http=_HTTP(_Resp(400, payload)))

    with caplog.at_level(logging.WARNING, logger="app.bling.client"):
        with pytest.raises(BlingValidationError):
            asyncio.run(client.post("/contatos", corpo))

    linhas = [r for r in caplog.records if r.name == "app.bling.client"]
    assert len(linhas) == 1
    assert linhas[0].levelno == logging.WARNING
    texto = linhas[0].getMessage()
    assert "POST /contatos" in texto
    assert "400" in texto
    assert "VALIDATION_ERROR" in texto
    assert "cep: O CEP informado é inválido" in texto
    assert "numeroDocumento:" in texto and "email:" in texto and "telefone:" in texto
    for pii in ("Maria", "123.456.789-09", "12345678909", "fulano@cliente.com.br",
                "99876-5432", "(34)"):
        assert pii not in texto, f"PII no log: {pii}"


def test_recusa_sem_fields_ainda_loga_a_linha(_client_sem_rede, caplog):
    client = bc.BlingClient(http=_HTTP(_Resp(422, {"error": {"type": "X", "message": "m"}})))
    with caplog.at_level(logging.WARNING, logger="app.bling.client"):
        with pytest.raises(BlingValidationError):
            asyncio.run(client.put("/pedidos/vendas/1", {}))
    linhas = [r.getMessage() for r in caplog.records if r.name == "app.bling.client"]
    assert len(linhas) == 1
    assert "PUT /pedidos/vendas/1" in linhas[0] and "422" in linhas[0]

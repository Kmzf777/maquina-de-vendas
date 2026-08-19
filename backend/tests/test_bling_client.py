import asyncio

import pytest

import app.bling.client as bc
from app.bling.errors import (
    BlingAuthError, BlingRateLimitError, BlingServerError, BlingValidationError,
)


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeResponseCorpoQuebrado:
    """Simula um 200/201 cujo corpo nao e JSON valido (proxy quebrado, HTML de
    erro disfarcado de sucesso). Tem `content` nao vazio, ao contrario de um
    204 de verdade."""

    def __init__(self, status_code=200, content=b"<html>erro</html>"):
        self.status_code = status_code
        self.content = content

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class FakeHTTP:
    """Devolve respostas de uma fila e grava as requisicoes feitas."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.requests = []

    async def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        return self.respostas.pop(0)

    async def aclose(self):
        pass


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    async def noop(*_a, **_k):
        return None
    monkeypatch.setattr(bc.asyncio, "sleep", noop)
    monkeypatch.setattr(bc.ratelimit, "acquire", noop)


@pytest.fixture
def token(monkeypatch):
    async def fake_token():
        return "jwt-aaa"

    async def fake_invalidate():
        return None

    monkeypatch.setattr(bc.auth, "get_access_token", fake_token)
    monkeypatch.setattr(bc.auth, "invalidate_cache", fake_invalidate)


def test_headers_carregam_bearer_e_enable_jwt(token):
    http = FakeHTTP([FakeResponse(200, {"data": {"id": 1}})])
    client = bc.BlingClient(http=http)

    out = asyncio.run(client.get("/produtos"))

    assert out == {"data": {"id": 1}}
    headers = http.requests[0]["headers"]
    assert headers["Authorization"] == "Bearer jwt-aaa"
    assert headers["enable-jwt"] == "1"
    assert http.requests[0]["url"].endswith("/Api/v3/produtos")


def test_401_renova_uma_vez_e_repete(token, monkeypatch):
    http = FakeHTTP([FakeResponse(401), FakeResponse(200, {"data": []})])
    invalidado = []

    async def fake_invalidate():
        invalidado.append(True)

    monkeypatch.setattr(bc.auth, "invalidate_cache", fake_invalidate)
    client = bc.BlingClient(http=http)

    assert asyncio.run(client.get("/produtos")) == {"data": []}
    assert len(invalidado) == 1
    assert len(http.requests) == 2


def test_401_duas_vezes_levanta_auth_error(token):
    http = FakeHTTP([FakeResponse(401), FakeResponse(401)])
    client = bc.BlingClient(http=http)
    with pytest.raises(BlingAuthError):
        asyncio.run(client.get("/produtos"))


def test_429_faz_backoff_e_desiste(token):
    http = FakeHTTP([FakeResponse(429), FakeResponse(429), FakeResponse(429)])
    client = bc.BlingClient(http=http)
    with pytest.raises(BlingRateLimitError):
        asyncio.run(client.get("/produtos"))
    assert len(http.requests) == 3


def test_5xx_repete_e_depois_levanta_server_error(token):
    http = FakeHTTP([FakeResponse(500), FakeResponse(502), FakeResponse(503)])
    client = bc.BlingClient(http=http)
    with pytest.raises(BlingServerError):
        asyncio.run(client.get("/produtos"))
    assert len(http.requests) == 3


def test_5xx_seguido_de_sucesso_devolve_o_sucesso(token):
    http = FakeHTTP([FakeResponse(500), FakeResponse(200, {"data": {"ok": True}})])
    client = bc.BlingClient(http=http)
    assert asyncio.run(client.get("/produtos")) == {"data": {"ok": True}}


def test_400_de_validacao_nao_repete_e_carrega_a_mensagem(token):
    corpo = {"error": {"type": "VALIDATION_ERROR",
                       "message": "Nao foi possivel executar a operacao",
                       "description": "itens[0].quantidade invalida"}}
    http = FakeHTTP([FakeResponse(400, corpo)])
    client = bc.BlingClient(http=http)

    with pytest.raises(BlingValidationError) as exc:
        asyncio.run(client.post("/pedidos/vendas", json={"x": 1}))

    assert len(http.requests) == 1, "erro de validacao nao pode ser retentado"
    assert exc.value.type == "VALIDATION_ERROR"
    assert "quantidade invalida" in exc.value.description


def test_rate_limiter_e_chamado_antes_de_cada_request(token, monkeypatch):
    chamadas = []

    async def fake_acquire():
        chamadas.append(True)

    monkeypatch.setattr(bc.ratelimit, "acquire", fake_acquire)
    http = FakeHTTP([FakeResponse(500), FakeResponse(200, {"data": []})])
    client = bc.BlingClient(http=http)

    asyncio.run(client.get("/produtos"))
    assert len(chamadas) == 2, "cada tentativa consome uma vaga do orcamento"


def test_paginate_percorre_ate_pagina_incompleta(token):
    http = FakeHTTP([
        FakeResponse(200, {"data": [{"id": 1}, {"id": 2}]}),
        FakeResponse(200, {"data": [{"id": 3}]}),
    ])
    client = bc.BlingClient(http=http)

    async def run():
        return [item async for item in client.paginate("/produtos", {"criterio": 5}, limite=2)]

    assert asyncio.run(run()) == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert http.requests[0]["params"]["pagina"] == 1
    assert http.requests[1]["params"]["pagina"] == 2


def test_paginate_leva_teto_de_paginas_e_levanta_server_error(token, monkeypatch):
    # Reduz o teto para nao ter que simular 1000 paginas: com _MAX_PAGES = 2 e
    # um endpoint que so devolve paginas CHEIAS (bug do lado do Bling, ou
    # limite ignorado), o paginate deve desistir e falhar alto em vez de
    # rodar para sempre / estourar o teto diario local.
    monkeypatch.setattr(bc, "_MAX_PAGES", 2)
    http = FakeHTTP([
        FakeResponse(200, {"data": [{"id": 1}, {"id": 2}]}),
        FakeResponse(200, {"data": [{"id": 3}, {"id": 4}]}),
    ])
    client = bc.BlingClient(http=http)

    async def run():
        return [item async for item in client.paginate("/produtos", limite=2)]

    with pytest.raises(BlingServerError):
        asyncio.run(run())
    assert len(http.requests) == 2, "nao deve tentar uma 3a pagina alem do teto"


def test_max_attempts_configuravel_nao_retenta(token):
    # O modal de venda (sincrono, vendedor olhando a tela) precisa de um teto
    # de tentativas bem menor que o default de 3 — 93s de retry e inaceitavel
    # ali.
    http = FakeHTTP([FakeResponse(500)])
    client = bc.BlingClient(http=http, max_attempts=1)

    with pytest.raises(BlingServerError):
        asyncio.run(client.get("/produtos"))
    assert len(http.requests) == 1, "max_attempts=1 nao pode retentar"


def test_200_com_corpo_quebrado_loga_erro_e_devolve_vazio(token, caplog):
    # Corpo nao vazio que falha o parse JSON (proxy quebrado, HTML de erro
    # disfarcado de 200) precisa ficar visivel em log — ao contrario do 204
    # de verdade, que e silencioso de proposito. No fluxo de criacao de
    # pedido, engolir isso em silencio pode significar que o pedido nasceu no
    # Bling e o id de retorno se perdeu.
    http = FakeHTTP([FakeResponseCorpoQuebrado()])
    client = bc.BlingClient(http=http)

    with caplog.at_level("ERROR", logger="app.bling.client"):
        out = asyncio.run(client.get("/produtos"))

    assert out == {}
    mensagens = [rec.getMessage() for rec in caplog.records]
    assert any("corpo" in m.lower() and "produtos" in m for m in mensagens)
    # Nunca logar o corpo da resposta em si.
    assert not any("<html>" in m for m in mensagens)

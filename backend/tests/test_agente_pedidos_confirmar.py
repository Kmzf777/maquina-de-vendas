import asyncio
import json

import pytest

import app.bling.contacts as ct
from app.agente_pedidos import confirmar, rascunhos
from app.bling import jobs
from app.bling.errors import BlingServerError, BlingValidationError
from tests.agente_pedidos_fakes import FakeBling, FakeRedis, FakeSupabase

ID = "abcdef123456"
VENDA = {
    "tipo": "venda", "conta": "default", "autor": {"discord_id": "123", "nome": "Ana"},
    "payload": {"contato": {"id": 10}, "data": "2026-10-21", "itens": [], "parcelas": [],
                "observacoesInternas": "Criado pelo agente de pedidos (Discord: Ana)"},
    "resumo": {"total": 100.0},
}
COMPRA = {
    "tipo": "compra", "conta": "secundaria", "autor": {"discord_id": "123", "nome": "Ana"},
    "payload": {"fornecedor": {"id": 900}, "data": "2026-10-21", "dataPrevista": "2026-10-21",
                "itens": [], "observacoes": "",
                "observacoesInternas": "Criado pelo agente de pedidos (Discord: Ana)"},
    "resumo": {"total": 100.0},
}
CONTATO = {
    "tipo": "contato", "conta": "default", "autor": {"discord_id": "123", "nome": "Ana"},
    "payload": {"nome": "Café do Ponto", "numeroDocumento": "45723174000110", "tipo": "J"},
    "resumo": {},
}


@pytest.fixture
def redis(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    fake = FakeRedis()
    monkeypatch.setattr(rascunhos, "get_redis", lambda: fake)
    return fake


@pytest.fixture
def bling(monkeypatch):
    fake = FakeBling()
    contas_usadas = []

    def fabrica(conta):
        contas_usadas.append(conta)
        return fake
    monkeypatch.setattr(confirmar, "novo_cliente", fabrica)
    fake.contas_usadas = contas_usadas
    return fake


@pytest.fixture
def fila(monkeypatch):
    enfileirados = []

    async def enqueue(kind, payload, *, sale_id=None, account="default"):
        enfileirados.append((kind, payload, account))
    monkeypatch.setattr(jobs, "enqueue", enqueue)
    return enfileirados


def guardar(redis, rascunho, id_=ID):
    redis.dados[rascunhos.CHAVE.format(id_)] = json.dumps({**rascunho, "id": id_,
                                                           "expira_em": "x"})


def rodar(coro):
    return asyncio.run(coro)


def venda_ok(bling, id_bling=555, numero=1234):
    bling.respostas[("GET", "/pedidos/vendas")] = {"data": []}
    bling.respostas[("POST", "/pedidos/vendas")] = {"data": {"id": id_bling}}
    bling.respostas[("GET", f"/pedidos/vendas/{id_bling}")] = {"data": {"id": id_bling,
                                                                        "numero": numero}}


def test_vencido_410(redis, bling):
    status, corpo = rodar(confirmar.confirmar(ID, "123"))
    assert status == 410 and corpo["erro"] == "vencido"
    assert bling.chamadas == []


def test_id_invalido_410(redis, bling):
    status, _ = rodar(confirmar.confirmar("../../x", "123"))
    assert status == 410


def test_venda_criada_201_com_link(redis, bling):
    guardar(redis, VENDA)
    venda_ok(bling)

    status, corpo = rodar(confirmar.confirmar(ID, "123"))

    assert status == 201
    assert corpo == {"status": "criado", "bling_id": 555, "numero": "1234",
                     "link": "https://www.bling.com.br/vendas.php#edit/555"}
    post = bling.posts("/pedidos/vendas")[0][2]
    assert post["numeroLoja"] == f"agp-{ID}"
    assert bling.chamadas[0] == ("GET", "/pedidos/vendas", {"numerosLojas[]": [f"agp-{ID}"]})
    assert rascunhos.CHAVE.format(ID) not in redis.dados, "rascunho apagado depois de criar"
    assert json.loads(redis.dados[confirmar.CHAVE_RESULTADO.format(ID)]) == corpo
    assert redis.ttls[confirmar.CHAVE_RESULTADO.format(ID)] == 24 * 3600
    assert confirmar.CHAVE_TRAVA.format(ID) not in redis.dados


def test_clique_duplo_devolve_o_mesmo_sem_segundo_post(redis, bling):
    guardar(redis, VENDA)
    venda_ok(bling)
    primeiro = rodar(confirmar.confirmar(ID, "123"))
    segundo = rodar(confirmar.confirmar(ID, "123"))
    assert primeiro == segundo
    assert len(bling.posts()) == 1


def test_clique_enquanto_outro_cria_fica_na_fila(redis, bling):
    guardar(redis, VENDA)
    redis.dados[confirmar.CHAVE_TRAVA.format(ID)] = "outro"
    assert rodar(confirmar.confirmar(ID, "123")) == (202, {"status": "na_fila"})
    assert bling.chamadas == []


def test_venda_ja_existente_com_numero_loja_reaproveitada(redis, bling):
    guardar(redis, VENDA)
    bling.respostas[("GET", "/pedidos/vendas")] = {"data": [{"id": 777, "numero": 99}]}
    status, corpo = rodar(confirmar.confirmar(ID, "123"))
    assert status == 201 and corpo["bling_id"] == 777 and corpo["numero"] == "99"
    assert bling.posts() == []


def test_numero_que_falha_no_get_fica_none(redis, bling):
    guardar(redis, VENDA)
    bling.respostas[("GET", "/pedidos/vendas")] = {"data": []}
    bling.respostas[("POST", "/pedidos/vendas")] = {"data": {"id": 555}}
    bling.respostas[("GET", "/pedidos/vendas/555")] = BlingServerError("caiu")
    status, corpo = rodar(confirmar.confirmar(ID, "123"))
    assert status == 201 and corpo["numero"] is None


def test_422_do_bling_mantem_o_rascunho_e_libera_a_trava(redis, bling):
    guardar(redis, VENDA)
    bling.respostas[("GET", "/pedidos/vendas")] = {"data": []}
    bling.respostas[("POST", "/pedidos/vendas")] = BlingValidationError(
        "Não foi possível salvar a venda", status=400,
        payload={"error": {"fields": [{"element": "parcelas", "msg": "Soma das parcelas difere"}]}})

    status, corpo = rodar(confirmar.confirmar(ID, "123"))

    assert status == 422
    assert corpo["erro"] == "bling"
    assert "Não foi possível salvar a venda" in corpo["mensagem"]
    assert "Soma das parcelas difere" in corpo["mensagem"]
    assert rascunhos.CHAVE.format(ID) in redis.dados
    assert confirmar.CHAVE_TRAVA.format(ID) not in redis.dados
    assert confirmar.CHAVE_RESULTADO.format(ID) not in redis.dados


def test_transitorio_enfileira_e_resultado_pendente(redis, bling, fila):
    guardar(redis, VENDA)
    bling.respostas[("GET", "/pedidos/vendas")] = BlingServerError("timeout")

    assert rodar(confirmar.confirmar(ID, "123")) == (202, {"status": "na_fila"})

    kind, payload, conta = fila[0]
    assert kind == "agente_venda" and conta == "default"
    assert payload["id"] == ID and payload["rascunho"]["payload"] == VENDA["payload"]
    assert rodar(confirmar.resultado(ID)) == {"status": "pendente"}
    # Novo clique enquanto a fila trabalha: na fila, sem tocar no Bling.
    n = len(bling.chamadas)
    assert rodar(confirmar.confirmar(ID, "123")) == (202, {"status": "na_fila"})
    assert len(bling.chamadas) == n


def test_job_grava_criado(redis, bling, fila):
    guardar(redis, VENDA)
    bling.respostas[("GET", "/pedidos/vendas")] = BlingServerError("timeout")
    rodar(confirmar.confirmar(ID, "123"))
    kind, payload, _ = fila[0]

    venda_ok(bling, id_bling=556, numero=1235)
    handler = jobs._HANDLERS[kind]
    rodar(handler(payload, {"id": "J1", "attempts": 0, "account": "default"}))

    assert rodar(confirmar.resultado(ID)) == {
        "status": "criado", "bling_id": 556, "numero": "1235",
        "link": "https://www.bling.com.br/vendas.php#edit/556"}
    assert rascunhos.CHAVE.format(ID) not in redis.dados
    assert rodar(confirmar.confirmar(ID, "123"))[0] == 201


def test_job_validacao_grava_falhou_e_confirmar_devolve_422(redis, bling, fila):
    payload = {"id": ID, "rascunho": VENDA}
    bling.respostas[("GET", "/pedidos/vendas")] = {"data": []}
    bling.respostas[("POST", "/pedidos/vendas")] = BlingValidationError("contato inválido")
    with pytest.raises(BlingValidationError):
        rodar(jobs._HANDLERS["agente_venda"](payload, {"id": "J1", "attempts": 0}))
    res = rodar(confirmar.resultado(ID))
    assert res["status"] == "falhou" and "contato inválido" in res["mensagem"]
    status, corpo = rodar(confirmar.confirmar(ID, "123"))
    assert status == 422 and "contato inválido" in corpo["mensagem"]


def test_job_transitorio_na_ultima_tentativa_grava_falhou(redis, bling):
    payload = {"id": ID, "rascunho": VENDA}
    bling.respostas[("GET", "/pedidos/vendas")] = BlingServerError("timeout")
    with pytest.raises(BlingServerError):
        rodar(jobs._HANDLERS["agente_venda"](payload, {"id": "J1", "attempts": 0}))
    assert rodar(confirmar.resultado(ID)) is None  # ainda vai retentar
    with pytest.raises(BlingServerError):
        rodar(jobs._HANDLERS["agente_venda"](payload, {"id": "J1",
                                                        "attempts": jobs.MAX_ATTEMPTS - 1}))
    assert rodar(confirmar.resultado(ID))["status"] == "falhou"


def test_compra_criada_com_marca_e_link(redis, bling):
    guardar(redis, COMPRA)
    bling.respostas[("POST", "/pedidos/compras")] = {"data": {"id": 88}}
    bling.respostas[("GET", "/pedidos/compras/88")] = {"data": {"id": 88, "numero": 12}}

    status, corpo = rodar(confirmar.confirmar(ID, "123"))

    assert status == 201
    assert corpo == {"status": "criado", "bling_id": 88, "numero": "12",
                     "link": "https://www.bling.com.br/compras.php#edit/88"}
    post = bling.posts("/pedidos/compras")[0][2]
    assert post["observacoesInternas"].endswith(f"[agp-{ID}]")
    assert bling.contas_usadas == ["secundaria"]


def test_job_de_compra_reaproveita_a_que_ja_existe(redis, bling):
    bling.respostas[("GET", "/pedidos/compras")] = {"data": [{"id": 70}, {"id": 71}]}
    bling.respostas[("GET", "/pedidos/compras/70")] = {"data": {"id": 70, "numero": 1,
                                                                "observacoesInternas": "outra"}}
    bling.respostas[("GET", "/pedidos/compras/71")] = {"data": {
        "id": 71, "numero": 2, "observacoesInternas": f"Criado ... [agp-{ID}]"}}
    rodar(jobs._HANDLERS["agente_compra"]({"id": ID, "rascunho": COMPRA},
                                          {"id": "J", "attempts": 1}))
    assert bling.posts() == []
    assert rodar(confirmar.resultado(ID))["bling_id"] == 71
    params = bling.chamadas[0][2]
    assert params == {"idFornecedor": 900, "dataInicial": "2026-10-21"}


def test_contato_criado_sem_lead(redis, bling, monkeypatch):
    guardar(redis, CONTATO)
    chamadas = []

    async def criar(client, dados, *, account, avisos=None):
        chamadas.append((dados, account))
        return 4321
    monkeypatch.setattr(ct, "criar_contato_sem_lead", criar)

    status, corpo = rodar(confirmar.confirmar(ID, "123"))

    assert status == 201
    assert corpo == {"status": "criado", "bling_id": 4321, "numero": None,
                     "link": "https://www.bling.com.br/contatos.php#edit/4321"}
    assert chamadas == [(CONTATO["payload"], "default")]


def test_resultado_e_cancelar(redis, bling):
    assert rodar(confirmar.resultado(ID)) is None
    guardar(redis, VENDA)
    assert rodar(confirmar.resultado(ID)) == {"status": "pendente"}
    assert rodar(confirmar.cancelar(ID)) is True
    assert rascunhos.CHAVE.format(ID) not in redis.dados
    assert rodar(confirmar.cancelar(ID)) is False

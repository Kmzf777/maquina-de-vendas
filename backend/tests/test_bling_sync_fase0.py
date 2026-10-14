"""Fase 0 da sincronia Bling (avaliacao 2026-10-13): backfill por conta e por
intervalo, retomavel por conta, alto quando para no meio, idempotente; e
reabertura dos eventos de webhook `failed`, por conta.

Nada aqui fala com o Bling nem com o Supabase de verdade: cliente e banco sao
dubles. As duas contas sao exercitadas porque o bug que motivou a fase (G6) era
justamente o backfill so existir para a `default`.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import date

import pytest

import app.bling.backfill as bf
import app.bling.webhook_processor as wp
from app.bling import alertas, trava
from app.bling.errors import BlingAuthError, BlingValidationError


@pytest.fixture(autouse=True)
def _contas(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")


# --------------------------------------------------------------------------
# Dubles
# --------------------------------------------------------------------------
class FakeClient:
    """Lista pedidos por janela (`dataInicial`) e devolve o detalhe por id."""

    def __init__(self, por_janela=None, detalhes=None, falha_listagem=None):
        self.por_janela = por_janela or {}
        self.detalhes = detalhes or {}
        self.falha_listagem = falha_listagem
        self.params = []
        self.gets = []

    async def paginate(self, path, params=None, limite=100):
        self.params.append(dict(params or {}))
        if self.falha_listagem:
            raise self.falha_listagem
        for p in self.por_janela.get((params or {}).get("dataInicial"), []):
            yield p

    async def get(self, path, params=None):
        self.gets.append(path)
        oid = int(path.rsplit("/", 1)[-1])
        return {"data": self.detalhes.get(oid, {"id": oid, "data": "2026-08-01"})}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@asynccontextmanager
async def _trava_livre(account, ttl_segundos=3600):
    class T:
        async def estender(self):
            return None
    yield T()


def _prepara(monkeypatch, client, *, cursor=None, importar=None):
    """Liga o backfill aos dubles. Devolve (progresso, alertas, importados)."""
    progresso, alertados, importados = [], [], []
    contas_cliente = []

    def novo(account):
        contas_cliente.append(account)
        return client

    async def importar_padrao(cli, account, order_id):
        importados.append((account, order_id))

    monkeypatch.setattr(bf, "_new_client", novo)
    monkeypatch.setattr(bf, "_importar", importar or importar_padrao)
    monkeypatch.setattr(bf, "_load_progress",
                        lambda account: cursor(account) if callable(cursor) else cursor)
    monkeypatch.setattr(bf, "_save_progress",
                        lambda account, c: progresso.append((account, c)))
    monkeypatch.setattr(bf, "trava_pedidos", _trava_livre)
    monkeypatch.setattr(bf, "alertar",
                        lambda tipo, account, titulo, msg, **k: alertados.append((tipo, account, msg)))
    return progresso, alertados, importados, contas_cliente


# --------------------------------------------------------------------------
# Backfill: conta + intervalo
# --------------------------------------------------------------------------
def test_backfill_por_intervalo_de_datas_na_conta_secundaria(monkeypatch):
    client = FakeClient(por_janela={"2026-07-23": [{"id": 10}, {"id": 11}]})
    progresso, alertados, importados, contas = _prepara(monkeypatch, client)

    out = asyncio.run(bf.run(account="secundaria", data_inicial=date(2026, 7, 23),
                             data_final=date(2026, 8, 31)))

    assert contas == ["secundaria"]
    janelas = [(p["dataInicial"], p["dataFinal"]) for p in client.params]
    assert janelas == [("2026-07-23", "2026-08-21"), ("2026-08-22", "2026-08-31")]
    assert importados == [("secundaria", 10), ("secundaria", 11)]
    assert progresso == [("secundaria", "2026-08-21"), ("secundaria", "2026-08-31")]
    assert out["status"] == "concluido"
    assert out["conta"] == "secundaria"
    assert out["pedidos"] == 2
    assert alertados == []


def test_intervalo_invertido_e_recusado(monkeypatch):
    _prepara(monkeypatch, FakeClient())
    with pytest.raises(ValueError):
        asyncio.run(bf.run(data_inicial=date(2026, 9, 1), data_final=date(2026, 8, 1)))


def test_conta_desconhecida_e_recusada_antes_de_qualquer_chamada(monkeypatch):
    client = FakeClient()
    _prepara(monkeypatch, client)
    with pytest.raises(Exception):
        asyncio.run(bf.run(account="terceira", data_inicial=date(2026, 8, 1)))
    assert client.params == []


def test_cursor_e_por_conta(monkeypatch):
    """O cursor da conta 1 (2026-07-22, o buraco G1) nao pode pular janelas da
    conta 2, que nunca teve backfill."""
    client = FakeClient()
    lidos = []

    def cursor(account):
        lidos.append(account)
        return "2026-07-22" if account == "default" else None

    _prepara(monkeypatch, client, cursor=cursor)
    asyncio.run(bf.run(account="secundaria", data_inicial=date(2026, 7, 1),
                       data_final=date(2026, 7, 30)))

    assert lidos == ["secundaria"]
    assert client.params[0]["dataInicial"] == "2026-07-01"


def test_retoma_a_conta_1_depois_do_cursor_parado(monkeypatch):
    """G1: cursor em 2026-07-22 => a primeira janela consultada comeca em 23/07."""
    client = FakeClient()
    _prepara(monkeypatch, client, cursor="2026-07-22")

    asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 23),
                       data_final=date(2026, 10, 13)))

    assert client.params[0]["dataInicial"] == "2026-07-23"


def test_reiniciar_ignora_o_cursor(monkeypatch):
    client = FakeClient()
    _prepara(monkeypatch, client, cursor="2026-12-31")

    out = asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 1),
                             data_final=date(2026, 7, 30), reiniciar=True))

    assert client.params[0]["dataInicial"] == "2026-07-01"
    assert out["janelas"] == 1


def test_rodar_de_novo_depois_de_concluir_nao_refaz_nada(monkeypatch):
    """Idempotencia do lado do custo: o cursor no fim do intervalo zera o trabalho."""
    client = FakeClient()
    _prepara(monkeypatch, client, cursor="2026-08-31")

    out = asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 23),
                             data_final=date(2026, 8, 31)))

    assert client.params == []
    assert out["janelas"] == 0
    assert out["status"] == "concluido"


def test_pedido_que_falha_nao_derruba_a_janela_mas_segura_o_cursor_e_alerta(monkeypatch):
    """Antes: um pedido com erro abortava tudo e o cursor ficava parado em
    silencio (foi assim que a conta 1 ficou com 114 pedidos de fora). Agora os
    outros pedidos da janela entram, o cursor NAO avanca e o alerta sai."""
    client = FakeClient(por_janela={"2026-07-23": [{"id": 1}, {"id": 2}, {"id": 3}]})
    importados = []

    async def importar(cli, account, order_id):
        if order_id == 2:
            raise RuntimeError('null value in column "lead_id"')
        importados.append(order_id)

    progresso, alertados, _, _ = _prepara(monkeypatch, client, importar=importar)

    out = asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 23),
                             data_final=date(2026, 9, 30)))

    assert importados == [1, 3]
    assert progresso == [], "janela com falha nao pode avancar o cursor"
    assert len(client.params) == 1, "para na janela com falha, nao segue para a proxima"
    assert out["status"] == "interrompido"
    assert out["falhas"] == [{"pedido": 2, "erro": 'null value in column "lead_id"'}]
    assert alertados and alertados[0][0] == "bling_backfill_interrompido"
    assert alertados[0][1] == "default"


def test_erro_sistemico_para_na_hora_e_alerta(monkeypatch):
    """Token invalido / teto diario: nao adianta seguir pedido a pedido."""
    client = FakeClient(falha_listagem=BlingAuthError("401 apos renovar"))
    progresso, alertados, _, _ = _prepara(monkeypatch, client)

    out = asyncio.run(bf.run(account="secundaria", data_inicial=date(2026, 7, 1),
                             data_final=date(2026, 9, 30)))

    assert out["status"] == "interrompido"
    assert "401" in out["erro"]
    assert progresso == []
    assert alertados and alertados[0][1] == "secundaria"


def test_pedido_404_no_bling_e_falha_do_pedido_nao_do_job(monkeypatch):
    client = FakeClient(por_janela={"2026-07-01": [{"id": 1}, {"id": 2}]})
    feitos = []

    async def importar(cli, account, order_id):
        if order_id == 1:
            raise BlingValidationError("nao encontrado", status=404)
        feitos.append(order_id)

    _prepara(monkeypatch, client, importar=importar)
    out = asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 1),
                             data_final=date(2026, 7, 30)))
    assert feitos == [2]
    assert out["status"] == "interrompido"


def test_trava_ocupada_nao_chama_o_bling(monkeypatch):
    client = FakeClient()
    _prepara(monkeypatch, client)

    @asynccontextmanager
    async def ocupada(account, ttl_segundos=3600):
        raise trava.TravaOcupada("bling:pedidos:default ja esta em uso")
        yield  # pragma: no cover

    monkeypatch.setattr(bf, "trava_pedidos", ocupada)
    out = asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 1)))
    assert out["status"] == "ocupado"
    assert client.params == []


def test_estimar_so_lista_e_nao_grava(monkeypatch):
    client = FakeClient(por_janela={"2026-07-01": [{"id": 1}, {"id": 2}],
                                    "2026-07-31": [{"id": 3}]})
    progresso, _, importados, _ = _prepara(monkeypatch, client)

    out = asyncio.run(bf.run(account="secundaria", data_inicial=date(2026, 7, 1),
                             data_final=date(2026, 8, 29), estimar=True))

    assert importados == [] and progresso == []
    assert client.gets == []
    assert out["pedidos_no_bling"] == 3
    # listagem (1 por janela com < 100 pedidos) + 1 detalhe por pedido
    assert out["chamadas_estimadas"] == 2 + 3
    assert out["status"] == "estimado"


def test_importar_usa_o_detalhe_e_a_conta(monkeypatch):
    """`_importar` busca o detalhe (a listagem nao traz itens) e projeta na conta certa."""
    client = FakeClient(detalhes={7: {"id": 7, "data": "2026-08-02", "contato": {"id": 9}}})
    gravados = []

    async def fake_upsert(pedido, lead_id, event_date, account):
        gravados.append((pedido["id"], lead_id, account))

    async def fake_lead(cli, account, pedido):
        return "LEAD-9"

    monkeypatch.setattr(bf, "upsert_from_bling", fake_upsert)
    monkeypatch.setattr(bf, "_lead_do_pedido", fake_lead)
    asyncio.run(bf._importar(client, "secundaria", 7))

    assert client.gets == ["/pedidos/vendas/7"]
    assert gravados == [(7, "LEAD-9", "secundaria")]


# --------------------------------------------------------------------------
# Reabertura dos eventos `failed`
# --------------------------------------------------------------------------
class FakeEventos:
    def __init__(self, linhas):
        self.linhas = linhas
        self.filtros = []
        self.payloads = []

    def table(self, name):
        assert name == "bling_webhook_events"
        return self

    def update(self, payload):
        self.payloads.append(payload)
        return self

    def eq(self, col, val):
        self.filtros.append(("eq", col, val))
        return self

    def lt(self, col, val):
        self.filtros.append(("lt", col, val))
        return self

    def gte(self, col, val):
        self.filtros.append(("gte", col, val))
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.linhas
        return r


def test_reabrir_falhas_so_mexe_nos_failed_da_conta(monkeypatch):
    db = FakeEventos([{"event_id": "A"}, {"event_id": "B"}])
    monkeypatch.setattr(wp, "get_supabase", lambda: db)

    n = wp.reabrir_falhas("secundaria")

    assert n == 2
    assert ("eq", "account", "secundaria") in db.filtros
    assert ("eq", "status", "failed") in db.filtros
    assert db.payloads[0]["status"] == "pending"
    assert db.payloads[0]["attempts"] == 0


def test_reabrir_falhas_e_idempotente(monkeypatch):
    """Segunda chamada nao acha mais `failed` (ja viraram `pending`): zero."""
    db = FakeEventos([])
    monkeypatch.setattr(wp, "get_supabase", lambda: db)
    assert wp.reabrir_falhas("default") == 0


def test_reabrir_falhas_rejeita_conta_desconhecida(monkeypatch):
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeEventos([]))
    with pytest.raises(Exception):
        wp.reabrir_falhas("terceira")


# --------------------------------------------------------------------------
# Trava por conta e alerta
# --------------------------------------------------------------------------
class RedisTrava:
    """SET NX + os dois scripts de dono (soltar/estender), sem Lua de verdade:
    o fakeredis da suite nao tem `eval`."""

    def __init__(self):
        self.dados = {}

    async def set(self, chave, valor, nx=False, px=None):
        if nx and chave in self.dados:
            return None
        self.dados[chave] = valor
        return True

    async def eval(self, script, _n, chave, token, *args):
        if self.dados.get(chave) != token:
            return 0
        if "DEL" in script:
            del self.dados[chave]
        return 1


def test_trava_e_por_conta_e_tem_dono(monkeypatch):
    fake = RedisTrava()
    monkeypatch.setattr(trava, "_get_redis", lambda: fake)

    async def cenario():
        async with trava.trava_pedidos("default"):
            # mesma conta: ocupada
            with pytest.raises(trava.TravaOcupada):
                async with trava.trava_pedidos("default"):
                    pass
            # outra conta: livre
            async with trava.trava_pedidos("secundaria"):
                pass
        # soltou: pega de novo
        async with trava.trava_pedidos("default"):
            pass
        # quem nao e dono nao solta a trava alheia
        alheia = trava.Trava("default", 60)
        await alheia.pegar()
        intruso = trava.Trava("default", 60)
        await intruso.soltar()
        assert fake.dados.get(trava.chave("default")) == alheia.token

    asyncio.run(cenario())


def test_trava_fail_closed_sem_redis(monkeypatch):
    class Quebrado:
        async def set(self, *a, **k):
            raise ConnectionError("redis fora")

    monkeypatch.setattr(trava, "_get_redis", lambda: Quebrado())

    async def cenario():
        async with trava.trava_pedidos("default"):
            pass

    with pytest.raises(trava.TravaOcupada):
        asyncio.run(cenario())


def test_alerta_grava_com_a_conta_e_respeita_dedup(monkeypatch):
    gravados = []
    monkeypatch.setattr("app.alerts.service.create_system_alert",
                        lambda tipo, titulo, msg, severity="error", metadata=None:
                        gravados.append((tipo, severity, metadata)))
    estado = {"ja": False}
    monkeypatch.setattr(alertas, "_ja_alertado", lambda tipo, conta, horas: estado["ja"])

    assert alertas.alertar("bling_x", "secundaria", "t", "m") is True
    assert gravados == [("bling_x", "warning", {"conta": "secundaria"})]

    estado["ja"] = True
    assert alertas.alertar("bling_x", "secundaria", "t", "m") is False
    assert len(gravados) == 1


def test_alerta_nunca_levanta(monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(alertas, "_ja_alertado", explode)
    monkeypatch.setattr("app.alerts.service.create_system_alert", explode)
    assert alertas.alertar("bling_x", "default", "t", "m") is False


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
def test_endpoint_backfill_repassa_conta_e_intervalo(monkeypatch):
    import app.bling.router as br
    chamadas = []

    async def fake_run(**kw):
        chamadas.append(kw)
        return {"status": "concluido"}

    monkeypatch.setattr(bf, "run", fake_run)
    asyncio.run(br.backfill_endpoint(account=" Secundaria ", data_inicial=date(2025, 10, 14),
                                     data_final=None, reiniciar=False, estimar=True))
    assert chamadas[0]["account"] == "secundaria"
    assert chamadas[0]["data_inicial"] == date(2025, 10, 14)
    assert chamadas[0]["estimar"] is True


def test_endpoint_backfill_sem_parametros_mantem_o_padrao_da_tela(monkeypatch):
    import app.bling.router as br
    chamadas = []

    async def fake_run(**kw):
        chamadas.append(kw)
        return {}

    monkeypatch.setattr(bf, "run", fake_run)
    asyncio.run(br.backfill_endpoint())
    assert chamadas[0]["months"] == 12
    assert chamadas[0]["account"] == "default"


def test_endpoint_backfill_conta_desconhecida_e_400(monkeypatch):
    import app.bling.router as br
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        asyncio.run(br.backfill_endpoint(account="terceira"))
    assert exc.value.status_code == 400


def test_endpoint_backfill_intervalo_invertido_e_422(monkeypatch):
    import app.bling.router as br
    from fastapi import HTTPException

    async def fake_run(**kw):
        raise ValueError("intervalo invertido")

    monkeypatch.setattr(bf, "run", fake_run)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(br.backfill_endpoint(data_inicial=date(2026, 9, 1),
                                         data_final=date(2026, 8, 1)))
    assert exc.value.status_code == 422


def test_endpoint_reprocessar_por_conta(monkeypatch):
    import app.bling.router as br
    monkeypatch.setattr(wp, "reabrir_falhas", lambda conta: 3 if conta == "secundaria" else 0)
    out = asyncio.run(br.reprocessar_webhooks_endpoint(account="secundaria"))
    assert out == {"conta": "secundaria", "reabertos": 3}


# --------------------------------------------------------------------------
# Script de operacao (o que o runbook manda rodar)
# --------------------------------------------------------------------------
def test_script_backfill_repassa_argumentos_e_sai_1_se_interrompido(monkeypatch, capsys):
    from app.bling import ops
    chamadas = []

    async def fake_run(**kw):
        chamadas.append(kw)
        return {"status": "interrompido", "conta": kw["account"]}

    monkeypatch.setattr(bf, "run", fake_run)
    rc = ops.main(["backfill", "--conta", "default", "--desde", "2026-07-23"])
    assert rc == 1
    assert chamadas[0]["account"] == "default"
    assert chamadas[0]["data_inicial"] == date(2026, 7, 23)
    assert chamadas[0]["data_final"] is None
    assert '"interrompido"' in capsys.readouterr().out


def test_script_reprocessar_falhas(monkeypatch, capsys):
    from app.bling import ops
    monkeypatch.setattr(wp, "reabrir_falhas", lambda conta: 2)
    assert ops.main(["reprocessar-falhas", "--conta", "secundaria"]) == 0
    assert '"reabertos": 2' in capsys.readouterr().out

"""Fase 2 da sincronia Bling: varredura periodica de pedidos por conta (G3/G5).

A cada 1-3 h, por conta: lista `/pedidos/vendas` alterados desde o cursor
(`bling_sync_state(account, 'orders_sweep')`), importa cada um, e so avanca o
cursor se tudo deu certo. Cliente Bling e banco sao dubles.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

import app.bling.varredura as vr
from app.bling import trava
from app.bling.errors import BlingDailyCapError, BlingValidationError


@pytest.fixture(autouse=True)
def _contas(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_ENABLED", "true")
    monkeypatch.setenv("BLING_VARREDURA_ATIVA", "true")  # padrao e DESLIGADA


AGORA = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


class Cliente:
    def __init__(self, listados=None, erro_listagem=None):
        self.listados = listados or []
        self.erro_listagem = erro_listagem
        self.params = []

    async def paginate(self, path, params=None, limite=100):
        assert path == "/pedidos/vendas"
        self.params.append(dict(params or {}))
        if self.erro_listagem:
            raise self.erro_listagem
        for p in self.listados:
            yield p

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@asynccontextmanager
async def _livre(account, ttl_segundos=3600):
    yield None


def _prepara(monkeypatch, cliente, *, estado=None, importar=None):
    reg = {"contas_cliente": [], "salvos": [], "importados": [], "alertas": [],
           "reabertos": []}

    def novo(account):
        reg["contas_cliente"].append(account)
        return cliente

    async def importar_padrao(cli, account, order_id, event_date=None, **_k):
        reg["importados"].append((account, order_id, event_date))

    monkeypatch.setattr(vr, "_new_client", novo)
    monkeypatch.setattr(vr, "trava_pedidos", _livre)
    monkeypatch.setattr(vr, "_carregar_estado", lambda conta: estado)
    monkeypatch.setattr(vr, "_salvar_estado",
                        lambda conta, quando: reg["salvos"].append((conta, quando)))
    monkeypatch.setattr(vr, "alertar",
                        lambda tipo, conta, t, m, **k: reg["alertas"].append((tipo, conta)))
    monkeypatch.setattr(vr, "reabrir_falhas",
                        lambda conta, **k: reg["reabertos"].append((conta, k)) or 0)
    monkeypatch.setattr(vr.pedido_import, "importar_pedido", importar or importar_padrao)
    return reg


@pytest.mark.parametrize("conta", ["default", "secundaria"])
def test_varre_desde_o_cursor_importa_e_avanca(monkeypatch, conta):
    cli = Cliente(listados=[{"id": 1}, {"id": 2}])
    reg = _prepara(monkeypatch, cli,
                   estado={"last_sync_at": "2026-10-14T10:00:00+00:00"})

    out = asyncio.run(vr.varrer_conta(conta, agora=AGORA))

    assert reg["contas_cliente"] == [conta]
    # 10:00 UTC - 6 h de margem (to_bling_datetime), sem fuso: ver app/bling/dates.py
    assert cli.params == [{"dataAlteracaoInicial": "2026-10-14 04:00:00"}]
    assert [i[:2] for i in reg["importados"]] == [(conta, 1), (conta, 2)]
    assert reg["importados"][0][2] == AGORA.isoformat(), \
        "event_date = hora da leitura: webhook mais velho que isso e descartado"
    assert reg["salvos"] == [(conta, AGORA.isoformat())]
    assert out["status"] == "ok" and out["pedidos"] == 2


def test_primeira_rodada_sem_cursor_olha_3_dias(monkeypatch):
    cli = Cliente()
    _prepara(monkeypatch, cli, estado=None)
    asyncio.run(vr.varrer_conta("default", agora=AGORA))
    esperado = (AGORA - vr.JANELA_INICIAL - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
    assert cli.params[0]["dataAlteracaoInicial"] == esperado


def test_pedido_que_falha_segura_o_cursor_e_alerta(monkeypatch):
    cli = Cliente(listados=[{"id": 1}, {"id": 2}])
    feitos = []

    async def importar(cli_, conta, order_id, event_date=None, **_k):
        if order_id == 1:
            raise RuntimeError("pedido sem lead")
        feitos.append(order_id)

    reg = _prepara(monkeypatch, cli, estado={"last_sync_at": "2026-10-14T10:00:00+00:00"},
                   importar=importar)
    out = asyncio.run(vr.varrer_conta("secundaria", agora=AGORA))

    assert feitos == [2], "os outros pedidos entram mesmo assim"
    assert reg["salvos"] == [], "cursor so avanca com tudo certo"
    assert out["status"] == "parcial"
    assert out["falhas"][0]["pedido"] == 1
    assert reg["alertas"] == [("bling_varredura_falhou", "secundaria")]


def test_pedido_apagado_no_bling_nao_trava_o_cursor(monkeypatch):
    """404 no detalhe: o pedido sumiu entre a listagem e o GET. Nao e falha."""
    cli = Cliente(listados=[{"id": 1}])

    async def importar(cli_, conta, order_id, event_date=None, **_k):
        raise BlingValidationError("nao encontrado", status=404)

    reg = _prepara(monkeypatch, cli, estado=None, importar=importar)
    out = asyncio.run(vr.varrer_conta("default", agora=AGORA))
    assert out["status"] == "ok"
    assert reg["salvos"]


def test_teto_diario_para_sem_avancar(monkeypatch):
    cli = Cliente(erro_listagem=BlingDailyCapError("teto diario local"))
    reg = _prepara(monkeypatch, cli, estado=None)
    out = asyncio.run(vr.varrer_conta("default", agora=AGORA))
    assert out["status"] == "interrompido"
    assert reg["salvos"] == [] and reg["importados"] == []


def test_listagem_grande_demais_aborta_e_alerta(monkeypatch):
    """Guarda do filtro: se o Bling ignorar `dataAlteracaoInicial`, a listagem
    traz a base inteira. Melhor parar e avisar do que reimportar milhares."""
    monkeypatch.setattr(vr, "MAX_PEDIDOS_POR_RODADA", 3)
    cli = Cliente(listados=[{"id": i} for i in range(10)])
    reg = _prepara(monkeypatch, cli, estado=None)
    out = asyncio.run(vr.varrer_conta("default", agora=AGORA))
    assert out["status"] == "interrompido"
    assert reg["importados"] == [] and reg["salvos"] == []
    assert reg["alertas"] == [("bling_varredura_filtro", "default")]


def test_trava_ocupada_pula_a_rodada(monkeypatch):
    cli = Cliente(listados=[{"id": 1}])
    reg = _prepara(monkeypatch, cli, estado=None)

    @asynccontextmanager
    async def ocupada(account, ttl_segundos=3600):
        raise trava.TravaOcupada("ocupada")
        yield  # pragma: no cover

    monkeypatch.setattr(vr, "trava_pedidos", ocupada)
    out = asyncio.run(vr.varrer_conta("default", agora=AGORA))
    assert out["status"] == "ocupado"
    assert cli.params == [] and reg["salvos"] == []


def test_varredura_reabre_failed_antigos_da_conta(monkeypatch):
    cli = Cliente()
    reg = _prepara(monkeypatch, cli, estado=None)
    asyncio.run(vr.varrer_conta("secundaria", agora=AGORA))
    conta, filtros = reg["reabertos"][0]
    assert conta == "secundaria"
    assert filtros["parados_ha"] == timedelta(hours=6)
    assert filtros["recebidos_desde"] == timedelta(days=7)


# --------------------------------------------------------------------------
# Tick e agenda
# --------------------------------------------------------------------------
def test_tick_varre_as_duas_contas_e_isola_falha(monkeypatch):
    chamadas = []

    async def varrer(conta, agora=None):
        chamadas.append(conta)
        if conta == "default":
            raise RuntimeError("explodiu")
        return {"status": "ok"}

    async def reconciliar(conta, agora=None):
        return None

    import app.bling.reconciliacao as rc
    monkeypatch.setattr(vr, "varrer_conta", varrer)
    monkeypatch.setattr(rc, "reconciliar_se_devido", reconciliar)
    asyncio.run(vr.bling_pedidos_tick())
    assert chamadas == ["default", "secundaria"]


def test_tick_desligado_nao_faz_nada(monkeypatch):
    monkeypatch.setenv("BLING_ENABLED", "false")

    async def varrer(conta, agora=None):
        raise AssertionError("nao deveria varrer")

    monkeypatch.setattr(vr, "varrer_conta", varrer)
    asyncio.run(vr.bling_pedidos_tick())


@pytest.mark.parametrize("valor,esperado", [(None, 7200), ("1", 3600), ("3", 10800),
                                            ("0", 3600), ("12", 10800), ("x", 7200)])
def test_intervalo_configuravel_entre_1_e_3_horas(monkeypatch, valor, esperado):
    from app.bling import config
    if valor is None:
        monkeypatch.delenv("BLING_VARREDURA_HORAS", raising=False)
    else:
        monkeypatch.setenv("BLING_VARREDURA_HORAS", valor)
    assert config.varredura_intervalo_segundos() == esperado


def test_worker_registra_a_varredura_periodica():
    from app.worker.main import TASK_SPECS
    spec = next(s for s in TASK_SPECS if s[0] == "bling-pedidos")
    assert spec[1] == "periodic"
    assert 3600 <= spec[3] <= 10800


# --------------------------------------------------------------------------
# Rate limit: a varredura passa pelo BlingClient da conta (3 req/s por conta)
# --------------------------------------------------------------------------
def test_cada_chamada_da_varredura_consome_o_orcamento_da_propria_conta(monkeypatch):
    from app.bling import client as client_mod

    consumos = []

    async def acquire(account):
        consumos.append(account)

    async def token(account):
        return "tok"

    class Resp:
        def __init__(self, corpo):
            self.status_code = 200
            self._corpo = corpo
            self.content = b"x"

        def json(self):
            return self._corpo

    class Http:
        async def request(self, method, url, headers=None, params=None, json=None):
            if url.endswith("/pedidos/vendas"):
                return Resp({"data": [{"id": 5}]})
            return Resp({"data": {"id": 5, "data": "2026-10-14"}})

    monkeypatch.setattr(client_mod.ratelimit, "acquire", acquire)
    monkeypatch.setattr(client_mod.auth, "get_access_token", token)
    monkeypatch.setattr(vr, "_new_client",
                        lambda conta: client_mod.BlingClient(http=Http(), account=conta))
    monkeypatch.setattr(vr, "trava_pedidos", _livre)
    monkeypatch.setattr(vr, "_carregar_estado", lambda conta: None)
    monkeypatch.setattr(vr, "_salvar_estado", lambda conta, quando: None)
    monkeypatch.setattr(vr, "reabrir_falhas", lambda conta, **k: 0)

    async def lead(cli, conta, pedido):
        return "L"

    async def upsert(pedido, lead_id, event_date, account):
        return "S"

    monkeypatch.setattr(vr.pedido_import, "lead_do_pedido", lead)
    monkeypatch.setattr(vr.pedido_import, "upsert_from_bling", upsert)
    monkeypatch.setattr(vr.pedido_import, "_venda_ja_existia", lambda conta, order_id: True)

    asyncio.run(vr.varrer_conta("secundaria", agora=AGORA))
    # 1 listagem + 1 detalhe, as duas no orcamento da secundaria
    assert consumos == ["secundaria", "secundaria"]


def test_comando_varrer(monkeypatch, capsys):
    from app.bling import ops

    async def varrer(conta, agora=None):
        return {"conta": conta, "status": "parcial"}

    monkeypatch.setattr(vr, "varrer_conta", varrer)
    assert ops.main(["varrer", "--conta", "secundaria"]) == 1
    assert '"secundaria"' in capsys.readouterr().out


def test_chave_de_desligar_a_varredura(monkeypatch):
    monkeypatch.setenv("BLING_VARREDURA_ATIVA", "false")

    async def varrer(conta, agora=None):
        raise AssertionError("desligada")

    monkeypatch.setattr(vr, "varrer_conta", varrer)
    asyncio.run(vr.bling_pedidos_tick())


def test_varredura_desligada_por_padrao(monkeypatch):
    from app.bling import config
    monkeypatch.delenv("BLING_VARREDURA_ATIVA", raising=False)
    assert config.varredura_ativa() is False
    monkeypatch.setenv("BLING_VARREDURA_ATIVA", "true")
    assert config.varredura_ativa() is True

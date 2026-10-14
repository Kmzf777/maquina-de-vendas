"""Fase 3 da sincronia Bling: reconciliacao diaria por conta e por dia.

Para cada conta e cada dia dos ultimos ~35: compara quantidade, soma e ids do
Bling com `sales`; reimporta o que divergir; se continuar divergente, grava e
alerta. O resultado vai para `bling_reconciliacao` ("Bling conferido ate X").
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import pytest

import app.bling.reconciliacao as rc
from app.bling import trava
from app.bling.errors import BlingServerError, BlingValidationError


@pytest.fixture(autouse=True)
def _contas(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_ENABLED", "true")
    monkeypatch.setenv("BLING_VARREDURA_ATIVA", "true")  # padrao e DESLIGADA


HOJE = date(2026, 10, 14)


class Cliente:
    def __init__(self, pedidos, erro=None):
        self.pedidos = pedidos
        self.erro = erro
        self.params = []

    async def paginate(self, path, params=None, limite=100):
        assert path == "/pedidos/vendas"
        self.params.append(dict(params or {}))
        if self.erro:
            raise self.erro
        for p in self.pedidos:
            yield p

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@asynccontextmanager
async def _livre(account, ttl_segundos=3600):
    yield None


def _bling(id_, dia, total):
    return {"id": id_, "data": dia, "total": total, "situacao": {"id": 9}}


def _banco(id_, dia, valor):
    return {"bling_order_id": id_, "sold_at": f"{dia}T12:00:00+00:00", "value": valor}


def _prepara(monkeypatch, cliente, banco, *, reimportar=None, dias=3):
    """`banco` e uma lista mutavel: o reimportador falso pode corrigi-la."""
    reg = {"gravados": [], "alertas": [], "reimportados": [], "estado": [], "contas": []}

    def novo(conta):
        reg["contas"].append(conta)
        return cliente

    async def reimportar_padrao(cli, conta, order_id, event_date=None):
        reg["reimportados"].append((conta, order_id))

    monkeypatch.setattr(rc, "_new_client", novo)
    monkeypatch.setattr(rc, "trava_pedidos", _livre)
    monkeypatch.setattr(rc, "_vendas_do_banco", lambda conta, inicio, fim: list(banco))
    monkeypatch.setattr(rc, "_gravar", lambda linhas: reg["gravados"].extend(linhas))
    monkeypatch.setattr(rc, "_salvar_estado", lambda conta, quando: reg["estado"].append(conta))
    monkeypatch.setattr(rc, "alertar",
                        lambda tipo, conta, t, m, **k: reg["alertas"].append((tipo, conta, k)))
    monkeypatch.setattr(rc.pedido_import, "importar_pedido", reimportar or reimportar_padrao)
    monkeypatch.setattr(rc, "DIAS_PADRAO", dias)
    return reg


def _por_dia(reg):
    return {l["dia"]: l for l in reg["gravados"]}


@pytest.mark.parametrize("conta", ["default", "secundaria"])
def test_dias_iguais_ficam_ok_e_sao_gravados(monkeypatch, conta):
    cli = Cliente([_bling(1, "2026-10-12", 100.0), _bling(2, "2026-10-13", 50.5)])
    banco = [_banco(1, "2026-10-12", 100.0), _banco(2, "2026-10-13", 50.5)]
    reg = _prepara(monkeypatch, cli, banco)

    out = asyncio.run(rc.reconciliar_conta(conta, hoje=HOJE))

    assert reg["contas"] == [conta]
    assert cli.params == [{"dataInicial": "2026-10-11", "dataFinal": "2026-10-13"}]
    dias = _por_dia(reg)
    assert set(dias) == {"2026-10-11", "2026-10-12", "2026-10-13"}, \
        "dia sem pedido tambem e conferido (zero = zero)"
    assert all(l["status"] == "ok" and l["account"] == conta for l in dias.values())
    assert dias["2026-10-13"]["qtd_bling"] == 1 and dias["2026-10-13"]["soma_banco"] == 50.5
    assert reg["reimportados"] == [] and reg["alertas"] == []
    assert out["status"] == "ok" and out["conferido_ate"] == "2026-10-13"
    assert reg["estado"] == [conta]


def test_divergente_reimporta_e_fica_ok(monkeypatch):
    """Pedido faltando + valor diferente -> reimporta so esses -> confere de novo -> ok."""
    cli = Cliente([_bling(1, "2026-10-12", 100.0), _bling(2, "2026-10-12", 70.0),
                   _bling(3, "2026-10-13", 10.0)])
    banco = [_banco(1, "2026-10-12", 90.0), _banco(3, "2026-10-13", 10.0)]

    async def reimportar(cli_, conta, order_id, event_date=None):
        reg["reimportados"].append((conta, order_id))
        banco[:] = [b for b in banco if b["bling_order_id"] != order_id]
        total = {1: 100.0, 2: 70.0}[order_id]
        banco.append(_banco(order_id, "2026-10-12", total))

    reg = _prepara(monkeypatch, cli, banco, reimportar=reimportar)
    out = asyncio.run(rc.reconciliar_conta("secundaria", hoje=HOJE))

    assert sorted(reg["reimportados"]) == [("secundaria", 1), ("secundaria", 2)]
    dia = _por_dia(reg)["2026-10-12"]
    assert dia["status"] == "reimportado"
    assert dia["qtd_bling"] == dia["qtd_banco"] == 2
    assert dia["soma_banco"] == 170.0
    assert dia["divergentes"]["faltando"] == [2]
    assert dia["divergentes"]["valor_diferente"] == [1]
    assert _por_dia(reg)["2026-10-13"]["status"] == "ok"
    assert reg["alertas"] == []
    assert out["status"] == "ok"


def test_continua_divergente_grava_e_alerta(monkeypatch):
    cli = Cliente([_bling(1, "2026-10-12", 100.0)])
    banco = []

    async def reimportar(cli_, conta, order_id, event_date=None):
        raise RuntimeError("pedido sem lead")

    reg = _prepara(monkeypatch, cli, banco, reimportar=reimportar)
    out = asyncio.run(rc.reconciliar_conta("default", hoje=HOJE))

    dia = _por_dia(reg)["2026-10-12"]
    assert dia["status"] == "divergente"
    assert dia["divergentes"]["faltando"] == [1]
    assert dia["divergentes"]["erros"][0]["pedido"] == 1
    assert reg["alertas"] and reg["alertas"][0][:2] == ("bling_reconciliacao_divergente", "default")
    assert out["status"] == "divergente"
    assert out["dias_divergentes"] == ["2026-10-12"]
    assert out["conferido_ate"] == "2026-10-11", "conferido ate o ultimo dia ok antes do buraco"


def test_pedido_no_banco_apagado_no_bling_continua_divergente(monkeypatch):
    """Sobrando no banco e 404 no Bling: nao cancelamos sozinhos (decisao do dono);
    fica registrado e alertado."""
    cli = Cliente([])
    banco = [_banco(9, "2026-10-12", 30.0)]

    async def reimportar(cli_, conta, order_id, event_date=None):
        raise BlingValidationError("nao encontrado", status=404)

    reg = _prepara(monkeypatch, cli, banco, reimportar=reimportar)
    asyncio.run(rc.reconciliar_conta("default", hoje=HOJE))
    dia = _por_dia(reg)["2026-10-12"]
    assert dia["status"] == "divergente"
    assert dia["divergentes"]["sobrando"] == [9]
    assert dia["divergentes"]["apagados_no_bling"] == [9]


def test_pedido_que_mudou_de_dia_e_corrigido(monkeypatch):
    """Data alterada no Bling: falta num dia e sobra no outro; o reimport acerta."""
    cli = Cliente([_bling(5, "2026-10-13", 40.0)])
    banco = [_banco(5, "2026-10-12", 40.0)]

    async def reimportar(cli_, conta, order_id, event_date=None):
        reg["reimportados"].append(order_id)
        banco[:] = [_banco(5, "2026-10-13", 40.0)]

    reg = _prepara(monkeypatch, cli, banco, reimportar=reimportar)
    out = asyncio.run(rc.reconciliar_conta("default", hoje=HOJE))
    assert reg["reimportados"] == [5], "o mesmo pedido nao e reimportado duas vezes"
    assert _por_dia(reg)["2026-10-12"]["status"] == "reimportado"
    assert _por_dia(reg)["2026-10-13"]["status"] == "reimportado"
    assert out["status"] == "ok"


def test_falha_da_listagem_nao_grava_e_nao_marca_o_dia(monkeypatch):
    cli = Cliente([], erro=BlingServerError("502"))
    reg = _prepara(monkeypatch, cli, [])
    out = asyncio.run(rc.reconciliar_conta("default", hoje=HOJE))
    assert out["status"] == "erro"
    assert reg["gravados"] == [] and reg["estado"] == []


def test_trava_ocupada(monkeypatch):
    cli = Cliente([])
    reg = _prepara(monkeypatch, cli, [])

    @asynccontextmanager
    async def ocupada(account, ttl_segundos=3600):
        raise trava.TravaOcupada("x")
        yield  # pragma: no cover

    monkeypatch.setattr(rc, "trava_pedidos", ocupada)
    out = asyncio.run(rc.reconciliar_conta("default", hoje=HOJE))
    assert out["status"] == "ocupado" and cli.params == []


def test_janela_padrao_e_de_35_dias_e_cabe_num_filtro():
    assert rc.DIAS_PADRAO == 35


# --------------------------------------------------------------------------
# Quando roda: uma vez por dia por conta, de madrugada (BRT), apos a varredura
# --------------------------------------------------------------------------
def test_reconcilia_uma_vez_por_dia_depois_da_hora(monkeypatch):
    chamadas = []

    async def reconciliar(conta, hoje=None):
        chamadas.append(conta)
        return {"status": "ok"}

    monkeypatch.setattr(rc, "reconciliar_conta", reconciliar)
    estado = {}
    monkeypatch.setattr(rc, "_carregar_estado", lambda conta: estado.get(conta))

    cedo = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)      # 01:00 BRT
    depois = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)    # 04:00 BRT
    asyncio.run(rc.reconciliar_se_devido("secundaria", agora=cedo))
    assert chamadas == []
    asyncio.run(rc.reconciliar_se_devido("secundaria", agora=depois))
    assert chamadas == ["secundaria"]

    estado["secundaria"] = {"last_sync_at": depois.isoformat()}
    asyncio.run(rc.reconciliar_se_devido("secundaria",
                                         agora=datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)))
    assert chamadas == ["secundaria"], "ja rodou hoje"


def test_tick_da_varredura_chama_a_reconciliacao_das_duas_contas(monkeypatch):
    import app.bling.varredura as vr
    feitas = []

    async def varrer(conta, agora=None):
        return {"status": "ok"}

    async def reconciliar(conta, agora=None):
        feitas.append(conta)

    monkeypatch.setattr(vr, "varrer_conta", varrer)
    monkeypatch.setattr(rc, "reconciliar_se_devido", reconciliar)
    asyncio.run(vr.bling_pedidos_tick())
    assert feitas == ["default", "secundaria"]


def _tick_com_espioes(monkeypatch):
    import app.bling.varredura as vr
    varridas, reconciliadas = [], []

    async def varrer(conta, agora=None):
        varridas.append(conta)
        return {"status": "ok"}

    async def reconciliar(conta, agora=None):
        reconciliadas.append(conta)

    monkeypatch.setattr(vr, "varrer_conta", varrer)
    monkeypatch.setattr(rc, "reconciliar_se_devido", reconciliar)
    asyncio.run(vr.bling_pedidos_tick())
    return varridas, reconciliadas


def test_reconciliacao_ligada_por_padrao_e_varredura_desligada(monkeypatch):
    from app.bling import config
    monkeypatch.delenv("BLING_RECONCILIACAO_ATIVA", raising=False)
    monkeypatch.delenv("BLING_VARREDURA_ATIVA", raising=False)
    assert config.reconciliacao_ativa() is True
    assert config.varredura_ativa() is False
    varridas, reconciliadas = _tick_com_espioes(monkeypatch)
    assert varridas == []
    assert reconciliadas == ["default", "secundaria"]


def test_reconciliacao_roda_com_a_varredura_desligada(monkeypatch):
    monkeypatch.setenv("BLING_VARREDURA_ATIVA", "false")
    monkeypatch.setenv("BLING_RECONCILIACAO_ATIVA", "true")
    varridas, reconciliadas = _tick_com_espioes(monkeypatch)
    assert varridas == [] and reconciliadas == ["default", "secundaria"]


def test_varredura_roda_com_a_reconciliacao_desligada(monkeypatch):
    monkeypatch.setenv("BLING_VARREDURA_ATIVA", "true")
    monkeypatch.setenv("BLING_RECONCILIACAO_ATIVA", "false")
    varridas, reconciliadas = _tick_com_espioes(monkeypatch)
    assert varridas == ["default", "secundaria"] and reconciliadas == []


def test_nada_roda_com_a_integracao_desligada(monkeypatch):
    monkeypatch.setenv("BLING_ENABLED", "false")
    varridas, reconciliadas = _tick_com_espioes(monkeypatch)
    assert varridas == [] and reconciliadas == []


def test_comando_reconciliar(monkeypatch, capsys):
    from app.bling import ops

    async def reconciliar(conta, hoje=None, dias=None):
        return {"conta": conta, "status": "divergente", "dias": dias}

    monkeypatch.setattr(rc, "reconciliar_conta", reconciliar)
    assert ops.main(["reconciliar", "--conta", "default", "--dias", "10"]) == 1
    assert '"dias": 10' in capsys.readouterr().out


def test_migration_da_reconciliacao():
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"
           / "20261014b_bling_reconciliacao.sql").read_text(encoding="utf-8").lower()
    assert "create table if not exists bling_reconciliacao" in sql
    for col in ("account", "dia", "qtd_bling", "qtd_banco", "soma_bling", "soma_banco",
                "divergentes", "status", "verificado_em"):
        assert col in sql
    assert "primary key (account, dia)" in sql
    assert "enable row level security" in sql

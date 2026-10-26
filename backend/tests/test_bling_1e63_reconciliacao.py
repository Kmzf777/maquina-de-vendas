"""Vendas e receita pela D7 (1e6381fe), Tarefa 1.

- `sold_at` de pedido Bling ao meio-dia de Brasilia (`T12:00:00-03:00`);
- reconciliacao com dias em America/Sao_Paulo;
- reconciliacao compara tambem a situacao do pedido: `situacao.id` da listagem
  diferente de `sales.bling_situacao_id` e divergente e e reimportado (e assim
  que o cancelamento chega em ate 1 dia mesmo sem webhook).
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import date

import pytest

import app.bling.reconciliacao as rc
from app.bling import orders


@pytest.fixture(autouse=True)
def _contas(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_ENABLED", "true")
    monkeypatch.setenv("BLING_VARREDURA_ATIVA", "true")


HOJE = date(2026, 10, 14)


class Cliente:
    def __init__(self, pedidos):
        self.pedidos = pedidos

    async def paginate(self, path, params=None, limite=100):
        for p in self.pedidos:
            yield p

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@asynccontextmanager
async def _livre(account, ttl_segundos=3600):
    yield None


def _prepara(monkeypatch, cliente, banco, *, reimportar=None, dias=3):
    reg = {"gravados": [], "alertas": [], "reimportados": []}

    async def reimportar_padrao(cli, conta, order_id, event_date=None):
        reg["reimportados"].append(order_id)

    monkeypatch.setattr(rc, "_new_client", lambda conta: cliente)
    monkeypatch.setattr(rc, "trava_pedidos", _livre)
    monkeypatch.setattr(rc, "_vendas_do_banco", lambda conta, inicio, fim: list(banco))
    monkeypatch.setattr(rc, "_gravar", lambda linhas: reg["gravados"].extend(linhas))
    monkeypatch.setattr(rc, "_salvar_estado", lambda conta, quando: None)
    monkeypatch.setattr(rc, "alertar",
                        lambda tipo, conta, t, m, **k: reg["alertas"].append(tipo))
    monkeypatch.setattr(rc.pedido_import, "importar_pedido", reimportar or reimportar_padrao)
    monkeypatch.setattr(rc, "DIAS_PADRAO", dias)
    return reg


def _por_dia(reg):
    return {l["dia"]: l for l in reg["gravados"]}


# ---------- sold_at ao meio-dia de Brasilia ----------

def test_sold_at_iso_meio_dia_de_brasilia():
    assert orders._sold_at_iso({"data": "2026-10-13"}, None) == "2026-10-13T12:00:00-03:00"


# ---------- dia em Brasilia ----------

def test_por_dia_banco_usa_dia_de_brasilia():
    dias = rc._por_dia_banco([
        {"bling_order_id": 1, "sold_at": "2026-10-14T01:30:00+00:00", "value": 10},
        {"bling_order_id": 2, "sold_at": "2026-10-13T12:00:00+00:00", "value": 20},
    ])
    assert set(dias) == {"2026-10-13"}
    assert set(dias["2026-10-13"]) == {1, 2}


# ---------- situacao ----------

def test_situacao_diferente_diverge_e_reimporta(monkeypatch):
    cli = Cliente([{"id": 7, "data": "2026-10-12", "total": 100.0, "situacao": {"id": 12}}])
    banco = [{"bling_order_id": 7, "sold_at": "2026-10-12T12:00:00-03:00", "value": 100.0,
              "status": "registrada", "bling_situacao_id": 9}]

    async def reimportar(cli_, conta, order_id, event_date=None):
        reg["reimportados"].append(order_id)
        banco[0] = {**banco[0], "bling_situacao_id": 12, "status": "cancelada"}

    reg = _prepara(monkeypatch, cli, banco, reimportar=reimportar)
    out = asyncio.run(rc.reconciliar_conta("default", hoje=HOJE))

    assert reg["reimportados"] == [7]
    dia = _por_dia(reg)["2026-10-12"]
    assert dia["status"] == "reimportado"
    assert dia["divergentes"]["situacao_diferente"] == [7]
    assert out["status"] == "ok"


def test_situacao_diferente_que_nao_corrige_continua_divergente(monkeypatch):
    cli = Cliente([{"id": 7, "data": "2026-10-12", "total": 100.0, "situacao": {"id": 12}}])
    banco = [{"bling_order_id": 7, "sold_at": "2026-10-12T12:00:00-03:00", "value": 100.0,
              "status": "registrada", "bling_situacao_id": 9}]
    reg = _prepara(monkeypatch, cli, banco)
    out = asyncio.run(rc.reconciliar_conta("default", hoje=HOJE))

    assert reg["reimportados"] == [7]
    assert _por_dia(reg)["2026-10-12"]["status"] == "divergente"
    assert out["dias_divergentes"] == ["2026-10-12"]


def test_situacao_e_valor_iguais_ficam_ok(monkeypatch):
    cli = Cliente([{"id": 7, "data": "2026-10-12", "total": 100.0, "situacao": {"id": 9}}])
    banco = [{"bling_order_id": 7, "sold_at": "2026-10-12T12:00:00-03:00", "value": 100.0,
              "status": "registrada", "bling_situacao_id": 9}]
    reg = _prepara(monkeypatch, cli, banco)
    out = asyncio.run(rc.reconciliar_conta("default", hoje=HOJE))

    assert reg["reimportados"] == []
    assert all(l["status"] == "ok" for l in reg["gravados"])
    assert out["status"] == "ok"


@pytest.mark.parametrize("sit_bling, sit_banco", [(None, 9), (12, None)])
def test_situacao_nula_de_um_lado_nao_diverge(monkeypatch, sit_bling, sit_banco):
    pedido = {"id": 7, "data": "2026-10-12", "total": 100.0}
    if sit_bling is not None:
        pedido["situacao"] = {"id": sit_bling}
    cli = Cliente([pedido])
    banco = [{"bling_order_id": 7, "sold_at": "2026-10-12T12:00:00-03:00", "value": 100.0,
              "status": "registrada", "bling_situacao_id": sit_banco}]
    reg = _prepara(monkeypatch, cli, banco)
    asyncio.run(rc.reconciliar_conta("default", hoje=HOJE))

    assert reg["reimportados"] == []
    assert _por_dia(reg)["2026-10-12"]["status"] == "ok"


# ---------- limites da leitura do banco ----------

class _Consulta:
    def __init__(self, chamadas):
        self.chamadas = chamadas
        self.not_ = self

    def __getattr__(self, nome):
        def metodo(*args, **kwargs):
            self.chamadas.append((nome, args))
            return self
        return metodo

    def execute(self):
        return type("R", (), {"data": []})()


def test_vendas_do_banco_limites_em_brasilia(monkeypatch):
    chamadas = []
    consulta = _Consulta(chamadas)
    monkeypatch.setattr(rc, "get_supabase",
                        lambda: type("S", (), {"table": lambda self, nome: consulta})())

    rc._vendas_do_banco("default", date(2026, 10, 11), date(2026, 10, 13))

    assert ("gte", ("sold_at", "2026-10-11T00:00:00-03:00")) in chamadas
    assert ("lt", ("sold_at", "2026-10-14T00:00:00-03:00")) in chamadas
    select = [a for n, a in chamadas if n == "select"][0][0]
    assert "bling_situacao_id" in select

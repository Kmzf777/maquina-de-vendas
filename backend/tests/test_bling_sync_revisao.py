"""Correcoes da revisao de codigo da sincronia Bling (fases 0-3).

Cada bloco cobre um achado da revisao:
  1. nome da situacao indisponivel nao apaga o nome gravado nem reabre venda cancelada;
  2. pedido com falha PERMANENTE (sem lead, 4xx) nao trava o cursor da varredura
     nem o backfill: fica registrado (alerta com dedup) e o job segue;
  3. reconciliacao: pedido apagado no Bling e ja cancelado no banco = dia ok ("apagado");
  4. decisao do dono: o degrau `lead_assigned` do vendedor so vale para venda dos
     ultimos 60 dias;
  5. decisao do dono: devolucao PARCIAL nao cancela a venda, marca para revisao;
  6. menores (reabertura com processed_at nulo, ordem por data de verdade, cursor
     do backfill, Redis fora, Reposicao pela varredura, migrations, paginacao).

Cliente Bling e banco sao dubles; os dubles das fases 0-3 sao reaproveitados.
"""
import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

import app.bling.backfill as bf
import app.bling.orders as orders
import app.bling.pedido_import as pi
import app.bling.reconciliacao as rc
import app.bling.varredura as vr
import app.bling.webhook_processor as wp
from app.bling import alertas, trava
from app.bling.errors import (
    BlingRateLimitError, BlingServerError, BlingValidationError,
)
from tests.test_bling_sync_fase0 import FakeClient, _prepara as _prepara_backfill
from tests.test_bling_sync_fase1 import DB, _db_vendedor, _pedido, _upsert, _usa
from tests.test_bling_sync_fase2 import Cliente as ClienteVarredura, _prepara as _prepara_varredura
from tests.test_bling_sync_fase3 import (
    Cliente as ClienteReconciliacao, _banco, _bling, _por_dia, _prepara as _prepara_reconciliacao,
)

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"


@pytest.fixture(autouse=True)
def _contas(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_ENABLED", "true")
    monkeypatch.delenv("BLING_VENDEDOR_LEAD_DIAS", raising=False)
    orders._cache_email_usuario.clear()
    getattr(trava, "pulos_sem_redis", {}).clear()


def _hoje_menos(dias: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=dias)).isoformat()


def _captura_alertas(monkeypatch, modulo) -> list:
    capturados = []
    monkeypatch.setattr(modulo, "alertar",
                        lambda tipo, conta, titulo, msg, **k:
                        capturados.append({"tipo": tipo, "conta": conta, **k}) or True)
    return capturados


# ==========================================================================
# 1. Nome da situacao indisponivel (falha transitoria ou situacao fora do espelho)
# ==========================================================================
def _venda(**extra):
    base = {"bling_account": "default", "bling_order_id": 900, "id": "SALE-1",
            "origin": "bling", "status": "registrada"}
    base.update(extra)
    return base


def test_cancelada_com_lookup_do_nome_falho_continua_cancelada_e_mantem_o_nome(monkeypatch):
    db = DB(sales=[_venda(status="cancelada", bling_situacao_id=31,
                          bling_situacao_nome="Devolvido")],
            bling_situacoes=[])
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(situacao={"id": 31}))
    assert linha["status"] == "cancelada", "nome desconhecido nao reabre venda cancelada"
    assert linha["bling_situacao_nome"] == "Devolvido", "mesmo id: reaproveita o nome gravado"


def test_lookup_que_levanta_conta_como_nome_desconhecido(monkeypatch):
    db = DB(sales=[_venda(status="cancelada", bling_situacao_id=31,
                          bling_situacao_nome="Devolvido")])
    _usa(monkeypatch, db, orders)
    monkeypatch.setattr(orders, "_situacao_nome", lambda situacao_id, account: None)
    linha = _upsert(db, _pedido(situacao={"id": 31}))
    assert linha["status"] == "cancelada"
    assert linha["bling_situacao_nome"] == "Devolvido"


def test_situacao_nova_sem_nome_nao_apaga_o_nome_nem_reabre(monkeypatch):
    db = DB(sales=[_venda(status="cancelada", bling_situacao_id=31,
                          bling_situacao_nome="Devolvido")],
            bling_situacoes=[])
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(situacao={"id": 40}))
    assert linha["status"] == "cancelada"
    assert linha["bling_situacao_id"] == 40
    assert "bling_situacao_nome" not in linha, "nome nao-nulo nunca vira NULL"


def test_venda_registrada_com_lookup_falho_mantem_o_nome(monkeypatch):
    db = DB(sales=[_venda(bling_situacao_id=9, bling_situacao_nome="Atendido")],
            bling_situacoes=[])
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(situacao={"id": 9}))
    assert linha["status"] == "registrada"
    assert linha["bling_situacao_nome"] == "Atendido"


def test_reabertura_continua_funcionando_com_o_nome_conhecido(monkeypatch):
    db = DB(sales=[_venda(status="cancelada", bling_situacao_id=12,
                          bling_situacao_nome="Cancelado")],
            bling_situacoes=[{"account": "default", "id": 6, "nome": "Em aberto"}])
    _usa(monkeypatch, db, orders)
    assert _upsert(db, _pedido(situacao={"id": 6}))["status"] == "registrada"


# ==========================================================================
# 5. Devolucao parcial (decisao do dono): continua venda, marca para revisao
# ==========================================================================
@pytest.mark.parametrize("nome", ["Devolvido parcialmente", "Devolução parcial",
                                  "DEVOLUCAO PARCIAL", "Parcialmente devolvido"])
def test_devolucao_parcial_mantem_a_venda_e_marca_para_revisao(monkeypatch, nome):
    db = DB(sales=[], bling_situacoes=[{"account": "secundaria", "id": 31, "nome": nome}])
    _usa(monkeypatch, db, orders)
    alertados = _captura_alertas(monkeypatch, orders)
    linha = _upsert(db, _pedido(situacao={"id": 31}), "secundaria")
    assert linha["status"] == "registrada"
    assert linha["devolucao_parcial"] is True
    assert alertados and alertados[0]["tipo"] == "bling_devolucao_parcial"
    assert alertados[0]["conta"] == "secundaria"
    assert alertados[0]["metadata"]["pedido"] == 900


@pytest.mark.parametrize("nome", ["Devolvido", "Em devolução", "Cancelado", "Devolução total"])
def test_devolucao_total_e_cancelamento_cancelam(monkeypatch, nome):
    db = DB(sales=[], bling_situacoes=[{"account": "default", "id": 31, "nome": nome}])
    _usa(monkeypatch, db, orders)
    alertados = _captura_alertas(monkeypatch, orders)
    linha = _upsert(db, _pedido(situacao={"id": 31}))
    assert linha["status"] == "cancelada"
    assert linha["devolucao_parcial"] is False
    assert alertados == []


def test_devolucao_parcial_ja_marcada_nao_alerta_de_novo(monkeypatch):
    db = DB(sales=[_venda(bling_situacao_id=31, bling_situacao_nome="Devolvido parcialmente",
                          devolucao_parcial=True)],
            bling_situacoes=[{"account": "default", "id": 31, "nome": "Devolvido parcialmente"}])
    _usa(monkeypatch, db, orders)
    alertados = _captura_alertas(monkeypatch, orders)
    linha = _upsert(db, _pedido(situacao={"id": 31}))
    assert linha["devolucao_parcial"] is True and linha["status"] == "registrada"
    assert alertados == []


def test_cancelada_por_devolucao_total_que_vira_parcial_volta_a_venda(monkeypatch):
    db = DB(sales=[_venda(status="cancelada", bling_situacao_id=30,
                          bling_situacao_nome="Devolvido")],
            bling_situacoes=[{"account": "default", "id": 31, "nome": "Devolvido parcialmente"}])
    _usa(monkeypatch, db, orders)
    _captura_alertas(monkeypatch, orders)
    assert _upsert(db, _pedido(situacao={"id": 31}))["status"] == "registrada"


def test_situacao_normal_limpa_a_marca_de_devolucao_parcial(monkeypatch):
    db = DB(sales=[_venda(bling_situacao_id=31, devolucao_parcial=True)],
            bling_situacoes=[{"account": "default", "id": 9, "nome": "Atendido"}])
    _usa(monkeypatch, db, orders)
    assert _upsert(db, _pedido(situacao={"id": 9}))["devolucao_parcial"] is False


def test_nome_desconhecido_nao_mexe_na_marca_de_devolucao_parcial(monkeypatch):
    db = DB(sales=[_venda(bling_situacao_id=31, devolucao_parcial=True)], bling_situacoes=[])
    _usa(monkeypatch, db, orders)
    assert "devolucao_parcial" not in _upsert(db, _pedido(situacao={"id": 77}))


# ==========================================================================
# 4. Vendedor: `lead_assigned` so para venda dos ultimos 60 dias (decisao do dono)
# ==========================================================================
def _com_responsavel(monkeypatch):
    monkeypatch.setattr(orders, "_email_do_usuario",
                        lambda uid: "ana@cafe.com" if uid == "uuid-ana" else None)


def test_responsavel_do_lead_vale_para_venda_recente(monkeypatch):
    db = _db_vendedor(bling_contacts=[])
    _usa(monkeypatch, db, orders)
    _com_responsavel(monkeypatch)
    linha = _upsert(db, _pedido(data=_hoje_menos(30)))
    assert linha["sold_by"] == "ana@cafe.com"
    assert linha["vendedor_fonte"] == "lead_assigned"


def test_venda_antiga_nao_herda_o_responsavel_atual_do_lead(monkeypatch):
    db = _db_vendedor(bling_contacts=[])
    _usa(monkeypatch, db, orders)
    _com_responsavel(monkeypatch)
    linha = _upsert(db, _pedido(data=_hoje_menos(90)))
    assert "sold_by" not in linha and "vendedor_fonte" not in linha


def test_venda_antiga_continua_usando_pedido_e_contato(monkeypatch):
    db = _db_vendedor()
    _usa(monkeypatch, db, orders)
    _com_responsavel(monkeypatch)
    assert _upsert(db, _pedido(data=_hoje_menos(400), vendedor={"id": 11}))["vendedor_fonte"] \
        == "bling_pedido"
    assert _upsert(db, _pedido(data=_hoje_menos(400)))["vendedor_fonte"] == "bling_contato"


def test_janela_do_responsavel_e_configuravel(monkeypatch):
    monkeypatch.setenv("BLING_VENDEDOR_LEAD_DIAS", "10")
    db = _db_vendedor(bling_contacts=[])
    _usa(monkeypatch, db, orders)
    _com_responsavel(monkeypatch)
    assert "sold_by" not in _upsert(db, _pedido(data=_hoje_menos(30)))
    assert _upsert(db, _pedido(data=_hoje_menos(5)))["vendedor_fonte"] == "lead_assigned"


def test_janela_padrao_do_responsavel_e_60_dias(monkeypatch):
    from app.bling import config
    assert config.vendedor_lead_dias() == 60
    monkeypatch.setenv("BLING_VENDEDOR_LEAD_DIAS", "x")
    assert config.vendedor_lead_dias() == 60


def test_venda_antiga_vinda_pela_reimportacao_tambem_respeita_a_janela(monkeypatch):
    """Todos os caminhos (webhook, varredura, backfill, reconciliacao) passam por
    `importar_pedido`/`upsert_from_bling`: a regra vale para todos."""
    db = _db_vendedor(bling_contacts=[])
    _usa(monkeypatch, db, orders)
    _com_responsavel(monkeypatch)

    async def lead(cli, conta, pedido):
        return "L1"

    monkeypatch.setattr(pi, "lead_do_pedido", lead)

    class Cli:
        async def get(self, path, params=None):
            return {"data": _pedido(data=_hoje_menos(200))}

    asyncio.run(pi.importar_pedido(Cli(), "default", 900))
    assert "sold_by" not in db.upserts("sales")[-1]


# ==========================================================================
# 2. Falha PERMANENTE de um pedido nao trava cursor nem backfill
# ==========================================================================
def test_varredura_pedido_envenenado_avanca_o_cursor_e_registra(monkeypatch):
    cli = ClienteVarredura(listados=[{"id": 1}, {"id": 2}, {"id": 3}])
    feitos = []

    async def importar(cli_, conta, order_id, event_date=None, **_k):
        if order_id == 1:
            raise orders.PedidoSemLead("pedido 1 sem lead")
        if order_id == 2:
            raise BlingValidationError("pedido invalido", status=400)
        feitos.append(order_id)

    reg = _prepara_varredura(monkeypatch, cli,
                             estado={"last_sync_at": "2026-10-14T10:00:00+00:00"},
                             importar=importar)
    alertados = _captura_alertas(monkeypatch, vr)
    agora = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)

    out = asyncio.run(vr.varrer_conta("secundaria", agora=agora))

    assert feitos == [3]
    assert reg["salvos"] == [("secundaria", agora.isoformat())], "cursor anda"
    assert out["status"] == "ok"
    assert [i["pedido"] for i in out["ignorados"]] == [1, 2]
    assert len(alertados) == 1
    alerta = alertados[0]
    assert alerta["tipo"] == "bling_pedido_ignorado" and alerta["conta"] == "secundaria"
    assert [i["pedido"] for i in alerta["metadata"]["pedidos"]] == [1, 2]
    assert alerta["metadata"]["origem"] == "varredura"
    assert alerta["chave"], "dedup por conjunto de pedidos, nao so por conta"


def test_varredura_erro_transitorio_continua_segurando_o_cursor(monkeypatch):
    cli = ClienteVarredura(listados=[{"id": 1}, {"id": 2}])

    async def importar(cli_, conta, order_id, event_date=None, **_k):
        raise BlingServerError("502")

    reg = _prepara_varredura(monkeypatch, cli, estado=None, importar=importar)
    out = asyncio.run(vr.varrer_conta("default"))
    assert out["status"] == "interrompido"
    assert reg["salvos"] == []


def test_backfill_pedido_envenenado_segue_para_as_proximas_janelas(monkeypatch):
    client = FakeClient(por_janela={"2026-07-01": [{"id": 1}, {"id": 2}, {"id": 3}],
                                    "2026-07-31": [{"id": 4}]})
    importados = []

    async def importar(cli, account, order_id):
        if order_id == 1:
            raise orders.PedidoSemLead("pedido 1 sem lead")
        if order_id == 2:
            raise BlingValidationError("pedido invalido", status=422)
        importados.append(order_id)

    progresso, _, _, _ = _prepara_backfill(monkeypatch, client, importar=importar)
    alertados = _captura_alertas(monkeypatch, bf)

    out = asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 1),
                             data_final=date(2026, 8, 29)))

    assert importados == [3, 4]
    assert progresso == [("default", "2026-07-30"), ("default", "2026-08-29")]
    assert out["status"] == "concluido"
    assert [i["pedido"] for i in out["ignorados"]] == [1, 2]
    assert [a["tipo"] for a in alertados] == ["bling_pedido_ignorado"]
    assert alertados[0]["metadata"]["origem"] == "backfill"


def test_backfill_erro_desconhecido_continua_parando(monkeypatch):
    """So o que e sabidamente permanente e pulado; erro desconhecido (ex.: banco
    fora) continua segurando o cursor."""
    client = FakeClient(por_janela={"2026-07-01": [{"id": 1}]})

    async def importar(cli, account, order_id):
        raise RuntimeError("conexao com o banco caiu")

    progresso, _, _, _ = _prepara_backfill(monkeypatch, client, importar=importar)
    out = asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 1),
                             data_final=date(2026, 7, 30)))
    assert out["status"] == "interrompido" and progresso == []


def test_alerta_com_chave_de_dedup(monkeypatch):
    vistos, gravados = [], []

    def ja(tipo, conta, horas, chave=None):
        vistos.append(chave)
        return False

    monkeypatch.setattr(alertas, "_ja_alertado", ja)
    monkeypatch.setattr("app.alerts.service.create_system_alert",
                        lambda tipo, titulo, msg, severity="error", metadata=None:
                        gravados.append(metadata))
    assert alertas.alertar("bling_x", "default", "t", "m", chave="varredura:1,2") is True
    assert vistos == ["varredura:1,2"]
    assert gravados[0]["chave"] == "varredura:1,2" and gravados[0]["conta"] == "default"


# ==========================================================================
# 3. Reconciliacao: apagado no Bling e ja cancelado no banco = ok ("apagado")
# ==========================================================================
def _cancelada(id_, dia, valor):
    return {**_banco(id_, dia, valor), "status": "cancelada"}


def test_apagado_no_bling_e_cancelado_no_banco_fica_ok(monkeypatch):
    cli = ClienteReconciliacao([])
    banco = [_cancelada(9, "2026-10-12", 30.0)]

    async def reimportar(cli_, conta, order_id, event_date=None):
        raise BlingValidationError("nao encontrado", status=404)

    reg = _prepara_reconciliacao(monkeypatch, cli, banco, reimportar=reimportar)
    monkeypatch.setattr(rc, "_apagados_conhecidos", lambda conta, inicio, fim: set())
    out = asyncio.run(rc.reconciliar_conta("default", hoje=date(2026, 10, 14)))

    dia = _por_dia(reg)["2026-10-12"]
    assert dia["status"] == "ok"
    assert dia["divergentes"]["observacao"] == "apagado"
    assert dia["divergentes"]["apagados_no_bling"] == [9]
    assert reg["alertas"] == []
    assert out["status"] == "ok"


def test_apagado_ja_conhecido_nao_e_reimportado_todo_dia(monkeypatch):
    cli = ClienteReconciliacao([])
    banco = [_cancelada(9, "2026-10-12", 30.0)]
    reg = _prepara_reconciliacao(monkeypatch, cli, banco)
    monkeypatch.setattr(rc, "_apagados_conhecidos", lambda conta, inicio, fim: {9})
    out = asyncio.run(rc.reconciliar_conta("default", hoje=date(2026, 10, 14)))
    assert reg["reimportados"] == []
    dia = _por_dia(reg)["2026-10-12"]
    assert dia["status"] == "ok" and dia["divergentes"]["observacao"] == "apagado"
    assert out["status"] == "ok"


def test_apagado_mas_nao_cancelado_continua_divergente(monkeypatch):
    cli = ClienteReconciliacao([])
    banco = [_banco(9, "2026-10-12", 30.0) | {"status": "registrada"}]

    async def reimportar(cli_, conta, order_id, event_date=None):
        raise BlingValidationError("nao encontrado", status=404)

    reg = _prepara_reconciliacao(monkeypatch, cli, banco, reimportar=reimportar)
    monkeypatch.setattr(rc, "_apagados_conhecidos", lambda conta, inicio, fim: {9})
    asyncio.run(rc.reconciliar_conta("default", hoje=date(2026, 10, 14)))
    assert _por_dia(reg)["2026-10-12"]["status"] == "divergente"


def test_apagados_conhecidos_le_as_linhas_anteriores(monkeypatch):
    linhas = [{"dia": "2026-10-12", "status": "ok",
               "divergentes": {"apagados_no_bling": [9, 10], "observacao": "apagado"}},
              {"dia": "2026-10-13", "status": "divergente",
               "divergentes": {"apagados_no_bling": [11]}},
              {"dia": "2026-10-11", "status": "ok", "divergentes": {}}]
    db = DB(bling_reconciliacao=[{**l, "account": "default"} for l in linhas])
    monkeypatch.setattr(rc, "get_supabase", lambda: db)
    assert rc._apagados_conhecidos("default", date(2026, 10, 1), date(2026, 10, 13)) == {9, 10}


# ==========================================================================
# 6a. Reabrir `failed` inclui os sem `processed_at`
# ==========================================================================
def test_reabrir_failed_parados_inclui_processed_at_nulo(monkeypatch):
    db = DB(bling_webhook_events=[{"event_id": "E1", "account": "default", "status": "failed"}])
    _usa(monkeypatch, db, wp)
    agora = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    wp.reabrir_falhas("default", parados_ha=timedelta(hours=6), agora=agora)
    corte = (agora - timedelta(hours=6)).isoformat()
    assert ("bling_webhook_events", f"processed_at.is.null,processed_at.lt.{corte}") in db.ors


# ==========================================================================
# 6b. Ordem dos eventos pela DATA, nao pela string
# ==========================================================================
@pytest.mark.parametrize("novo,anterior,atrasado", [
    # mesmo instante em formatos diferentes: nao e atrasado
    ("2026-10-10T12:00:00+00:00", "2026-10-10T12:00:00Z", False),
    ("2026-10-10T09:00:00-03:00", "2026-10-10T12:00:00+00:00", False),
    # 13:00-03:00 = 16:00Z, mais NOVO que 15:00Z (a string diria o contrario)
    ("2026-10-10T13:00:00-03:00", "2026-10-10T15:00:00+00:00", False),
    ("2026-10-10T11:59:59Z", "2026-10-10T12:00:00.250000+00:00", True),
    ("2026-10-10T08:00:00-03:00", "2026-10-10T12:00:00+00:00", True),
    # sem fuso = UTC (mesma assuncao de `venda_recente`)
    ("2026-10-10 11:00:00", "2026-10-10T12:00:00+00:00", True),
    ("2026-10-10 13:00:00", "2026-10-10T12:00:00+00:00", False),
    # ilegivel: nao descarta (o upsert e idempotente)
    ("ontem", "2026-10-10T12:00:00+00:00", False),
    ("2026-10-10T12:00:00Z", None, False),
])
def test_evento_atrasado_compara_datas(novo, anterior, atrasado):
    assert wp._evento_atrasado(novo, anterior) is atrasado


def test_evento_com_offset_mais_novo_nao_e_descartado(monkeypatch):
    async def ultimo(account, order_id):
        return "2026-10-10T15:00:00+00:00"

    monkeypatch.setattr(wp, "_last_event_date", ultimo)
    cancelados = []

    async def cancelar(order_id, event_date, account):
        cancelados.append(order_id)

    monkeypatch.setattr(wp, "cancel_from_bling", cancelar)
    evento = {"event_id": "E", "account": "default", "event": "order.deleted"}
    corpo = {"date": "2026-10-10T13:00:00-03:00", "data": {"id": 900}}
    assert asyncio.run(wp._handle_order(evento, corpo)) == "done"
    assert cancelados == [900]


# ==========================================================================
# 6c. Backfill: intervalo inteiro antes do cursor e `reiniciar` sem recuar o cursor
# ==========================================================================
def test_intervalo_todo_antes_do_cursor_devolve_nada_a_fazer(monkeypatch, caplog):
    client = FakeClient()
    _prepara_backfill(monkeypatch, client, cursor="2026-09-30")
    with caplog.at_level(logging.WARNING):
        out = asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 23),
                                 data_final=date(2026, 8, 21)))
    assert out["status"] == "nada_a_fazer"
    assert "reiniciar" in out["aviso"]
    assert client.params == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_cursor_no_meio_de_uma_janela_retoma_no_dia_seguinte(monkeypatch):
    client = FakeClient()
    _prepara_backfill(monkeypatch, client, cursor="2026-07-15")
    asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 1),
                       data_final=date(2026, 8, 29)))
    assert client.params[0]["dataInicial"] == "2026-07-16"


def test_reiniciar_nao_recua_o_cursor(monkeypatch):
    client = FakeClient()
    progresso, _, _, _ = _prepara_backfill(monkeypatch, client, cursor="2026-09-30")
    out = asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 1),
                             data_final=date(2026, 7, 30), reiniciar=True))
    assert client.params[0]["dataInicial"] == "2026-07-01"
    assert progresso == [], "cursor em 30/09 nao volta para 30/07"
    assert out["status"] == "concluido"


def test_reiniciar_com_recuar_cursor_explicito(monkeypatch):
    client = FakeClient()
    progresso, _, _, _ = _prepara_backfill(monkeypatch, client, cursor="2026-09-30")
    asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 1),
                       data_final=date(2026, 7, 30), reiniciar=True, recuar_cursor=True))
    assert progresso == [("default", "2026-07-30")]


def test_reiniciar_avanca_o_cursor_quando_passa_dele(monkeypatch):
    client = FakeClient()
    progresso, _, _, _ = _prepara_backfill(monkeypatch, client, cursor="2026-07-10")
    asyncio.run(bf.run(account="default", data_inicial=date(2026, 7, 1),
                       data_final=date(2026, 7, 30), reiniciar=True))
    assert progresso == [("default", "2026-07-30")]


def test_comando_backfill_repassa_recuar_cursor(monkeypatch):
    from app.bling import ops
    chamadas = []

    async def fake_run(**kw):
        chamadas.append(kw)
        return {"status": "concluido"}

    monkeypatch.setattr(bf, "run", fake_run)
    ops.main(["backfill", "--conta", "default", "--desde", "2026-07-01", "--reiniciar",
              "--recuar-cursor"])
    assert chamadas[0]["recuar_cursor"] is True and chamadas[0]["reiniciar"] is True


def test_comando_nada_a_fazer_sai_com_codigo_1(monkeypatch):
    from app.bling import ops

    async def fake_run(**kw):
        return {"status": "nada_a_fazer"}

    monkeypatch.setattr(bf, "run", fake_run)
    assert ops.main(["backfill", "--conta", "default", "--desde", "2026-07-01"]) == 1


# ==========================================================================
# 6d. Redis fora: WARNING, alerta apos N pulos seguidos; reconciliacao nao marca o
#     dia quando a reimportacao falha por erro sistemico
# ==========================================================================
@asynccontextmanager
async def _sem_redis(account, ttl_segundos=3600):
    raise trava.RedisIndisponivel("redis fora")
    yield  # pragma: no cover


def test_varredura_sem_redis_alerta_apos_3_pulos(monkeypatch, caplog):
    cli = ClienteVarredura()
    _prepara_varredura(monkeypatch, cli, estado=None)
    monkeypatch.setattr(vr, "trava_pedidos", _sem_redis)
    alertados = _captura_alertas(monkeypatch, vr)

    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            assert asyncio.run(vr.varrer_conta("default"))["status"] == "sem_redis"
    assert alertados == []
    assert any(r.levelno == logging.WARNING and "Redis" in r.getMessage()
               for r in caplog.records)
    asyncio.run(vr.varrer_conta("default"))
    assert [a["tipo"] for a in alertados] == ["bling_redis_indisponivel"]
    assert alertados[0]["conta"] == "default"


def test_varredura_com_redis_de_volta_zera_a_contagem(monkeypatch):
    cli = ClienteVarredura()
    reg = _prepara_varredura(monkeypatch, cli, estado=None)
    alertados = _captura_alertas(monkeypatch, vr)
    from tests.test_bling_sync_fase2 import _livre
    for _ in range(2):
        monkeypatch.setattr(vr, "trava_pedidos", _sem_redis)
        asyncio.run(vr.varrer_conta("default"))
    monkeypatch.setattr(vr, "trava_pedidos", _livre)
    asyncio.run(vr.varrer_conta("default"))
    assert reg["salvos"]
    for _ in range(2):
        monkeypatch.setattr(vr, "trava_pedidos", _sem_redis)
        asyncio.run(vr.varrer_conta("default"))
    assert alertados == []


def test_trava_ocupada_de_verdade_nao_conta_como_redis_fora(monkeypatch):
    cli = ClienteVarredura()
    _prepara_varredura(monkeypatch, cli, estado=None)
    alertados = _captura_alertas(monkeypatch, vr)

    @asynccontextmanager
    async def ocupada(account, ttl_segundos=3600):
        raise trava.TravaOcupada("em uso")
        yield  # pragma: no cover

    monkeypatch.setattr(vr, "trava_pedidos", ocupada)
    for _ in range(4):
        assert asyncio.run(vr.varrer_conta("default"))["status"] == "ocupado"
    assert alertados == []


def test_trava_sem_redis_levanta_redis_indisponivel(monkeypatch):
    class Quebrado:
        async def set(self, *a, **k):
            raise ConnectionError("redis fora")

    monkeypatch.setattr(trava, "_get_redis", lambda: Quebrado())

    async def cenario():
        async with trava.trava_pedidos("default"):
            pass

    with pytest.raises(trava.RedisIndisponivel):
        asyncio.run(cenario())


def test_reconciliacao_sem_redis_alerta_apos_3_pulos(monkeypatch):
    cli = ClienteReconciliacao([])
    reg = _prepara_reconciliacao(monkeypatch, cli, [])
    monkeypatch.setattr(rc, "trava_pedidos", _sem_redis)
    alertados = _captura_alertas(monkeypatch, rc)
    for _ in range(3):
        out = asyncio.run(rc.reconciliar_conta("secundaria", hoje=date(2026, 10, 14)))
    assert out["status"] == "sem_redis"
    assert [a["tipo"] for a in alertados] == ["bling_redis_indisponivel"]
    assert reg["estado"] == []


@pytest.mark.parametrize("erro", [BlingServerError("502"), BlingRateLimitError("429")])
def test_reconciliacao_nao_marca_o_dia_se_a_reimportacao_falha_por_erro_sistemico(
        monkeypatch, erro):
    cli = ClienteReconciliacao([_bling(1, "2026-10-12", 100.0), _bling(2, "2026-10-12", 5.0)])
    tentados = []

    async def reimportar(cli_, conta, order_id, event_date=None):
        tentados.append(order_id)
        raise erro

    reg = _prepara_reconciliacao(monkeypatch, cli, [], reimportar=reimportar)
    out = asyncio.run(rc.reconciliar_conta("default", hoje=date(2026, 10, 14)))
    assert out["status"] == "interrompido"
    assert tentados == [1], "erro sistemico: nao adianta seguir pedido a pedido"
    assert reg["gravados"] == [] and reg["estado"] == [], "fica para o proximo tick"


# ==========================================================================
# 6e. Varredura que recupera venda NOVA e recente abre a Reposicao (como o webhook)
# ==========================================================================
def _prepara_pos_venda(monkeypatch, *, ja_existia=False):
    reposicoes = []

    async def lead(cli, conta, pedido):
        return "LEAD-1"

    async def upsert(pedido, lead_id, event_date, account):
        return "S"

    monkeypatch.setattr(pi, "lead_do_pedido", lead)
    monkeypatch.setattr(pi, "upsert_from_bling", upsert)
    monkeypatch.setattr(pi, "_venda_ja_existia", lambda conta, order_id: ja_existia)
    monkeypatch.setattr(pi, "garantir_reposicao_apos_venda",
                        lambda lead_id, deal_id: reposicoes.append((lead_id, deal_id)))
    return reposicoes


class _CliDetalhe:
    def __init__(self, data):
        self.data = data

    async def get(self, path, params=None):
        return {"data": {"id": 5, "data": self.data}}


def test_importar_com_pos_venda_abre_reposicao_de_venda_nova_e_recente(monkeypatch):
    reposicoes = _prepara_pos_venda(monkeypatch)
    asyncio.run(pi.importar_pedido(_CliDetalhe(_hoje_menos(1)), "secundaria", 5,
                                   pos_venda=True))
    assert reposicoes == [("LEAD-1", None)]


@pytest.mark.parametrize("dias,ja_existia,pos_venda", [
    (30, False, True),   # venda velha
    (1, True, True),     # venda que ja estava no banco
    (1, False, False),   # backfill/reconciliacao: sem pos-venda
])
def test_importar_sem_reposicao_fora_da_regra(monkeypatch, dias, ja_existia, pos_venda):
    reposicoes = _prepara_pos_venda(monkeypatch, ja_existia=ja_existia)
    asyncio.run(pi.importar_pedido(_CliDetalhe(_hoje_menos(dias)), "default", 5,
                                   pos_venda=pos_venda))
    assert reposicoes == []


def test_falha_na_reposicao_nao_derruba_a_importacao(monkeypatch):
    _prepara_pos_venda(monkeypatch)

    def explode(lead_id, deal_id):
        raise RuntimeError("reposicao fora")

    monkeypatch.setattr(pi, "garantir_reposicao_apos_venda", explode)
    pedido = asyncio.run(pi.importar_pedido(_CliDetalhe(_hoje_menos(1)), "default", 5,
                                            pos_venda=True))
    assert pedido["id"] == 5


def test_varredura_importa_com_pos_venda(monkeypatch):
    cli = ClienteVarredura(listados=[{"id": 1}])
    kwargs = []

    async def importar(cli_, conta, order_id, event_date=None, **k):
        kwargs.append(k)

    _prepara_varredura(monkeypatch, cli, estado=None, importar=importar)
    asyncio.run(vr.varrer_conta("default"))
    assert kwargs == [{"pos_venda": True}]


# ==========================================================================
# 6f/6g. Migrations
# ==========================================================================
def _sql(nome):
    return (MIGRATIONS / nome).read_text(encoding="utf-8").lower()


def _ativo(sql):
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


def test_migration_reconciliacao_tem_policy_para_consulta_ro():
    ativo = _ativo(_sql("20261014b_bling_reconciliacao.sql"))
    assert "to consulta_ro" in ativo and "create policy" in ativo
    bloco = ativo[ativo.index("pg_roles"):]
    assert "consulta_ro" in bloco and "create policy" in bloco, \
        "policy so quando o role existe, como o grant"


def test_migration_fase1_check_not_valid_e_validate_separado():
    ativo = _ativo(_sql("20261014_bling_sync_webhook_vendedor.sql"))
    assert "not valid" in ativo
    assert "validate constraint sales_vendedor_fonte_check" in ativo
    add = ativo.index("add constraint sales_vendedor_fonte_check")
    assert ativo.index("not valid", add) < ativo.index("validate constraint")


def test_migration_fase1_cria_devolucao_parcial():
    ativo = _ativo(_sql("20261014_bling_sync_webhook_vendedor.sql"))
    assert "add column if not exists devolucao_parcial boolean" in ativo


# ==========================================================================
# 6i. Reconciliacao pagina a leitura do banco (max_rows do PostgREST)
# ==========================================================================
class _Paginado:
    def __init__(self, linhas):
        self.linhas = linhas
        self.ranges = []
        self.ordenado = False

    def table(self, nome):
        assert nome == "sales"
        return self

    @property
    def not_(self):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a):
        return self

    def is_(self, *_a):
        return self

    def gte(self, *_a):
        return self

    def lt(self, *_a):
        return self

    def order(self, *_a, **_k):
        self.ordenado = True
        return self

    def range(self, inicio, fim):
        self.ranges.append((inicio, fim))
        self._fatia = self.linhas[inicio:fim + 1]
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self._fatia
        return r


def test_vendas_do_banco_pagina_ate_acabar(monkeypatch):
    linhas = [_banco(i, "2026-10-12", 1.0) for i in range(5)]
    fake = _Paginado(linhas)
    monkeypatch.setattr(rc, "get_supabase", lambda: fake)
    monkeypatch.setattr(rc, "_PAGINA", 2)
    out = rc._vendas_do_banco("default", date(2026, 10, 1), date(2026, 10, 13))
    assert [v["bling_order_id"] for v in out] == [0, 1, 2, 3, 4]
    assert fake.ranges == [(0, 1), (2, 3), (4, 5)]
    assert fake.ordenado, "paginar sem ordem estavel pula/repete linhas"

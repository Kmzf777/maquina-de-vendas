"""Varredura periodica de pedidos, POR CONTA (Fase 2 da avaliacao 2026-10-13).

Depois do backfill, a unica porta de entrada de pedido era o webhook (G3).
Webhook perdido (fora do ar, assinatura invalida, deploy) ou que falhou nunca
era recuperado, e a situacao de pedido sem webhook novo congelava (G5).

Aqui, a cada 1-3 h (`BLING_VARREDURA_HORAS`), para cada conta, em sequencia:
  1. lista `/pedidos/vendas` com `dataAlteracaoInicial` = cursor da conta
     (`bling_sync_state(account, 'orders_sweep').last_sync_at`), menos a margem
     de fuso/relogio de `to_bling_datetime` — a mesma usada em produtos e
     contatos;
  2. importa cada pedido listado (detalhe + lead com contato sob demanda +
     upsert), com `event_date` = hora da leitura;
  3. so entao avanca o cursor para o INICIO desta rodada. Falha TRANSITORIA ou
     desconhecida de pedido segura o cursor (a proxima rodada relista a mesma
     janela) e alerta. Falha PERMANENTE (`pedido_import.PERMANENTES`: pedido sem
     lead, 4xx do Bling) NAO segura: o pedido fica registrado no alerta
     `bling_pedido_ignorado` (dedup pelo conjunto de pedidos) e o cursor anda —
     senao um unico pedido envenenado congelaria a varredura da conta para
     sempre. A reconciliacao diaria continua apontando esses pedidos;
  4. reabre os eventos de webhook `failed` da conta parados ha mais de 6 h
     (recebidos nos ultimos 7 dias).

ASSUNCAO A VERIFICAR ANTES DO DEPLOY (runbook): que `GET /pedidos/vendas`
aceita `dataAlteracaoInicial` (formato 'Y-m-d H:i:s', como em `/produtos` e
`/contatos`). A documentacao oficial nao foi consultavel daqui. Se o Bling
ignorar o filtro, a listagem traz a base inteira: a guarda
`MAX_PEDIDOS_POR_RODADA` para a rodada e alerta (`bling_varredura_filtro`) em
vez de reimportar milhares de pedidos.

Rate limit, cota diaria e token: tudo pelo `BlingClient(account=conta)` — o
mesmo token-bucket de 3 req/s e o mesmo `auth.get_access_token` (com o lock de
refresh por conta) que o resto da integracao usa. Nenhum refresher novo.
Backfill, varredura e reconciliacao dividem a trava `bling:pedidos:{conta}`.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.bling import config, pedido_import
from app.bling.alertas import alertar
from app.bling.dates import to_bling_datetime
from app.bling.errors import (
    BlingAuthError, BlingNotConfigured, BlingRateLimitError, BlingServerError,
    BlingValidationError,
)
from app.bling.sync import _load_sync_state, _save_sync_state
from app.bling.trava import (
    PULOS_PARA_ALERTAR, RedisIndisponivel, TravaOcupada, registrar_pulo_sem_redis,
    trava_pedidos, zerar_pulos_sem_redis,
)
from app.bling.webhook_processor import reabrir_falhas

logger = logging.getLogger(__name__)

RESOURCE = "orders_sweep"
# Primeira rodada (sem cursor): olha 3 dias para tras. O historico e assunto do
# backfill; 3 dias cobrem um fim de semana de webhook perdido.
JANELA_INICIAL = timedelta(days=3)
# Guarda de custo/filtro: a conta mais movimentada tem ~30 pedidos/semana.
MAX_PEDIDOS_POR_RODADA = 500
_TRAVA_TTL = 3600
_SISTEMICOS = (BlingAuthError, BlingNotConfigured, BlingRateLimitError, BlingServerError)
# Reabertura dos `failed` do webhook (G2): so os que desistiram ha 6 h, recebidos
# na ultima semana. Mais velho que isso, quem pega e a reconciliacao.
REABRIR_PARADOS_HA = timedelta(hours=6)
REABRIR_RECEBIDOS_DESDE = timedelta(days=7)


def _new_client(account: str):
    from app.bling.client import BlingClient
    return BlingClient(account=account)


def _carregar_estado(conta: str) -> dict | None:
    return _load_sync_state(RESOURCE, conta)


def _salvar_estado(conta: str, quando: str) -> None:
    _save_sync_state(RESOURCE, conta, last_sync_at=quando)


async def varrer_conta(account: str, *, agora: datetime | None = None) -> dict:
    """Uma rodada da varredura numa conta. Nunca levanta (o tick isola contas)."""
    conta = config.account(account).key
    inicio = agora or datetime.now(timezone.utc)
    resultado: dict = {"conta": conta, "status": "ok", "pedidos": 0, "falhas": [],
                       "ignorados": []}

    try:
        async with trava_pedidos(conta, _TRAVA_TTL):
            zerar_pulos_sem_redis(RESOURCE, conta)
            try:
                await _rodada(conta, inicio, resultado)
            finally:
                # Registro duravel dos pulados, tambem quando a rodada para no meio.
                if resultado["ignorados"]:
                    pedido_import.registrar_ignorados(alertar, conta, "varredura",
                                                      resultado["ignorados"])
    except RedisIndisponivel as exc:
        pulos = registrar_pulo_sem_redis(RESOURCE, conta)
        logger.warning("[BLING VARREDURA] conta %s pulada: Redis indisponivel (%d seguida(s)): %s",
                       conta, pulos, exc)
        if pulos >= PULOS_PARA_ALERTAR:
            alertar("bling_redis_indisponivel", conta,
                    "Varredura Bling parada: Redis indisponivel",
                    f"{pulos} rodadas seguidas sem a trava bling:pedidos (Redis fora). "
                    "Pedidos alterados nao estao sendo recuperados.",
                    metadata={"job": RESOURCE, "pulos": pulos})
        resultado["status"] = "sem_redis"
        return resultado
    except TravaOcupada as exc:
        logger.info("[BLING VARREDURA] conta %s pulada: %s", conta, exc)
        resultado["status"] = "ocupado"
        return resultado

    try:
        resultado["webhooks_reabertos"] = await asyncio.to_thread(
            reabrir_falhas, conta, parados_ha=REABRIR_PARADOS_HA,
            recebidos_desde=REABRIR_RECEBIDOS_DESDE)
    except Exception:  # noqa: BLE001
        logger.warning("[BLING VARREDURA] conta %s: reabrir failed falhou", conta, exc_info=True)
    return resultado


async def _rodada(conta: str, inicio: datetime, resultado: dict) -> None:
    estado = await asyncio.to_thread(_carregar_estado, conta)
    desde = (estado or {}).get("last_sync_at") or (inicio - JANELA_INICIAL).isoformat()
    params = {"dataAlteracaoInicial": to_bling_datetime(desde)}
    resultado["desde"] = params["dataAlteracaoInicial"]

    async with _new_client(conta) as client:
        try:
            ids = []
            async for p in client.paginate("/pedidos/vendas", params):
                ids.append(int(p["id"]))
                if len(ids) > MAX_PEDIDOS_POR_RODADA:
                    break
        except Exception as exc:  # noqa: BLE001 — sem listagem, nada a fazer nesta rodada
            resultado.update(status="interrompido", erro=str(exc))
            logger.warning("[BLING VARREDURA] conta %s: listagem falhou: %s", conta, exc)
            if not isinstance(exc, BlingRateLimitError):
                alertar("bling_varredura_falhou", conta, "Varredura Bling sem listagem",
                        f"Listagem de pedidos alterados falhou: {exc}")
            return

        if len(ids) > MAX_PEDIDOS_POR_RODADA:
            resultado.update(status="interrompido", erro="listagem grande demais")
            alertar("bling_varredura_filtro", conta,
                    "Varredura Bling: listagem grande demais",
                    f"Mais de {MAX_PEDIDOS_POR_RODADA} pedidos alterados desde {params}. "
                    "O filtro dataAlteracaoInicial pode estar sendo ignorado pelo Bling; "
                    "nada foi importado e o cursor nao andou.")
            return

        lido_em = inicio.isoformat()
        for order_id in dict.fromkeys(ids):
            try:
                # pos_venda: pedido NOVO e recente recuperado aqui (webhook perdido)
                # abre a Reposicao como o webhook abriria (mesma guarda de 7 dias).
                await pedido_import.importar_pedido(client, conta, order_id, event_date=lido_em,
                                                    pos_venda=True)
                resultado["pedidos"] += 1
            except pedido_import.PERMANENTES as exc:
                if isinstance(exc, BlingValidationError) and exc.status == 404:
                    # sumiu entre a listagem e o detalhe (apagado): nao e falha da rodada
                    logger.info("[BLING VARREDURA] conta %s pedido %s nao existe mais",
                                conta, order_id)
                    continue
                logger.warning("[BLING VARREDURA] conta %s pedido %s ignorado (permanente): %s",
                               conta, order_id, exc)
                resultado["ignorados"].append({"pedido": order_id, "erro": str(exc)})
            except _SISTEMICOS as exc:
                resultado["falhas"].append({"pedido": order_id, "erro": str(exc)})
                resultado.update(status="interrompido", erro=str(exc))
                logger.warning("[BLING VARREDURA] conta %s parou no pedido %s: %s",
                               conta, order_id, exc)
                return
            except Exception as exc:  # noqa: BLE001 — falha DO PEDIDO: segue a rodada
                logger.error("[BLING VARREDURA] conta %s pedido %s falhou: %s",
                             conta, order_id, exc)
                resultado["falhas"].append({"pedido": order_id, "erro": str(exc)})

    if resultado["falhas"]:
        resultado["status"] = "parcial"
        alertar("bling_varredura_falhou", conta,
                f"Varredura Bling com pedidos falhando ({config.account(conta).label})",
                f"{len(resultado['falhas'])} pedido(s) falharam; o cursor nao andou e a "
                "proxima rodada tenta de novo.",
                metadata={"falhas": resultado["falhas"][:50]})
        return

    await asyncio.to_thread(_salvar_estado, conta, inicio.isoformat())
    logger.info("[BLING VARREDURA] conta %s: %d pedidos desde %s",
                conta, resultado["pedidos"], params["dataAlteracaoInicial"])


async def bling_pedidos_tick() -> None:
    """Tick do worker: varre (e, uma vez por dia, reconcilia) as contas em
    SEQUENCIA (o orcamento e por conta, mas rodar em serie deixa o log legivel e
    o pico de carga no banco menor)."""
    if not config.enabled() or not config.varredura_ativa():
        return
    for conta in config.accounts():
        try:
            resultado = await varrer_conta(conta.key)
            logger.info("[BLING VARREDURA] %s", {k: v for k, v in resultado.items()
                                                 if k != "falhas"})
        except Exception:  # noqa: BLE001 — uma conta nunca derruba a outra
            logger.error("[BLING VARREDURA] conta %s falhou", conta.key, exc_info=True)
        # Reconciliacao diaria (Fase 3): mesmo tick, DEPOIS da varredura da conta,
        # para nao disputar a trava. So roda uma vez por dia, de madrugada (BRT).
        try:
            from app.bling import reconciliacao
            await reconciliacao.reconciliar_se_devido(conta.key)
        except Exception:  # noqa: BLE001
            logger.error("[BLING RECONCILIACAO] conta %s falhou", conta.key, exc_info=True)

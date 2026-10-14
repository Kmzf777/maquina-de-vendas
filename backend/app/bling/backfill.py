"""Importacao dos pedidos historicos (decisao D8: 12 meses).

Janelas de 30 dias por dois motivos: o filtro de periodo do Bling rejeita
intervalos maiores que 1 ano (HTTP 400), e janelas curtas tornam o job
retomavel — se cair no meio, recomeca da ultima janela concluida, nao do zero.

Custo: ~2 chamadas por pedido (listagem paginada + GET do detalhe, que e a
unica forma de obter os itens). Com 3 req/s, ~1,5 pedido por segundo.

MULTI-CONTA (avaliacao 2026-10-13, Fase 0): `run()` recebe a conta e um
intervalo de datas, e o endpoint /backfill e o script
`python -m app.bling.ops` expoem os dois. As duas contas sao tratadas igual:
cursor proprio em `bling_sync_state(account, resource='backfill')`, trava
propria (`trava.trava_pedidos`) e orcamento de rate limit proprio (o
`BlingClient` da conta).

PARADA NO MEIO (G1): o backfill da conta 1 parou com o cursor em 2026-07-22 e
ninguem soube. Agora:
  - um pedido que falha nao derruba a janela — os outros entram —, mas o
    cursor NAO avanca e o job para ali, com alerta (`system_alerts`) e log em
    ERROR listando os pedidos. Rodar de novo refaz so aquela janela;
  - erro sistemico (token, teto diario, Bling fora) para na hora, com alerta.
Idempotente: `sales` faz upsert por (bling_account, bling_order_id), entao
refazer uma janela nao duplica nada.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from app.bling import config
from app.bling.alertas import alertar
from app.bling.errors import (
    BlingAuthError, BlingNotConfigured, BlingRateLimitError, BlingServerError,
)
from app.bling.orders import upsert_from_bling
from app.bling.trava import TravaOcupada, trava_pedidos
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_RESOURCE = "backfill"
_WINDOW_DAYS = 30
_PAGE_LIMIT = 100
# A trava e estendida a cada janela; o TTL so precisa cobrir UMA janela lenta.
_TRAVA_TTL = 2 * 3600
# Erros em que seguir pedido a pedido so queima orcamento: para na hora.
_SISTEMICOS = (BlingAuthError, BlingNotConfigured, BlingRateLimitError, BlingServerError)


def _new_client(account: str):
    from app.bling.client import BlingClient
    return BlingClient(account=account)


def build_windows(inicio: date, fim: date, dias: int = _WINDOW_DAYS) -> list[tuple[str, str]]:
    """Fatia [inicio, fim] em janelas contiguas de `dias`, sem lacuna nem sobreposicao."""
    janelas = []
    atual = inicio
    while atual <= fim:
        termino = min(atual + timedelta(days=dias - 1), fim)
        janelas.append((atual.isoformat(), termino.isoformat()))
        atual = termino + timedelta(days=1)
    return janelas


def _load_progress(account: str) -> str | None:
    res = (get_supabase().table("bling_sync_state").select("last_cursor")
           .eq("resource", _RESOURCE).eq("account", account)
           .limit(1).maybe_single().execute())
    return (getattr(res, "data", None) or {}).get("last_cursor")


def _save_progress(account: str, cursor: str) -> None:
    (get_supabase().table("bling_sync_state").upsert(
        {"resource": _RESOURCE, "account": account, "last_cursor": cursor,
         "last_sync_at": datetime.now(timezone.utc).isoformat(),
         "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="account,resource").execute())


def _contact_row(account: str, contact_id: int) -> dict | None:
    res = (get_supabase().table("bling_contacts").select("*")
           .eq("account", account).eq("id", contact_id)
           .limit(1).maybe_single().execute())
    return getattr(res, "data", None)


async def _lead_for_contact(account: str, contact_id: int | None) -> str | None:
    if not contact_id:
        return None
    from app.bling.contacts import ensure_lead
    contato = await asyncio.to_thread(_contact_row, account, int(contact_id))
    return await ensure_lead(contato, account) if contato else None


async def _lead_do_pedido(client, account: str, pedido: dict) -> str | None:
    contact_id = (pedido.get("contato") or {}).get("id")
    return await _lead_for_contact(account, contact_id)


async def _importar(client, account: str, order_id: int) -> None:
    """Busca o detalhe (a listagem nao traz itens) e projeta em `sales`."""
    pedido = (await client.get(f"/pedidos/vendas/{order_id}")).get("data") or {}
    if not pedido:
        return
    lead_id = await _lead_do_pedido(client, account, pedido)
    await upsert_from_bling(
        pedido, lead_id=lead_id,
        event_date=f"{pedido.get('data')}T00:00:00+00:00",
        account=account,
    )


def _intervalo(months: int, hoje: date | None, data_inicial: date | None,
               data_final: date | None) -> tuple[date, date]:
    fim = data_final or hoje or datetime.now(timezone.utc).date()
    if data_inicial:
        inicio = data_inicial
    else:
        # -1: queremos `30 * months` DIAS de cobertura (contagem inclusiva). Sem o -1,
        # o intervalo [inicio, fim] tem 30*months + 1 dias e sobra 1 dia solto, gerando
        # uma janela extra de 1 dia toda vez (ex.: months=1 vira 2 janelas, nao 1).
        inicio = fim - timedelta(days=30 * months - 1)
    if inicio > fim:
        raise ValueError(f"intervalo invertido: {inicio} > {fim}")
    return inicio, fim


def _interromper(conta: str, resultado: dict, motivo: str) -> dict:
    resultado["status"] = "interrompido"
    resultado["erro"] = motivo
    meta = {k: v for k, v in resultado.items() if k != "falhas"}
    meta["falhas"] = resultado.get("falhas", [])[:50]
    alertar(
        "bling_backfill_interrompido", conta,
        f"Backfill Bling parou no meio ({config.account(conta).label})",
        f"{motivo}. Concluido ate {resultado.get('concluido_ate') or 'nenhuma janela'}. "
        "Rodar o mesmo comando de novo retoma da janela que falhou.",
        metadata=meta,
    )
    return resultado


async def run(months: int = 12, hoje: date | None = None,
              account: str = config.DEFAULT_ACCOUNT, *,
              data_inicial: date | None = None, data_final: date | None = None,
              reiniciar: bool = False, estimar: bool = False) -> dict:
    """Importa os pedidos de [data_inicial, data_final] (ou dos ultimos `months`
    meses) da conta `account`. Retomavel pelo cursor DA CONTA.

    `reiniciar=True` ignora o cursor (para reimportar um trecho ja concluido).
    `estimar=True` so LISTA: devolve quantos pedidos ha e quantas chamadas o
    backfill de verdade custaria — nada e gravado, nem o cursor.
    """
    conta = config.account(account).key  # valida antes de qualquer chamada
    inicio, fim = _intervalo(months, hoje, data_inicial, data_final)

    concluido_ate = None if reiniciar else await asyncio.to_thread(_load_progress, conta)
    janelas = build_windows(inicio, fim)
    if concluido_ate:
        janelas = [j for j in janelas if j[0] > concluido_ate]
        logger.info("[BLING BACKFILL] conta %s retomando apos %s (%d janelas restantes)",
                    conta, concluido_ate, len(janelas))

    resultado: dict = {
        "conta": conta, "inicio": inicio.isoformat(), "fim": fim.isoformat(),
        "janelas": len(janelas), "janelas_concluidas": 0, "pedidos": 0,
        "concluido_ate": concluido_ate, "falhas": [], "status": "concluido",
    }
    if not janelas:
        return resultado

    try:
        async with trava_pedidos(conta, _TRAVA_TTL) as trava:
            async with _new_client(conta) as client:
                if estimar:
                    return await _estimar(client, janelas, resultado)
                return await _executar(client, conta, janelas, resultado, trava)
    except TravaOcupada as exc:
        logger.warning("[BLING BACKFILL] conta %s: %s", conta, exc)
        resultado["status"] = "ocupado"
        resultado["erro"] = str(exc)
        return resultado


async def _estimar(client, janelas, resultado: dict) -> dict:
    pedidos = 0
    listagens = 0
    for win_inicio, win_fim in janelas:
        n = 0
        async for _ in client.paginate("/pedidos/vendas",
                                       {"dataInicial": win_inicio, "dataFinal": win_fim}):
            n += 1
        # paginas que o backfill de verdade pede: as cheias + a ultima (incompleta/vazia)
        listagens += n // _PAGE_LIMIT + 1
        pedidos += n
    resultado.update({"status": "estimado", "pedidos_no_bling": pedidos,
                      "chamadas_estimadas": listagens + pedidos})
    return resultado


async def _executar(client, conta: str, janelas, resultado: dict, trava) -> dict:
    for win_inicio, win_fim in janelas:
        try:
            params = {"dataInicial": win_inicio, "dataFinal": win_fim}
            ids = [int(p["id"]) async for p in client.paginate("/pedidos/vendas", params)]
        except Exception as exc:  # noqa: BLE001 — sem a listagem nada da janela e confiavel
            return _interromper(conta, resultado,
                                f"listagem da janela {win_inicio}..{win_fim} falhou: {exc}")

        falhas = []
        for order_id in ids:
            try:
                await _importar(client, conta, order_id)
                resultado["pedidos"] += 1
            except _SISTEMICOS as exc:
                resultado["falhas"].extend(falhas)
                return _interromper(conta, resultado,
                                    f"erro sistemico no pedido {order_id} "
                                    f"(janela {win_inicio}..{win_fim}): {exc}")
            except Exception as exc:  # noqa: BLE001 — falha DO PEDIDO: segue a janela
                logger.error("[BLING BACKFILL] conta %s pedido %s falhou: %s",
                             conta, order_id, exc)
                falhas.append({"pedido": order_id, "erro": str(exc)})

        if falhas:
            resultado["falhas"].extend(falhas)
            return _interromper(conta, resultado,
                                f"{len(falhas)} pedido(s) falharam na janela "
                                f"{win_inicio}..{win_fim}")

        await asyncio.to_thread(_save_progress, conta, win_fim)
        await trava.estender()
        resultado["janelas_concluidas"] += 1
        resultado["concluido_ate"] = win_fim
        logger.info("[BLING BACKFILL] conta %s janela %s..%s: %d pedidos (total %d)",
                    conta, win_inicio, win_fim, len(ids), resultado["pedidos"])

    return resultado

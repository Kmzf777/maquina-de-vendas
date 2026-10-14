"""Processa os eventos que o receiver gravou.

Fica fora do request porque o Bling exige 2xx em 5s e aqui precisamos de
`GET /pedidos/vendas/{id}` — o payload do webhook nao traz os itens do pedido.

Duas garantias que este modulo implementa:
  - Idempotencia ja veio do receiver (event_id e PK).
  - ORDEM: a entrega do Bling nao e ordenada. Um `order.updated` antigo pode
    chegar depois de um mais novo e reverteria a situacao do pedido. Comparamos
    `event_date` com o `bling_event_date` ja gravado na venda e descartamos o
    atrasado.

MULTI-CONTA: cada linha de `bling_webhook_events` ja grava o slug da conta que
entregou o evento (o receiver grava isso). Ler `evento["account"]` e mais
direto e mais seguro que iterar `config.accounts()` — a linha ja diz qual
conta processar, entao nao ha o que adivinhar nem risco de processar o evento
com o cliente da conta errada.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.bling import config
from app.bling.orders import (
    _sold_at_iso,
    cancel_from_bling,
    garantir_reposicao_apos_venda,
    upsert_from_bling,
    venda_recente,
)
from app.bling.errors import BlingRateLimitError
from app.bling.pedido_import import buscar_contato
from app.bling.products import apply_product_event
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# BACKOFF por evento (Fase 1, G2/G9). Antes: 6 tentativas, uma por tick, todas
# em ~6 minutos — o evento desistia muito antes de qualquer coisa mudar. Agora a
# n-esima falha espera BACKOFF_MINUTOS[n-1]; somando as 7 esperas sao ~8 h antes
# de virar `failed`. E `failed` nao e mais para sempre: a varredura de pedidos
# (Fase 2) reabre os que desistiram ha mais de 6 h (`reabrir_falhas`).
MAX_ATTEMPTS = 8
BACKOFF_MINUTOS = (1, 5, 15, 30, 60, 120, 240, 240)
# Rate limit/teto diario nao e defeito do evento: reagenda sem gastar tentativa.
_ESPERA_RATE_LIMIT = timedelta(minutes=2)
BATCH = 20


def _new_client(account: str):
    from app.bling.client import BlingClient
    return BlingClient(account=account)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _claim() -> list[dict]:
    agora = _agora().isoformat()
    res = (get_supabase().table("bling_webhook_events")
           .select("*").eq("status", "pending")
           .or_(f"next_attempt_at.is.null,next_attempt_at.lte.{agora}")
           .order("received_at").limit(BATCH).execute())
    return getattr(res, "data", None) or []


def _update(event_id: str, account: str, payload: dict) -> None:
    # PK e (account, event_id) desde a migration multi-conta: filtrar so por
    # event_id alcancaria o evento homonimo da outra conta.
    (get_supabase().table("bling_webhook_events").update(payload)
     .eq("event_id", event_id).eq("account", account).execute())


def _contact_filter(account: str, contact_id: int) -> dict:
    return {"account": account, "id": contact_id}


def _contact_row(account: str, contact_id: int) -> dict | None:
    res = (get_supabase().table("bling_contacts").select("*")
           .eq("account", account).eq("id", contact_id)
           .limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _sale_event_date(account: str, order_id: int) -> str | None:
    res = (get_supabase().table("sales").select("bling_event_date")
           .eq("bling_account", account).eq("bling_order_id", order_id)
           .limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return (linhas[0] or {}).get("bling_event_date") if linhas else None


def _venda_ja_existia(account: str, order_id: int) -> bool:
    """Ja ha linha em `sales` para este pedido? Erro de leitura → True (nao cria card)."""
    try:
        res = (get_supabase().table("sales").select("id")
               .eq("bling_account", account).eq("bling_order_id", order_id)
               .limit(1).execute())
        return bool(getattr(res, "data", None))
    except Exception:
        logger.warning("[BLING WEBHOOK] nao consegui checar se o pedido %s ja existia — "
                       "Reposicao nao sera criada", order_id, exc_info=True)
        return True


async def _last_event_date(account: str, order_id: int) -> str | None:
    return await asyncio.to_thread(_sale_event_date, account, order_id)


async def _resolve_lead(account: str, contato: dict) -> str | None:
    from app.bling.contacts import ensure_lead
    return await ensure_lead(contato, account)


async def _handle_order(evento: dict, corpo: dict) -> str:
    account = evento.get("account") or config.DEFAULT_ACCOUNT
    dados = corpo.get("data") or {}
    order_id = int(dados["id"])
    event_date = corpo.get("date") or evento.get("event_date")

    anterior = await _last_event_date(account, order_id)
    if anterior and event_date and event_date < anterior:
        logger.info("[BLING WEBHOOK] evento %s fora de ordem (%s < %s) — descartado",
                    evento["event_id"], event_date, anterior)
        return "skipped"

    if evento["event"].endswith(".deleted"):
        await cancel_from_bling(order_id, event_date=event_date, account=account)
        return "done"

    async with _new_client(account) as client:
        pedido = (await client.get(f"/pedidos/vendas/{order_id}")).get("data") or {}

        contact_id = (pedido.get("contato") or dados.get("contato") or {}).get("id")
        lead_id = None
        if contact_id:
            contato = await asyncio.to_thread(_contact_row, account, int(contact_id))
            if not contato:
                # G2: cliente cadastrado hoje ainda nao esta no espelho (sync diario).
                # Busca na hora, pelo MESMO cliente da conta (rate limit e token dela).
                logger.info("[BLING WEBHOOK] contato %s fora do espelho — buscando", contact_id)
                contato = await buscar_contato(client, account, int(contact_id))
            if contato:
                lead_id = await _resolve_lead(account, contato)
            else:
                logger.warning("[BLING WEBHOOK] contato %s nao existe no Bling (conta %s)",
                               contact_id, account)

    # Reposicao (spec P1.4): so venda NOVA e RECENTE. A checagem de existencia vem antes
    # do upsert (depois dele a linha sempre existe). Pedido criado pelo CRM ja passou
    # por `create_order`, que cuidou do card — por isso "ja existia" nao cria. O
    # backfill nao passa por aqui, entao nunca abre cards em massa.
    nova_e_recente = False
    if lead_id and venda_recente(_sold_at_iso(pedido, event_date)):
        nova_e_recente = not await asyncio.to_thread(_venda_ja_existia, account, order_id)

    await upsert_from_bling(pedido, lead_id=lead_id, event_date=event_date, account=account)

    if nova_e_recente:
        try:
            await asyncio.to_thread(garantir_reposicao_apos_venda, lead_id, None)
        except Exception:
            logger.exception("[BLING WEBHOOK] Reposicao do lead %s falhou (venda mantida)",
                             lead_id)
    return "done"


async def _handle_product(evento: dict, corpo: dict) -> str:
    account = evento.get("account") or config.DEFAULT_ACCOUNT
    await apply_product_event(evento["event"], corpo.get("data") or {}, account)
    return "done"


async def process_pending() -> int:
    """Processa um lote de eventos pendentes. Devolve quantos concluiram."""
    pendentes = await asyncio.to_thread(_claim)
    concluidos = 0

    for evento in pendentes:
        corpo = evento.get("payload") or {}
        nome = evento.get("event") or ""
        tentativas = int(evento.get("attempts") or 0) + 1
        conta = evento.get("account") or config.DEFAULT_ACCOUNT

        try:
            if nome.startswith("order."):
                status = await _handle_order(evento, corpo)
            elif nome.startswith("product."):
                status = await _handle_product(evento, corpo)
            else:
                logger.info("[BLING WEBHOOK] recurso nao tratado: %s", nome)
                status = "skipped"
        except BlingRateLimitError as exc:
            # Orcamento de 3 req/s ou teto diario da conta: o evento nao tem culpa.
            await asyncio.to_thread(_update, evento["event_id"], conta, {
                "status": "pending", "attempts": tentativas - 1, "last_error": str(exc),
                "next_attempt_at": (_agora() + _ESPERA_RATE_LIMIT).isoformat(),
            })
            continue
        except Exception as exc:  # noqa: BLE001
            if tentativas >= MAX_ATTEMPTS:
                await asyncio.to_thread(_update, evento["event_id"], conta, {
                    "status": "failed", "attempts": tentativas, "last_error": str(exc),
                    # momento da desistencia: `reabrir_falhas(parados_ha=...)` le daqui
                    "processed_at": _agora().isoformat(), "next_attempt_at": None,
                })
                logger.error("[BLING WEBHOOK] evento %s (conta %s) desistiu: %s",
                             evento["event_id"], conta, exc)
            else:
                espera = timedelta(minutes=BACKOFF_MINUTOS[
                    min(tentativas - 1, len(BACKOFF_MINUTOS) - 1)])
                await asyncio.to_thread(_update, evento["event_id"], conta, {
                    "status": "pending", "attempts": tentativas, "last_error": str(exc),
                    "next_attempt_at": (_agora() + espera).isoformat(),
                })
            continue

        await asyncio.to_thread(_update, evento["event_id"], conta, {
            "status": status, "attempts": tentativas,
            "processed_at": _agora().isoformat(), "next_attempt_at": None,
        })
        if status == "done":
            concluidos += 1

    return concluidos


def reabrir_falhas(account: str, *, parados_ha: timedelta | None = None,
                   recebidos_desde: timedelta | None = None,
                   agora: datetime | None = None) -> int:
    """Devolve para a fila (`pending`, tentativas zeradas) os eventos `failed`
    DA CONTA. Devolve quantos reabriu.

    Antes nenhum processo olhava os `failed` de novo (G2): 31 eventos ficaram
    parados para sempre, 4 pedidos nunca entraram. Idempotente — so toca em
    `failed`, entao rodar duas vezes seguidas reabre zero na segunda. O
    `last_error` fica (historico do porque falhou).

    `parados_ha`: so os que desistiram ha pelo menos esse tempo (`processed_at`
    guarda o momento da desistencia). `recebidos_desde`: so os recebidos nessa
    janela — evento muito antigo e assunto da reconciliacao, nao do webhook.
    """
    conta = config.account(account).key
    agora = agora or datetime.now(timezone.utc)
    consulta = (get_supabase().table("bling_webhook_events")
                .update({"status": "pending", "attempts": 0, "next_attempt_at": None})
                .eq("account", conta).eq("status", "failed"))
    if parados_ha is not None:
        consulta = consulta.lt("processed_at", (agora - parados_ha).isoformat())
    if recebidos_desde is not None:
        consulta = consulta.gte("received_at", (agora - recebidos_desde).isoformat())
    res = consulta.execute()
    n = len(getattr(res, "data", None) or [])
    if n:
        logger.info("[BLING WEBHOOK] conta %s: %d evento(s) failed reabertos", conta, n)
    return n


async def bling_webhook_tick() -> None:
    if not config.enabled():
        return
    try:
        await process_pending()
    except Exception as exc:  # noqa: BLE001 — worker nunca morre por causa do Bling
        logger.warning("[BLING WEBHOOK] processamento falhou: %s", exc)

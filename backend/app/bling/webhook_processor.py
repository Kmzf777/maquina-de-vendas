"""Processa os eventos que o receiver gravou.

Fica fora do request porque o Bling exige 2xx em 5s e aqui precisamos de
`GET /pedidos/vendas/{id}` — o payload do webhook nao traz os itens do pedido.

Duas garantias que este modulo implementa:
  - Idempotencia ja veio do receiver (event_id e PK).
  - ORDEM: a entrega do Bling nao e ordenada. Um `order.updated` antigo pode
    chegar depois de um mais novo e reverteria a situacao do pedido. Comparamos
    `event_date` com o `bling_event_date` ja gravado na venda e descartamos o
    atrasado.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.bling import config
from app.bling.orders import cancel_from_bling, upsert_from_bling
from app.bling.products import apply_product_event
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
BATCH = 20


def _new_client():
    from app.bling.client import BlingClient
    return BlingClient()


def _claim() -> list[dict]:
    res = (get_supabase().table("bling_webhook_events")
           .select("*").eq("status", "pending")
           .order("received_at").limit(BATCH).execute())
    return getattr(res, "data", None) or []


def _update(event_id: str, payload: dict) -> None:
    (get_supabase().table("bling_webhook_events").update(payload)
     .eq("event_id", event_id).execute())


def _sale_event_date(order_id: int) -> str | None:
    res = (get_supabase().table("sales").select("bling_event_date")
           .eq("bling_order_id", order_id).limit(1).execute())
    linhas = getattr(res, "data", None) or []
    return (linhas[0] or {}).get("bling_event_date") if linhas else None


async def _last_event_date(order_id: int) -> str | None:
    return await asyncio.to_thread(_sale_event_date, order_id)


def _contact_row(contact_id: int) -> dict | None:
    res = (get_supabase().table("bling_contacts").select("*")
           .eq("id", contact_id).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


async def _resolve_lead(contato: dict) -> str | None:
    from app.bling.contacts import ensure_lead
    return await ensure_lead(contato)


async def _handle_order(evento: dict, corpo: dict) -> str:
    dados = corpo.get("data") or {}
    order_id = int(dados["id"])
    event_date = corpo.get("date") or evento.get("event_date")

    anterior = await _last_event_date(order_id)
    if anterior and event_date and event_date < anterior:
        logger.info("[BLING WEBHOOK] evento %s fora de ordem (%s < %s) — descartado",
                    evento["event_id"], event_date, anterior)
        return "skipped"

    if evento["event"].endswith(".deleted"):
        await cancel_from_bling(order_id, event_date=event_date)
        return "done"

    async with _new_client() as client:
        pedido = (await client.get(f"/pedidos/vendas/{order_id}")).get("data") or {}

    contact_id = (pedido.get("contato") or dados.get("contato") or {}).get("id")
    lead_id = None
    if contact_id:
        contato = await asyncio.to_thread(_contact_row, int(contact_id))
        if contato:
            lead_id = await _resolve_lead(contato)
        else:
            logger.warning("[BLING WEBHOOK] contato %s ausente do espelho", contact_id)

    await upsert_from_bling(pedido, lead_id=lead_id, event_date=event_date)
    return "done"


async def _handle_product(evento: dict, corpo: dict) -> str:
    await apply_product_event(evento["event"], corpo.get("data") or {})
    return "done"


async def process_pending() -> int:
    """Processa um lote de eventos pendentes. Devolve quantos concluiram."""
    pendentes = await asyncio.to_thread(_claim)
    concluidos = 0

    for evento in pendentes:
        corpo = evento.get("payload") or {}
        nome = evento.get("event") or ""
        tentativas = int(evento.get("attempts") or 0) + 1

        try:
            if nome.startswith("order."):
                status = await _handle_order(evento, corpo)
            elif nome.startswith("product."):
                status = await _handle_product(evento, corpo)
            else:
                logger.info("[BLING WEBHOOK] recurso nao tratado: %s", nome)
                status = "skipped"
        except Exception as exc:  # noqa: BLE001
            if tentativas >= MAX_ATTEMPTS:
                await asyncio.to_thread(_update, evento["event_id"], {
                    "status": "failed", "attempts": tentativas, "last_error": str(exc),
                })
                logger.error("[BLING WEBHOOK] evento %s desistiu: %s",
                             evento["event_id"], exc)
            else:
                await asyncio.to_thread(_update, evento["event_id"], {
                    "status": "pending", "attempts": tentativas, "last_error": str(exc),
                })
            continue

        await asyncio.to_thread(_update, evento["event_id"], {
            "status": status, "attempts": tentativas,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        })
        if status == "done":
            concluidos += 1

    return concluidos


async def bling_webhook_tick() -> None:
    if not config.enabled():
        return
    try:
        await process_pending()
    except Exception as exc:  # noqa: BLE001 — worker nunca morre por causa do Bling
        logger.warning("[BLING WEBHOOK] processamento falhou: %s", exc)

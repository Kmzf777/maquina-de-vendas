"""Outbox da integracao: o que nao entrou sincrono entra pela fila.

O caminho feliz do modal de venda e SINCRONO — o vendedor precisa ver o numero
do pedido na hora, senao ele abre o Bling para conferir e a dor volta. A fila
existe so para o caminho triste: Bling fora do ar, 429, timeout.

Erro de VALIDACAO nunca entra aqui: repetir o mesmo payload invalido nao
conserta e ainda conta para o bloqueio de IP (300 erros em 10s).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.bling import config
from app.bling.errors import TRANSIENT
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BATCH = 10
# Backoff exponencial limitado a 30 min: 1, 2, 4, 8, 16, 30, 30, 30 minutos.
_BACKOFF_MINUTES = (1, 2, 4, 8, 16, 30, 30, 30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _insert(row: dict) -> None:
    get_supabase().table("bling_jobs").insert(row).execute()


async def enqueue(kind: str, payload: dict, *, sale_id: str | None = None) -> None:
    payload = dict(payload)  # copia: nao mutamos o dict do chamador

    if kind == "create_order" and not payload.get("idempotency_key"):
        # A chave de idempotencia nasce AQUI, uma unica vez, e vai gravada no
        # job. Toda tentativa le a mesma linha e reusa a mesma chave; se cada
        # tentativa gerasse a sua, o `numeroLoja` mudaria e o Bling criaria um
        # pedido NOVO a cada retentativa — exatamente o que se quer evitar.
        #
        # Por que o caminho SINCRONO (router chamando create_order direto) nao
        # gera chave: la nao existe retentativa. Se o POST sincrono falhar, o
        # router enfileira um job novo e a chave nasce aqui. Gerar chave no
        # sincrono so gastaria uma consulta a mais no orcamento de 3 req/s sem
        # proteger nada.
        payload["idempotency_key"] = f"crm-{uuid4().hex[:16]}"

    await asyncio.to_thread(_insert, {
        "kind": kind,
        "payload": payload,
        "status": "pending",
        "attempts": 0,
        "sale_id": sale_id,
        "run_after": _now().isoformat(),
    })
    logger.info("[BLING JOBS] enfileirado %s (sale=%s, chave=%s)",
                kind, sale_id, payload.get("idempotency_key"))


def _claim() -> list[dict]:
    res = (get_supabase().table("bling_jobs")
           .select("*").eq("status", "pending")
           .lte("run_after", _now().isoformat())
           .order("run_after").limit(BATCH).execute())
    return getattr(res, "data", None) or []


def _update(job_id: str, payload: dict) -> None:
    get_supabase().table("bling_jobs").update(payload).eq("id", job_id).execute()


async def _handle_create_order(payload: dict, job: dict) -> dict:
    """Retenta a criacao do pedido e casa com a `sales` que ja existe."""
    from app.bling.client import BlingClient
    from app.bling.orders import create_order

    # A chave veio gravada no payload pelo enqueue e e a MESMA em toda
    # tentativa. Sai por pop (de uma copia) porque `create_order` a recebe como
    # parametro nomeado, nao como parte dos dados do pedido.
    kwargs = dict(payload)
    idempotency_key = kwargs.pop("idempotency_key", None)

    async with BlingClient() as client:
        return await create_order(client, idempotency_key=idempotency_key, **kwargs)


_HANDLERS = {"create_order": _handle_create_order}


async def drain() -> int:
    """Processa um lote de jobs pendentes. Devolve quantos foram concluidos."""
    pendentes = await asyncio.to_thread(_claim)
    concluidos = 0

    for job in pendentes:
        handler = _HANDLERS.get(job["kind"])
        if handler is None:
            await asyncio.to_thread(_update, job["id"], {
                "status": "failed",
                "last_error": f"kind desconhecido: {job['kind']}",
            })
            continue

        tentativas = int(job.get("attempts") or 0) + 1
        try:
            await handler(job.get("payload") or {}, job)
        except TRANSIENT as exc:
            if tentativas >= MAX_ATTEMPTS:
                await asyncio.to_thread(_update, job["id"], {
                    "status": "failed", "attempts": tentativas, "last_error": str(exc),
                })
                logger.error("[BLING JOBS] job %s desistiu apos %d tentativas: %s",
                             job["id"], tentativas, exc)
                continue
            atraso = _BACKOFF_MINUTES[min(tentativas - 1, len(_BACKOFF_MINUTES) - 1)]
            await asyncio.to_thread(_update, job["id"], {
                "status": "pending", "attempts": tentativas, "last_error": str(exc),
                "run_after": (_now() + timedelta(minutes=atraso)).isoformat(),
            })
        except Exception as exc:  # noqa: BLE001 — validacao e qualquer outro: nao retenta
            await asyncio.to_thread(_update, job["id"], {
                "status": "failed", "attempts": tentativas, "last_error": str(exc),
            })
            logger.error("[BLING JOBS] job %s falhou definitivamente: %s", job["id"], exc)
        else:
            # `bling_jobs` nao tem processed_at (so bling_webhook_events tem);
            # updated_at e mantido pelo trigger da migration.
            await asyncio.to_thread(_update, job["id"], {
                "status": "done", "attempts": tentativas,
            })
            concluidos += 1

    return concluidos


async def bling_jobs_tick() -> None:
    if not config.enabled():
        return
    try:
        await drain()
    except Exception as exc:  # noqa: BLE001 — worker nunca morre por causa do Bling
        logger.warning("[BLING JOBS] drain falhou: %s", exc)

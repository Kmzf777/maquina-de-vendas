import asyncio
import logging
import time

import redis.asyncio as aioredis

from app.buffer.manager import FLUSH_QUEUE_KEY
from app.buffer.processor import process_buffered_messages
from app.channels.service import get_channel_by_id as get_channel

logger = logging.getLogger(__name__)

BUFFER_FLAG_KEY = "config:buffer_enabled"

# A2 — concorrência limitada: processa vários leads vencidos em paralelo, mas com
# um teto para não afogar a rede/LLM (head-of-line blocking sob rajada).
FLUSH_CONCURRENCY = 10


async def _process_claimed(phone: str, combined: str, channel_id: str, sem: asyncio.Semaphore) -> None:
    """Processa um item já reivindicado, respeitando o limite de concorrência.

    Isola falhas: uma exceção em um lead não cancela/aborta os demais do lote.
    """
    async with sem:
        try:
            await process_buffered_messages(phone, combined, channel_id)
        except Exception as e:
            logger.error(
                f"Erro ao processar buffer de {phone} no canal {channel_id}: {e}",
                exc_info=True,
            )


async def flush_due_items(r: aioredis.Redis) -> None:
    """Process all flush_queue items whose score (flush_at) has passed.

    Uses ZREM for atomic claiming: only the worker that successfully removes
    the member processes it. Safe across multiple uvicorn workers.

    O claim (ZREM + leitura do buffer) é feito sequencialmente (rápido, só Redis),
    mas o processamento pesado (LLM/envio) roda concorrente, limitado por Semaphore.
    """
    now = time.time()
    due_members = await r.zrangebyscore(FLUSH_QUEUE_KEY, "-inf", now)

    claimed: list[tuple[str, str, str]] = []  # (phone, combined, channel_id)

    for member in due_members:
        removed = await r.zrem(FLUSH_QUEUE_KEY, member)
        if removed == 0:
            continue

        channel_id, phone = member.split(":", 1)
        buffer_key = f"buffer:{channel_id}:{phone}"
        lead_name_key = f"lead_name:{channel_id}:{phone}"

        async with r.pipeline(transaction=True) as pipe:
            pipe.lrange(buffer_key, 0, -1)
            pipe.delete(buffer_key)
            pipe.get(lead_name_key)
            results = await pipe.execute()

        raw_messages = results[0]
        if not raw_messages:
            continue

        push_name = results[2] if results[2] else None
        combined = "\n".join(raw_messages)
        logger.info(
            f"Flushing {len(raw_messages)} message(s) for {phone} on channel {channel_id}"
        )

        try:
            _ = get_channel(channel_id)  # validate channel exists before processing
        except Exception as e:
            logger.error(
                f"Channel {channel_id} not found during flush, "
                f"dropping {len(raw_messages)} message(s): {e}"
            )
            continue

        # processor expects channel_id (string), not the full channel dict.
        logger.info(f"Flushing buffered messages for {phone} (push_name={push_name})")
        claimed.append((phone, combined, channel_id))

    if not claimed:
        return

    sem = asyncio.Semaphore(FLUSH_CONCURRENCY)
    await asyncio.gather(
        *(_process_claimed(phone, combined, channel_id, sem) for phone, combined, channel_id in claimed)
    )


async def run_flusher(app) -> None:
    """Background loop started by FastAPI lifespan.

    Checks config:buffer_enabled flag each cycle.
    Runs forever until the app shuts down (asyncio.CancelledError).
    """
    redis: aioredis.Redis = app.state.redis
    logger.info("Buffer flusher started")

    while True:
        try:
            flag = await redis.get(BUFFER_FLAG_KEY)
            if flag != "0":
                await flush_due_items(redis)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Flusher loop error: {e}", exc_info=True)

        await asyncio.sleep(0.5)

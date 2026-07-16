"""Runtime do worker: um loop isolado por domínio.

- run_periodic: tick fixo; exceção do fn é logada e o loop continua.
- run_event_driven: processa, depois bloqueia em XREADGROUP até chegar evento
  (wake-up) ou estourar o fallback (varredura de segurança). ACK imediato:
  o evento não é a camada de durabilidade — o banco é (claims atômicos +
  recovery de stale). Redis fora ⇒ degrada para tick puro (comportamento antigo).
"""
import asyncio
import inspect
import logging

import redis.asyncio as aioredis
from redis import exceptions as redis_exceptions

from app.config import settings
from app.events.bus import stream_key

logger = logging.getLogger(__name__)

GROUP = "worker"
CONSUMER = "worker-main"


async def _call(fn) -> None:
    if inspect.iscoroutinefunction(fn):
        await fn()
    else:
        await asyncio.to_thread(fn)


async def run_periodic(name: str, fn, interval: float) -> None:
    logger.info("[WORKER:%s] loop periódico (%.0fs)", name, interval)
    while True:
        try:
            await _call(fn)
        except Exception:
            logger.error("[WORKER:%s] erro no tick (isolado)", name, exc_info=True)
        await asyncio.sleep(interval)


def _default_client(fallback_interval: float) -> aioredis.Redis:
    return aioredis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=2, socket_timeout=fallback_interval + 10,
    )


async def run_event_driven(
    name: str, fn, domain: str, fallback_interval: float, *, client: aioredis.Redis | None = None
) -> None:
    r = client if client is not None else _default_client(fallback_interval)
    stream = stream_key(domain)
    group_ready = False
    logger.info("[WORKER:%s] loop por evento (stream=%s, fallback=%.0fs)", name, stream, fallback_interval)
    while True:
        # Processa primeiro: cobre o startup (pendências acumuladas em restart)
        # e o pós-wake-up. A varredura decide o que fazer; o evento só acorda.
        try:
            await _call(fn)
        except Exception:
            logger.error("[WORKER:%s] erro no processamento (isolado)", name, exc_info=True)
        # Espera o próximo wake-up (evento) ou o fallback (timeout do BLOCK).
        try:
            if not group_ready:
                try:
                    await r.xgroup_create(stream, GROUP, id="$", mkstream=True)
                except redis_exceptions.ResponseError as exc:
                    if "BUSYGROUP" not in str(exc):
                        raise
                group_ready = True
            entries = await r.xreadgroup(
                GROUP, CONSUMER, {stream: ">"}, count=32, block=int(fallback_interval * 1000)
            )
            if entries:
                ids = [entry_id for _stream, items in entries for entry_id, _fields in items]
                if ids:
                    await r.xack(stream, GROUP, *ids)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            group_ready = False  # força recriar grupo/conexão na próxima volta
            logger.warning(
                "[WORKER:%s] Redis indisponível — degradando p/ tick de %.0fs: %s",
                name, fallback_interval, exc,
            )
            await asyncio.sleep(fallback_interval)

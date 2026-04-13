import asyncio
import logging
import time

import redis.asyncio as aioredis

from app.buffer.manager import FLUSH_QUEUE_KEY
from app.buffer.processor import process_buffered_messages
from app.channels.service import get_channel

logger = logging.getLogger(__name__)


async def flush_due_items(r: aioredis.Redis) -> None:
    """Process all flush_queue items whose score (flush_at) has passed.

    Uses ZREM for atomic claiming: only the worker that successfully removes
    the member processes it. Safe across multiple uvicorn workers.
    """
    now = time.time()
    due_members = await r.zrangebyscore(FLUSH_QUEUE_KEY, "-inf", now)

    for member in due_members:
        # Atomic claim: only one worker gets removed=1
        removed = await r.zrem(FLUSH_QUEUE_KEY, member)
        if removed == 0:
            continue  # Another worker claimed it first

        channel_id, phone = member.split(":", 1)
        buffer_key = f"buffer:{channel_id}:{phone}"
        lead_name_key = f"lead_name:{channel_id}:{phone}"

        # Atomic read + delete using Redis pipeline
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
            f"Flushing {len(raw_messages)} message(s) for {phone} "
            f"on channel {channel_id}"
        )

        try:
            channel = get_channel(channel_id)
        except Exception as e:
            logger.error(
                f"Channel {channel_id} not found during flush, "
                f"dropping {len(raw_messages)} message(s): {e}"
            )
            continue

        await process_buffered_messages(phone, combined, channel, push_name=push_name)


async def run_flusher(app) -> None:
    """Background loop started by FastAPI lifespan.

    Polls flush_queue every 500ms. Runs forever until the app shuts down.
    """
    redis: aioredis.Redis = app.state.redis
    logger.info("Buffer flusher started")

    while True:
        try:
            await flush_due_items(redis)
        except Exception as e:
            logger.error(f"Flusher loop error: {e}", exc_info=True)

        await asyncio.sleep(0.5)

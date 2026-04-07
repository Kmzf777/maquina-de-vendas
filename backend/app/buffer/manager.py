import logging
import time

import redis.asyncio as aioredis

from app.config import settings
from app.webhook.parser import IncomingMessage

logger = logging.getLogger(__name__)

FLUSH_QUEUE_KEY = "flush_queue"


async def push_to_buffer(r: aioredis.Redis, msg: IncomingMessage, channel: dict):
    """Push message text to Redis list and schedule flush via sorted set.

    The sorted set `flush_queue` maps `{channel_id}:{phone}` → flush_at_timestamp.
    A background worker (flusher.py) polls this set and processes due items.
    This function is safe across multiple uvicorn workers because all state
    lives exclusively in Redis.
    """
    phone = msg.from_number
    channel_id = channel["id"]
    buffer_key = f"buffer:{channel_id}:{phone}"
    member = f"{channel_id}:{phone}"

    if msg.media_id:
        text = msg.text or f"[{msg.type}: media_id={msg.media_id}]"
    elif msg.media_url:
        text = msg.text or f"[{msg.type}: media_url={msg.media_url}]"
    else:
        text = msg.text or ""

    await r.rpush(buffer_key, text)

    if msg.push_name:
        # NX: only write if key doesn't exist yet — avoids redundant writes on every message
        await r.set(f"lead_name:{channel_id}:{phone}", msg.push_name, ex=3600, nx=True)

    now = time.time()
    current_score = await r.zscore(FLUSH_QUEUE_KEY, member)

    if current_score is None:
        flush_at = now + settings.buffer_base_timeout
        await r.zadd(FLUSH_QUEUE_KEY, {member: flush_at})
        logger.info(
            f"Buffer started for {phone} on channel {channel['name']}: "
            f"flush in {settings.buffer_base_timeout}s"
        )
    else:
        new_flush_at = min(
            current_score + settings.buffer_extend_timeout,
            now + settings.buffer_max_timeout,
        )
        if new_flush_at > current_score:
            await r.zadd(FLUSH_QUEUE_KEY, {member: new_flush_at}, xx=True)
            logger.info(
                f"Buffer extended for {phone} on channel {channel['name']}"
            )

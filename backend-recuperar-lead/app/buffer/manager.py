import asyncio
import logging

import redis.asyncio as aioredis

from app.config import settings
from app.webhook.parser import IncomingMessage

logger = logging.getLogger(__name__)

# Track active timers per phone number
_active_timers: dict[str, asyncio.Task] = {}


async def push_to_buffer(r: aioredis.Redis, msg: IncomingMessage):
    """Push a message to the buffer (or process immediately if buffer is off)."""
    from app.buffer.processor import process_buffered_messages

    phone = msg.from_number
    channel_id = msg.channel_id or ""

    # Determine text content (will be resolved later for media)
    if msg.text:
        text = msg.text
    elif msg.media_url:
        text = f"[{msg.type}: media_url={msg.media_url}]"
    else:
        text = f"[{msg.type}: sem conteudo]"

    # Save push_name for later use
    if msg.push_name:
        await r.set(f"pushname:{phone}", msg.push_name, ex=86400)

    # Save channel_id for this phone (used when flushing buffer)
    if channel_id:
        await r.set(f"channel:{phone}", channel_id, ex=86400)

    # Check if buffer is enabled
    buffer_enabled = await r.get("config:buffer_enabled")
    if buffer_enabled == "0":
        logger.info(f"Buffer OFF — processing immediately for {phone}")
        await process_buffered_messages(phone, text, channel_id)
        return

    buffer_key = f"buffer:{phone}"
    lock_key = f"buffer:{phone}:lock"

    # Push message to the list
    await r.rpush(buffer_key, text)

    # Check if timer is already active
    has_lock = await r.exists(lock_key)

    if has_lock:
        # Timer already running — extend it
        current_ttl = await r.ttl(lock_key)
        new_ttl = min(
            current_ttl + settings.buffer_extend_timeout,
            settings.buffer_max_timeout,
        )
        await r.expire(lock_key, new_ttl)
        logger.info(f"Buffer extended for {phone}: TTL now {new_ttl}s")
    else:
        # First message — set lock and start timer
        await r.set(lock_key, "1", ex=settings.buffer_base_timeout)
        logger.info(f"Buffer started for {phone}: {settings.buffer_base_timeout}s")

        # Start async timer
        if phone in _active_timers:
            _active_timers[phone].cancel()

        _active_timers[phone] = asyncio.create_task(
            _wait_and_flush(r, phone)
        )


async def _wait_and_flush(r: aioredis.Redis, phone: str):
    """Wait for the buffer to expire, then flush."""
    from app.buffer.processor import process_buffered_messages

    while True:
        await asyncio.sleep(1)
        lock_key = f"buffer:{phone}:lock"
        exists = await r.exists(lock_key)
        if not exists:
            break

    buffer_key = f"buffer:{phone}"

    # Get all messages
    messages = await r.lrange(buffer_key, 0, -1)
    await r.delete(buffer_key)

    # Clean up timer reference
    _active_timers.pop(phone, None)

    if messages:
        combined = "\n".join(messages)
        logger.info(f"Buffer flushed for {phone}: {len(messages)} messages")
        # Get channel_id stored for this phone
        channel_id = await r.get(f"channel:{phone}") or ""
        await process_buffered_messages(phone, combined, channel_id)

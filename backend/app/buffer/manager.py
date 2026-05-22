import asyncio
import base64
import json
import logging
import time

import redis.asyncio as aioredis

FLUSH_QUEUE_KEY = "flush_queue"

from app.config import settings
from app.leads.service import normalize_phone
from app.webhook.parser import IncomingMessage

logger = logging.getLogger(__name__)

# Track active timers per phone number
_active_timers: dict[str, asyncio.Task] = {}


async def push_to_buffer(r: aioredis.Redis, msg: IncomingMessage):
    """Push a message to the buffer (or process immediately if buffer is off)."""
    from app.buffer.processor import process_buffered_messages

    phone = normalize_phone(msg.from_number)
    channel_id = msg.channel_id or ""

    # Determine text content (will be resolved later for media)
    _MEDIA_TYPES = ("image", "video", "audio", "document", "sticker")
    _META_TYPES = ("location", "contact", "reaction")
    if msg.media_url and msg.type in _MEDIA_TYPES:
        if msg.type == "document" and msg.document_name:
            fname_b64 = base64.b64encode(msg.document_name.encode()).decode()
            placeholder = f"[{msg.type}: media_url={msg.media_url} filename_b64={fname_b64}]"
        else:
            placeholder = f"[{msg.type}: media_url={msg.media_url}]"
        text = f"{msg.text}\n{placeholder}" if msg.text else placeholder
    elif msg.metadata and msg.type in _META_TYPES:
        meta_b64 = base64.b64encode(json.dumps(msg.metadata).encode()).decode()
        text = f"[{msg.type}: meta_b64={meta_b64}]"
    elif msg.text:
        text = msg.text
    else:
        text = f"[{msg.type}: sem conteudo]"

    # Save push_name for later use
    if msg.push_name:
        await r.set(f"pushname:{phone}", msg.push_name, ex=86400)

    # Check if buffer is enabled
    buffer_enabled = await r.get("config:buffer_enabled")
    if buffer_enabled == "0":
        logger.info(f"Buffer OFF — processing immediately for {phone}")
        await process_buffered_messages(phone, text, channel_id)
        return

    # Buffer is keyed per phone+channel so messages from different channels
    # never share a timer or get flushed under the wrong channel's mode.
    buf_key = f"buffer:{phone}:{channel_id}"
    lock_key = f"buffer:{phone}:{channel_id}:lock"
    deadline_key = f"buffer:{phone}:{channel_id}:deadline"
    timer_key = f"{phone}:{channel_id}"

    # Push message to the list
    await r.rpush(buf_key, text)

    # Check if timer is already active
    has_lock = await r.exists(lock_key)

    if has_lock:
        # Timer already running — extend it, but never beyond the absolute deadline
        current_ttl = await r.ttl(lock_key)
        deadline_raw = await r.get(deadline_key)
        remaining = max(1, float(deadline_raw) - time.time()) if deadline_raw else settings.buffer_max_timeout
        new_ttl = min(
            current_ttl + settings.buffer_extend_timeout,
            int(remaining),
        )
        await r.expire(lock_key, new_ttl)
        logger.info(f"Buffer extended for {phone}: TTL now {new_ttl}s (deadline in {remaining:.1f}s)")
    else:
        # First message — record absolute deadline, set lock, start timer
        flush_at = time.time() + settings.buffer_max_timeout
        await r.set(deadline_key, str(flush_at), ex=settings.buffer_max_timeout + 5)
        await r.set(lock_key, "1", ex=settings.buffer_base_timeout)
        logger.info(f"Buffer started for {phone}: {settings.buffer_base_timeout}s (deadline in {settings.buffer_max_timeout}s)")

        # Start async timer
        if timer_key in _active_timers:
            _active_timers[timer_key].cancel()

        _active_timers[timer_key] = asyncio.create_task(
            _wait_and_flush(r, phone, channel_id)
        )


async def _wait_and_flush(r: aioredis.Redis, phone: str, channel_id: str):
    """Wait for the buffer to expire, then flush."""
    from app.buffer.processor import process_buffered_messages

    lock_key = f"buffer:{phone}:{channel_id}:lock"
    buf_key = f"buffer:{phone}:{channel_id}"
    timer_key = f"{phone}:{channel_id}"

    while True:
        await asyncio.sleep(1)
        exists = await r.exists(lock_key)
        if not exists:
            break

    # Get all messages
    messages = await r.lrange(buf_key, 0, -1)
    await r.delete(buf_key)

    # Clean up timer reference
    _active_timers.pop(timer_key, None)

    if messages:
        combined = "\n".join(messages)
        logger.info(f"Buffer flushed for {phone}: {len(messages)} messages")
        await process_buffered_messages(phone, combined, channel_id)

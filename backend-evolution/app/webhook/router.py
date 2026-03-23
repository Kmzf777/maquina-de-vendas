import logging

from fastapi import APIRouter, Request

from app.webhook.parser import parse_webhook_payload
from app.whatsapp.client import mark_read
from app.buffer.manager import push_to_buffer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()

    logger.info(f"Webhook event: {payload.get('event', 'unknown')}")

    messages = parse_webhook_payload(payload)

    for msg in messages:
        logger.info(f"Message from {msg.from_number} ({msg.push_name}): type={msg.type}, text={msg.text[:50] if msg.text else 'N/A'}")

        # Mark as read
        try:
            await mark_read(msg.message_id, msg.remote_jid)
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        # Push to buffer for processing
        redis = request.app.state.redis
        await push_to_buffer(redis, msg)

    return {"status": "ok"}

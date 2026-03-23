import logging

from fastapi import APIRouter, Request, Query, Response

from app.config import settings
from app.webhook.parser import parse_webhook_payload
from app.whatsapp.client import mark_read
from app.buffer.manager import push_to_buffer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)


@router.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    messages = parse_webhook_payload(payload)

    for msg in messages:
        logger.info(f"Message from {msg.from_number}: type={msg.type}")

        # Mark as read immediately
        try:
            await mark_read(msg.message_id)
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        # Push to buffer for processing
        redis = request.app.state.redis
        await push_to_buffer(redis, msg)

    return {"status": "ok"}

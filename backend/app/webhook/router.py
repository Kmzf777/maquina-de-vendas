import logging

from fastapi import APIRouter, Request, Query, Response

from app.webhook.parser import parse_meta_webhook, parse_evolution_webhook
from app.channels.service import get_channel, get_channel_by_provider_config
from app.providers.registry import get_provider
from app.buffer.manager import push_to_buffer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/webhook/meta")
async def verify_meta_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification. Checks verify_token against all meta_cloud channels."""
    if hub_mode != "subscribe":
        return Response(status_code=403)

    from app.db.supabase import get_supabase
    sb = get_supabase()
    channels = sb.table("channels").select("*").eq("provider", "meta_cloud").execute().data

    for ch in channels:
        config = ch.get("provider_config", {})
        if config.get("verify_token") == hub_verify_token:
            return Response(content=hub_challenge, media_type="text/plain")

    return Response(status_code=403)


@router.post("/webhook/meta")
async def receive_meta_webhook(request: Request):
    """Receive messages from Meta Cloud API. Resolves channel by phone_number_id."""
    payload = await request.json()
    messages, phone_number_id = parse_meta_webhook(payload)

    if not messages or not phone_number_id:
        return {"status": "ok"}

    channel = get_channel_by_provider_config("phone_number_id", phone_number_id)
    if not channel:
        logger.warning(f"No channel found for phone_number_id={phone_number_id}")
        return {"status": "ok"}

    if not channel.get("is_active"):
        logger.info(f"Channel {channel['name']} is inactive, ignoring message")
        return {"status": "ok"}

    provider = get_provider(channel)

    for msg in messages:
        msg.channel_id = channel["id"]
        logger.info(f"[Meta] Message from {msg.from_number} on channel {channel['name']}: type={msg.type}")

        try:
            await provider.mark_read(msg.message_id)
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        redis = request.app.state.redis
        await push_to_buffer(redis, msg, channel)

    return {"status": "ok"}


@router.post("/webhook/evolution/{channel_id}")
async def receive_evolution_webhook(channel_id: str, request: Request):
    """Receive messages from Evolution API. Channel identified by URL path."""
    payload = await request.json()
    messages = parse_evolution_webhook(payload)

    if not messages:
        return {"status": "ok"}

    try:
        channel = get_channel(channel_id)
    except Exception:
        logger.warning(f"No channel found for id={channel_id}")
        return {"status": "ok"}

    if not channel.get("is_active"):
        logger.info(f"Channel {channel['name']} is inactive, ignoring message")
        return {"status": "ok"}

    provider = get_provider(channel)

    for msg in messages:
        msg.channel_id = channel_id
        logger.info(f"[Evolution] Message from {msg.from_number} on channel {channel['name']}: type={msg.type}")

        try:
            await provider.mark_read(msg.message_id, remote_jid=msg.remote_jid or "")
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        redis = request.app.state.redis
        await push_to_buffer(redis, msg, channel)

    return {"status": "ok"}

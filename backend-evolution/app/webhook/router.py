import logging

from fastapi import APIRouter, Request

from app.webhook.parser import parse_webhook_payload
from app.whatsapp.factory import get_whatsapp_client
from app.buffer.manager import push_to_buffer
from app.leads.service import get_or_create_lead, reset_lead
from app.channels.service import get_channel_by_provider_config

logger = logging.getLogger(__name__)

router = APIRouter()


def _find_evolution_channel(payload: dict) -> dict | None:
    """Find the Evolution channel from the webhook payload.

    Evolution API v2 sends instance info at the top level of the payload:
    { "instance": { "instanceName": "xxx" }, "event": "messages.upsert", ... }
    """
    instance_name = ""
    instance_data = payload.get("instance")
    if isinstance(instance_data, dict):
        instance_name = instance_data.get("instanceName", "")
    elif isinstance(instance_data, str):
        instance_name = instance_data

    if not instance_name:
        # Try alternative payload structures
        instance_name = payload.get("instanceName", "")

    if instance_name:
        channel = get_channel_by_provider_config("instance", instance_name, "evolution")
        if channel:
            return channel

    logger.warning(f"No Evolution channel found for instance={instance_name}")
    return None


@router.post("/webhook/evolution")
async def receive_evolution_webhook(request: Request):
    payload = await request.json()
    logger.info(f"Evolution webhook event: {payload.get('event', 'unknown')}")

    # Find channel by instance name (the reliable identifier)
    channel = _find_evolution_channel(payload)
    if not channel:
        return {"status": "ok"}

    if not channel.get("is_active"):
        logger.info(f"Channel {channel['id']} is inactive, skipping")
        return {"status": "ok"}

    messages = parse_webhook_payload(payload)

    for msg in messages:
        logger.info(f"Message from {msg.from_number} ({msg.push_name}): type={msg.type}")

        # Set channel_id on message
        msg.channel_id = channel["id"]

        # Mark as read
        try:
            wa_client = get_whatsapp_client(channel)
            await wa_client.mark_read(msg.message_id, msg.remote_jid)
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        # Handle !resetar command
        if msg.text and msg.text.strip().lower() == "!resetar":
            try:
                lead = get_or_create_lead(msg.from_number)
                reset_lead(lead["id"])
                wa_client = get_whatsapp_client(channel)
                await wa_client.send_text(msg.from_number, "Memoria resetada! Pode comecar uma nova conversa do zero.")
            except Exception as e:
                logger.error(f"Failed to reset lead: {e}", exc_info=True)
            continue

        # Push to buffer
        redis = request.app.state.redis
        await push_to_buffer(redis, msg)

    return {"status": "ok"}


# Keep old /webhook endpoint for backward compatibility
@router.post("/webhook")
async def receive_webhook_legacy(request: Request):
    return await receive_evolution_webhook(request)

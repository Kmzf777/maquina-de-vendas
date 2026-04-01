import logging

from fastapi import APIRouter, Request

from app.webhook.parser import parse_webhook_payload
from app.whatsapp.factory import get_whatsapp_client
from app.buffer.manager import push_to_buffer
from app.leads.service import get_or_create_lead, reset_lead
from app.channels.service import get_channel_by_phone, get_channel_by_provider_config

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook/evolution")
async def receive_evolution_webhook(request: Request):
    payload = await request.json()
    logger.info(f"Evolution webhook event: {payload.get('event', 'unknown')}")

    messages = parse_webhook_payload(payload)

    for msg in messages:
        logger.info(f"Message from {msg.from_number} ({msg.push_name}): type={msg.type}")

        # Find the channel this message belongs to
        channel = get_channel_by_phone(msg.from_number, "evolution")
        if not channel:
            # Try to find by instance name from the webhook payload
            instance = payload.get("instance", {}).get("instanceName", "")
            if instance:
                channel = get_channel_by_provider_config("instance", instance, "evolution")

        if not channel:
            logger.warning(f"No active Evolution channel found for {msg.from_number}")
            continue

        if not channel.get("is_active"):
            logger.info(f"Channel {channel['id']} is inactive, skipping")
            continue

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


# Keep old /webhook endpoint for backward compatibility during transition
@router.post("/webhook")
async def receive_webhook_legacy(request: Request):
    return await receive_evolution_webhook(request)

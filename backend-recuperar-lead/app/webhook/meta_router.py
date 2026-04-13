import hashlib
import hmac
import logging

from fastapi import APIRouter, Request, Response

from app.webhook.meta_parser import parse_meta_webhook_payload, extract_phone_number_id
# TODO: migrate to app.providers.registry.get_provider (matching production pattern)
from app.whatsapp.factory import get_whatsapp_client
from app.buffer.manager import push_to_buffer
from app.leads.service import get_or_create_lead, reset_lead
from app.channels.service import get_channel_by_provider_config

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_signature(payload_bytes: bytes, signature_header: str, app_secret: str) -> bool:
    """Verify Meta webhook HMAC-SHA256 signature."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header[7:]  # strip "sha256=" prefix
    computed = hmac.new(app_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, expected)


@router.get("/webhook/meta")
async def verify_meta_webhook(request: Request):
    """Meta webhook verification challenge."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode != "subscribe" or not token or not challenge:
        return Response(status_code=403)

    # Find a channel with this verify_token
    channel = get_channel_by_provider_config("verify_token", token, "meta_cloud")
    if not channel:
        logger.warning(f"Meta verify: no channel found with verify_token={token}")
        return Response(status_code=403)

    logger.info(f"Meta webhook verified for channel {channel['id']}")
    return Response(content=challenge, media_type="text/plain")


@router.post("/webhook/meta")
async def receive_meta_webhook(request: Request):
    """Receive incoming WhatsApp messages from Meta Cloud API."""
    payload_bytes = await request.body()
    payload = await request.json()

    # Extract phone_number_id to identify the channel
    phone_number_id = extract_phone_number_id(payload)
    if not phone_number_id:
        logger.warning("Meta webhook: no phone_number_id found in payload")
        return {"status": "ok"}

    channel = get_channel_by_provider_config("phone_number_id", phone_number_id, "meta_cloud")
    if not channel:
        logger.warning(f"No active Meta channel for phone_number_id={phone_number_id}")
        return {"status": "ok"}

    if not channel.get("is_active"):
        logger.info(f"Channel {channel['id']} is inactive, skipping")
        return {"status": "ok"}

    # Verify signature
    signature = request.headers.get("x-hub-signature-256", "")
    app_secret = channel.get("provider_config", {}).get("app_secret", "")
    if app_secret and not _verify_signature(payload_bytes, signature, app_secret):
        logger.warning(f"Meta webhook: invalid signature for channel {channel['id']}")
        return Response(status_code=403)

    # Parse messages
    messages = parse_meta_webhook_payload(payload)

    for msg in messages:
        logger.info(f"Meta message from {msg.from_number}: type={msg.type}")
        msg.channel_id = channel["id"]

        # Mark as read
        try:
            wa_client = get_whatsapp_client(channel)
            await wa_client.mark_read(msg.message_id)
        except Exception as e:
            logger.warning(f"Failed to mark read via Meta: {e}")

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

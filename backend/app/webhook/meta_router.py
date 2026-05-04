import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.webhook.meta_parser import parse_meta_webhook_payload, extract_phone_number_id
from app.whatsapp.registry import get_provider
from app.buffer.manager import push_to_buffer
from app.leads.service import get_or_create_lead, normalize_phone, reset_lead
from app.channels.service import get_channel_by_provider_config
from app.dev_router.service import get_dev_route
from app.dev_router.forwarder import forward_to_dev
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def _track_inbound_message_time(phone: str) -> None:
    """Update last_customer_message_at so the 24h window status stays current."""
    normalized = normalize_phone(phone)
    try:
        sb = get_supabase()
        sb.table("leads").update(
            {"last_customer_message_at": datetime.now(timezone.utc).isoformat()}
        ).eq("phone", normalized).execute()
    except Exception as e:
        logger.warning(f"Failed to update last_customer_message_at for {normalized}: {e}")

    # Cancela follow-ups pendentes pois cliente respondeu
    try:
        from app.follow_up.service import cancel_followups_by_phone
        normalized_for_cancel = normalize_phone(phone)
        cancel_followups_by_phone(normalized_for_cancel, reason="client_replied")
    except Exception as e:
        logger.warning(f"[FOLLOWUP] Failed to cancel follow-ups for {phone}: {e}")


def _log_webhook(
    channel_id: str | None,
    phone_number_id: str | None,
    from_number: str | None,
    payload: dict,
    message_count: int,
) -> None:
    """Persists raw Meta webhook payload to Supabase for audit/debugging. Fire-and-forget."""
    try:
        sb = get_supabase()
        sb.table("meta_webhook_logs").insert({
            "channel_id": channel_id,
            "phone_number_id": phone_number_id,
            "from_number": from_number,
            "payload": payload,
            "message_count": message_count,
        }).execute()
    except Exception as e:
        logger.warning(
            f"[META LOG] Failed to persist webhook log channel={channel_id} from={from_number}: {e}"
        )


router = APIRouter()


def _extract_from_number(payload: dict) -> str | None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                from_number = msg.get("from")
                if from_number:
                    return from_number
    return None


def _verify_signature(payload_bytes: bytes, signature_header: str, app_secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header[7:]
    computed = hmac.new(app_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, expected)


@router.get("/webhook/meta")
async def verify_meta_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode != "subscribe" or not token or not challenge:
        return Response(status_code=403)

    channel = get_channel_by_provider_config("verify_token", token, "meta_cloud")
    if not channel:
        logger.warning(f"Meta verify: no channel found with verify_token={token}")
        return Response(status_code=403)

    logger.info(f"Meta webhook verified for channel {channel['id']}")
    return Response(content=challenge, media_type="text/plain")


@router.post("/webhook/meta")
async def receive_meta_webhook(request: Request, background_tasks: BackgroundTasks):
    payload_bytes = await request.body()
    payload = json.loads(payload_bytes)

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

    signature = request.headers.get("x-hub-signature-256", "")
    app_secret = channel.get("provider_config", {}).get("app_secret", "")
    if app_secret and not _verify_signature(payload_bytes, signature, app_secret):
        logger.warning(f"Meta webhook: invalid signature for channel {channel['id']}")
        return Response(status_code=403)

    redis = request.app.state.redis

    # Dev routing happens on the raw payload before parsing so that ALL message
    # types (including 'button', future types) are forwarded to dev correctly.
    if request.headers.get("x-dev-routed") != "1":
        from_number = _extract_from_number(payload)
        if from_number:
            dev_url = await get_dev_route(redis, from_number)
            if dev_url:
                logger.info(f"Dev routing: forwarding Meta {from_number} to {dev_url}")
                background_tasks.add_task(
                    forward_to_dev,
                    dev_url=dev_url,
                    path="/webhook/meta",
                    headers=dict(request.headers),
                    body=payload_bytes,
                )
                return {"status": "ok"}

    messages = parse_meta_webhook_payload(payload)

    background_tasks.add_task(
        _log_webhook,
        channel_id=channel["id"],
        phone_number_id=phone_number_id,
        from_number=_extract_from_number(payload),
        payload=payload,
        message_count=len(messages),
    )

    for msg in messages:
        logger.info(f"Meta message from {msg.from_number}: type={msg.type}")
        msg.channel_id = channel["id"]

        try:
            provider = get_provider(channel)
            await provider.mark_read(msg.message_id)
        except Exception as e:
            logger.warning(f"Failed to mark read via Meta: {e}")

        if msg.text and msg.text.strip().lower() == "!resetar":
            try:
                lead = get_or_create_lead(msg.from_number)
                reset_lead(lead["id"])
                provider = get_provider(channel)
                await provider.send_text(msg.from_number, "Memoria resetada! Pode comecar uma nova conversa do zero.")
            except Exception as e:
                logger.error(f"Failed to reset lead: {e}", exc_info=True)
            continue

        background_tasks.add_task(_track_inbound_message_time, msg.from_number)
        await push_to_buffer(redis, msg)

    return {"status": "ok"}

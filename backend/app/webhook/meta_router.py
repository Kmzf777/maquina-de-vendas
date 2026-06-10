import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.webhook.meta_parser import parse_meta_webhook_payload, extract_phone_number_id
from app.whatsapp.registry import get_provider
from app.buffer.manager import push_to_buffer
from app.leads.service import get_or_create_lead, normalize_phone, reset_lead, purge_dev_lead
from app.channels.service import get_channel_by_provider_config
from app.dev_router.service import get_dev_route, is_dev_number
from app.dev_router.forwarder import forward_to_dev
from app.db.supabase import get_supabase
from app.meta_audit import log_inbound

logger = logging.getLogger(__name__)


def _register_lead(from_number: str, push_name: str | None) -> None:
    """Ensure the lead exists in the CRM the moment they contact us.

    Called as a BackgroundTask so it never delays the webhook response.
    Runs before the buffer flushes, guaranteeing CRM registration even if
    the buffer fails (e.g. backend restart during buffering).
    """
    try:
        get_or_create_lead(from_number, name=push_name, channel="whatsapp")
    except Exception as exc:
        logger.warning("Failed to register lead for %s: %s", from_number, exc)


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




router = APIRouter()


def _extract_from_number(payload: dict) -> str | None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                from_number = msg.get("from")
                if from_number:
                    return from_number
    return None


def _extract_statuses(payload: dict) -> list[dict]:
    """Extract all status events from a Meta webhook payload."""
    statuses = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            statuses.extend(change.get("value", {}).get("statuses", []))
    return statuses


async def _handle_delivery_status(wamid: str, status: str, errors: list | None = None) -> None:
    """Handle Meta delivery status events: updates messages.delivery_status and broadcast counters."""
    if status not in ("sent", "delivered", "read", "failed"):
        return
    try:
        sb = get_supabase()
        sb.table("messages").update({"delivery_status": status}).eq("wamid", wamid).execute()
    except Exception as e:
        logger.warning("[DELIVERY] Failed to update message delivery_status for wamid=%s: %s", wamid, e)

    if status == "delivered":
        try:
            from app.broadcast.service import find_broadcast_lead_by_wamid, mark_broadcast_lead_delivered, increment_broadcast_delivered
            bl = find_broadcast_lead_by_wamid(wamid)
            if not bl:
                return
            # mark_broadcast_lead_delivered is atomic: updates only when delivered_at IS NULL.
            # Returns True if the row was actually updated (first delivery), False if duplicate.
            if mark_broadcast_lead_delivered(bl["id"]):
                increment_broadcast_delivered(bl["broadcast_id"])
                logger.info("[DELIVERY] wamid=%s broadcast_lead=%s delivered", wamid, bl["id"])
            else:
                logger.info("[DELIVERY] wamid=%s duplicate webhook — already counted", wamid)
        except Exception as e:
            logger.warning("[DELIVERY] Failed to process broadcast delivery for wamid=%s: %s", wamid, e)

    elif status == "failed":
        try:
            from app.broadcast.service import find_broadcast_lead_by_wamid, mark_broadcast_lead_failed, increment_broadcast_failed
            bl = find_broadcast_lead_by_wamid(wamid)
            if not bl:
                return
            error_codes = [err.get("code") for err in (errors or [])]
            error_msg = "; ".join(err.get("title", str(err.get("code", ""))) for err in (errors or [])) or "failed"
            mark_broadcast_lead_failed(bl["id"], error_msg)
            increment_broadcast_failed(bl["broadcast_id"])
            logger.warning("[DELIVERY] wamid=%s broadcast_lead=%s FAILED — %s", wamid, bl["id"], error_msg)

            # Remove conversation if the lead never replied (only broadcast messages present).
            # Avoids polluting /conversas with conversations the lead never received.
            try:
                msg_result = sb.table("messages").select("id, conversation_id").eq("wamid", wamid).limit(1).execute()
                if msg_result.data:
                    conv_id = msg_result.data[0].get("conversation_id")
                    if conv_id:
                        user_msgs = sb.table("messages").select("id", count="exact").eq("conversation_id", conv_id).eq("role", "user").execute()
                        if not (user_msgs.count or 0):
                            sb.table("conversations").delete().eq("id", conv_id).execute()
                            logger.info("[DELIVERY] Removed conversation %s — lead never replied, failed broadcast wamid=%s", conv_id, wamid)
            except Exception as cleanup_exc:
                logger.warning("[DELIVERY] Failed to clean up conversation for wamid=%s: %s", wamid, cleanup_exc)

            if 131042 in error_codes:
                from app.alerts.service import fire_billing_alert
                await fire_billing_alert(errors or [])
        except Exception as e:
            logger.warning("[DELIVERY] Failed to process broadcast failure for wamid=%s: %s", wamid, e)


def _extract_template_events(payload: dict) -> list[dict]:
    """Extract Meta template status update events (field: message_template_status_update)."""
    events = []
    for entry in payload.get("entry", []):
        waba_id = entry.get("id", "")
        for change in entry.get("changes", []):
            if change.get("field") == "message_template_status_update":
                value = change.get("value", {})
                events.append({
                    "waba_id": waba_id,
                    "event": value.get("event", ""),
                    "template_id": str(value.get("message_template_id", "")),
                    "template_name": value.get("message_template_name"),
                    "reason": value.get("reason"),
                })
    return events


def _handle_template_status_events(events: list[dict], raw_payload: dict, channel_id: str | None) -> None:
    """Update message_templates.status and log the event to meta_webhook_logs."""
    STATUS_MAP = {
        "APPROVED": "approved",
        "REJECTED": "rejected",
        "DISABLED": "rejected",
        "FLAGGED": "rejected",
        "PENDING_DELETION": "cancelled",
    }
    sb = get_supabase()
    for event in events:
        event_type = event.get("event", "")
        new_status = STATUS_MAP.get(event_type)
        if not new_status:
            logger.info("[TEMPLATE] Unhandled event type: %s", event_type)
            continue

        template_id = event.get("template_id")
        template_name = event.get("template_name")
        try:
            updated = False
            if template_id:
                res = (
                    sb.table("message_templates")
                    .update({"status": new_status})
                    .eq("meta_template_id", template_id)
                    .execute()
                )
                if res.data:
                    updated = True
            if not updated and template_name:
                sb.table("message_templates").update({"status": new_status}).eq("name", template_name).execute()

            logger.info(
                "[TEMPLATE] %s → status=%s (id=%s name=%s reason=%s)",
                event_type, new_status, template_id, template_name, event.get("reason"),
            )
        except Exception as exc:
            logger.error("[TEMPLATE] Failed to update status for id=%s: %s", template_id, exc)

    log_inbound(
        channel_id=channel_id,
        phone_number_id=None,
        from_number=None,
        payload=raw_payload,
        message_count=0,
    )


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
    is_dev_routed = request.headers.get("x-dev-routed") == "1"
    logger.info(
        "[WEBHOOK] POST /webhook/meta received — size=%d bytes, x-dev-routed=%s",
        len(payload_bytes),
        is_dev_routed,
    )
    payload = json.loads(payload_bytes)

    # Template status events use a different payload structure (no phone_number_id).
    # Intercept them before the early-return that would silently discard them.
    template_events = _extract_template_events(payload)
    if template_events:
        waba_id = template_events[0].get("waba_id") if template_events else None
        channel = get_channel_by_provider_config("waba_id", waba_id, "meta_cloud") if waba_id else None
        if channel:
            app_secret = channel.get("provider_config", {}).get("app_secret", "")
            signature = request.headers.get("x-hub-signature-256", "")
            if app_secret and not _verify_signature(payload_bytes, signature, app_secret):
                logger.warning("[TEMPLATE] Invalid signature for waba_id=%s", waba_id)
                return Response(status_code=403)
        background_tasks.add_task(
            _handle_template_status_events,
            template_events,
            payload,
            channel["id"] if channel else None,
        )
        return {"status": "ok"}

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
    rehearsal_mode = os.environ.get("REHEARSAL_MODE") == "true"
    if app_secret and not rehearsal_mode and not _verify_signature(payload_bytes, signature, app_secret):
        logger.warning(f"Meta webhook: invalid signature for channel {channel['id']}")
        return Response(status_code=403)

    redis = request.app.state.redis

    # Dev routing on raw payload — before parsing so ALL message types are caught.
    # On production (IS_DEV_ENV != "true"): if from_number is in dev whitelist → forward
    # to dev backend (best effort) and drop immediately with 200.
    # On dev server (IS_DEV_ENV=true): skip entirely — we ARE the dev server.
    if request.headers.get("x-dev-routed") != "1" and os.environ.get("IS_DEV_ENV") != "true":
        from_number = _extract_from_number(payload)
        if not from_number:
            # Delivery/read receipts have no messages[].from — check recipient_id in statuses
            statuses = _extract_statuses(payload)
            if statuses:
                from_number = statuses[0].get("recipient_id")
        if from_number:
            dev_url = await get_dev_route(redis, from_number)
            logger.info(
                "[DEV-ROUTER] from_number=%s → dev_url=%s",
                from_number,
                dev_url or "NOT_IN_WHITELIST",
            )
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
            elif await is_dev_number(redis, from_number):
                # Number is in whitelist but URL is empty — still drop in production.
                logger.warning(
                    "[DEV-ROUTER] %s in dev whitelist but no URL configured — dropping in production",
                    from_number,
                )
                return {"status": "ok"}

    messages = parse_meta_webhook_payload(payload)

    background_tasks.add_task(
        log_inbound,
        channel_id=channel["id"],
        phone_number_id=phone_number_id,
        from_number=_extract_from_number(payload),
        payload=payload,
        message_count=len(messages),
    )

    # Process delivery receipts — updates broadcasts.delivered/failed counters
    for status_event in _extract_statuses(payload):
        wamid = status_event.get("id")
        status = status_event.get("status")
        errors = status_event.get("errors") or []
        if wamid and status:
            background_tasks.add_task(_handle_delivery_status, wamid, status, errors)

    for msg in messages:
        logger.info(f"Meta message from {msg.from_number}: type={msg.type}")
        msg.channel_id = channel["id"]

        # Register lead immediately — guarantees CRM entry before buffer flushes
        background_tasks.add_task(_register_lead, msg.from_number, msg.push_name)

        try:
            provider = get_provider(channel)
            await provider.mark_read(msg.message_id)
        except Exception as e:
            logger.warning(f"Failed to mark read via Meta: {e}")

        if msg.text and msg.text.strip().lower() == "!resetar":
            try:
                result = purge_dev_lead(msg.from_number)
                provider = get_provider(channel)
                if result.get("purged"):
                    await provider.send_text(msg.from_number, "Lead removido completamente do CRM. Pode comecar do zero.")
                else:
                    await provider.send_text(msg.from_number, f"Nada a remover: {result.get('reason', 'lead nao encontrado')}.")
            except ValueError:
                logger.warning("[RESET] !resetar ignorado: numero %s nao esta na whitelist de dev", msg.from_number)
            except Exception as e:
                logger.error(f"Failed to purge lead: {e}", exc_info=True)
            continue

        background_tasks.add_task(_track_inbound_message_time, msg.from_number)
        await push_to_buffer(redis, msg)

    return {"status": "ok"}

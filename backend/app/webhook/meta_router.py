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
from app.leads.service import get_or_create_lead, normalize_phone, reset_lead, purge_dev_lead, update_lead, is_bsuid
from app.channels.service import get_channel_by_provider_config
from app.dev_router.service import get_dev_route, is_dev_number
from app.dev_router.forwarder import forward_to_dev
from app.db.supabase import get_supabase, run_with_retry
from app.meta_audit import log_inbound

logger = logging.getLogger(__name__)

WAMID_DEDUP_TTL_SECS = 86400  # 24h


async def _mark_read_bg(channel: dict, message_id: str) -> None:
    """Call Meta mark-as-read in the background so it never delays the 200 response."""
    try:
        provider = get_provider(channel)
        await provider.mark_read(message_id)
    except Exception as e:
        logger.warning("Failed to mark read via Meta: %s", e)


def _register_lead(
    from_number: str,
    push_name: str | None,
    ctwa_clid: str | None = None,
    ctwa_origem: str | None = None,
    bsuid: str | None = None,
) -> None:
    """Ensure the lead exists in the CRM the moment they contact us (BackgroundTask).

    Passa o `bsuid` (Business-Scoped User ID) para o get_or_create_lead: numa mensagem
    só-BSUID (adotante de username, sem telefone) o lead é criado/achado pela coluna bsuid;
    numa mensagem com telefone, o bsuid é carimbado no lead (merge) para reencontrá-lo caso
    o usuário passe a omitir o telefone depois.

    Também captura o `wa_id` REAL: `from_number` é o `messages[].from` cru da Meta —
    o endereço que a Meta de fato entrega. Guardamos no lead para usar como destino de
    envio (evita 131026 em números BR sem o 9º dígito). A identidade do lead continua
    pelo phone normalizado; o wa_id é só o endereço de entrega.

    Atribuição CTWA: quando a mensagem vem de um anúncio Meta Ads (Click-to-WhatsApp),
    o `ctwa_clid` é persistido no lead — na criação (first-touch, via get_or_create_lead)
    e atualizado quando um novo clique chega (last-touch). Mensagens orgânicas trazem
    ctwa_clid=None e NUNCA sobrescrevem um clid já capturado. Base p/ disparos via CAPI.
    """
    try:
        lead = get_or_create_lead(
            from_number, name=push_name, channel="whatsapp", ctwa_clid=ctwa_clid, bsuid=bsuid
        )
    except Exception as exc:
        logger.warning("Failed to register lead for %s/%s: %s", from_number, bsuid, exc)
        return
    try:
        if lead and from_number and not is_bsuid(from_number) and lead.get("wa_id") != from_number:
            update_lead(lead["id"], wa_id=from_number)
    except Exception as exc:
        logger.warning("Failed to capture wa_id=%s for lead %s: %s", from_number, lead.get("id"), exc)
    try:
        if lead and ctwa_clid and lead.get("ctwa_clid") != ctwa_clid:
            update_lead(lead["id"], ctwa_clid=ctwa_clid, traffic_type="paid")
    except Exception as exc:
        logger.warning("Failed to capture ctwa_clid=%s for lead %s: %s", ctwa_clid, lead.get("id"), exc)
    # Atribuição do funil (Opção B): carimba origem do anúncio CTWA quando ainda não há
    # origem no lead. First-touch vence — não sobrescreve uma origem já capturada (LP/CTWA
    # anterior). Mensagens orgânicas trazem ctwa_origem=None e são no-op.
    try:
        if lead and ctwa_origem and not (lead.get("metadata") or {}).get("origem"):
            new_meta = {**(lead.get("metadata") or {}), "origem": ctwa_origem}
            update_lead(lead["id"], metadata=new_meta)
    except Exception as exc:
        logger.warning("Failed to stamp ctwa origem=%s for lead %s: %s", ctwa_origem, lead.get("id"), exc)
    # Merge do BSUID: carimba o bsuid num lead já existente que ainda não o tem (get_or_create
    # só o injeta na criação). Assim, se este usuário passar a omitir o telefone (adoção de
    # username), continuamos a reencontrá-lo pela coluna bsuid. Fail-soft: uma colisão do
    # índice único (bsuid já pertence a outro lead) só loga, nunca derruba o registro.
    try:
        if lead and is_bsuid(bsuid) and lead.get("bsuid") != bsuid:
            update_lead(lead["id"], bsuid=bsuid)
    except Exception as exc:
        logger.warning("Failed to stamp bsuid=%s for lead %s: %s", bsuid, lead.get("id"), exc)


def _track_inbound_message_time(phone: str) -> None:
    """Update last_customer_message_at so the 24h window status stays current.

    `phone` is the routing identity — a normalized phone OR a BSUID (username adopter,
    whose lead row has phone="" and is keyed by the bsuid column). Match on the right
    column so the 24h window and follow-up cancellation also work for BSUID-only leads.
    """
    normalized = normalize_phone(phone)
    id_col = "bsuid" if is_bsuid(normalized) else "phone"
    try:
        run_with_retry(
            lambda: get_supabase().table("leads").update(
                {"last_customer_message_at": datetime.now(timezone.utc).isoformat()}
            ).eq(id_col, normalized).execute(),
            label="last_customer_message_at",
        )
    except Exception as e:
        logger.warning(f"Failed to update last_customer_message_at for {normalized}: {e}")

    # Cancela follow-ups pendentes pois cliente respondeu
    try:
        from app.follow_up.service import cancel_followups_by_phone
        cancel_followups_by_phone(normalized, reason="client_replied")
    except Exception as e:
        logger.warning(f"[FOLLOWUP] Failed to cancel follow-ups for {phone}: {e}")




router = APIRouter()


def _extract_from_number(payload: dict) -> str | None:
    """Routing identity from raw payload: phone (messages[].from) or BSUID (from_user_id).

    Runs on the raw payload before parsing so the Dev Router catches every message type
    (CLAUDE.md section 2). Returns the phone when present, else the BSUID, else None.
    """
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                identity = msg.get("from") or msg.get("from_user_id")
                if identity:
                    return identity
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


def _status_has_backfillable_contact(payload: dict) -> bool:
    """True if any contacts block carries both wa_id and user_id (a phone worth backfilling).

    Lets the caller skip enqueuing the backfill task on the vast majority of delivery/read
    receipts, which carry no such pair.
    """
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for c in change.get("value", {}).get("contacts", []):
                if c.get("wa_id") and c.get("user_id"):
                    return True
    return False


def _backfill_phone_from_status(payload: dict) -> None:
    """When a status/contacts block carries both wa_id and user_id, merge the phone
    onto the BSUID lead (free phone recovery for username adopters)."""
    try:
        from app.leads.service import resolve_lead_identity
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for c in change.get("value", {}).get("contacts", []):
                    wa_id = c.get("wa_id")
                    user_id = c.get("user_id")
                    if wa_id and user_id:
                        resolve_lead_identity(wa_id, user_id)
    except Exception as exc:
        logger.warning("[DELIVERY] phone backfill failed: %s", exc)


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


async def _is_duplicate_wamid(redis, wamid: str) -> bool:
    """Return True if this wamid has already been processed (idempotency check).

    Uses Redis SETNX with a 24h TTL so each unique wamid is processed at most once.
    Fail-open: if Redis raises, logs a warning and returns False so the message is
    processed normally — we never drop a real customer message due to a Redis hiccup.
    """
    key = f"seen_wamid:{wamid}"
    try:
        result = await redis.set(key, "1", nx=True, ex=WAMID_DEDUP_TTL_SECS)
        # set(..., nx=True) returns True when the key was newly created,
        # None when the key already existed.
        return result is None
    except Exception as exc:
        logger.warning("[DEDUP] Redis error checking wamid=%s — processing normally: %s", wamid, exc)
        return False


async def _unmark_wamid(redis, wamid: str) -> None:
    """Clear the seen-wamid key so a message that failed to buffer is reprocessed on redelivery.

    The dedup mark is set on ingestion (before buffering) to absorb Meta's retry bursts.
    If buffering then fails, leaving the mark would make Meta's redelivery be silently
    skipped — a data-loss window. Clearing it here lets the redelivery be processed.
    """
    try:
        await redis.delete(f"seen_wamid:{wamid}")
    except Exception as exc:
        logger.warning("[DEDUP] failed to unmark wamid=%s after buffer error: %s", wamid, exc)


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
                from_number = statuses[0].get("recipient_id") or statuses[0].get("recipient_user_id")
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

    if _status_has_backfillable_contact(payload):
        background_tasks.add_task(_backfill_phone_from_status, payload)

    for msg in messages:
        # NOTE: marcamos o wamid como visto na ingestão (antes do processamento). Se o
        # push_to_buffer falhar logo após o SETNX, uma reentrega da Meta seria pulada —
        # risco aceito: (a) o objetivo é justamente deduplicar os retries agressivos da Meta;
        # (b) se o Redis estiver fora, o SETNX falha-open e o wamid NÃO é marcado.
        if msg.message_id and await _is_duplicate_wamid(redis, msg.message_id):
            logger.info(
                "[DEDUP] Duplicate wamid=%s from=%s — skipping (already processed)",
                msg.message_id,
                msg.from_number,
            )
            continue

        identity = msg.from_number or msg.bsuid or ""
        logger.info(f"Meta message from {msg.from_number}: type={msg.type}")
        msg.channel_id = channel["id"]

        # Register lead immediately — guarantees CRM entry before buffer flushes.
        # ctwa_clid (se presente) vincula o lead ao clique do anúncio Meta Ads (CTWA).
        background_tasks.add_task(_register_lead, msg.from_number, msg.push_name, msg.ctwa_clid, msg.ctwa_origem, msg.bsuid)

        # CA#1: o read receipt (tique azul) NÃO é mais disparado aqui na ingestão — isso
        # marcava a mensagem como lida instantaneamente (tique de robô). Agora o mark_read
        # acontece no INÍCIO DO TURNO DA IA, dentro de process_buffered_messages, quando o
        # debounce do buffer expira e a Valéria vai de fato agir. (_mark_read_bg permanece
        # disponível como utilitário, mas não é chamado na ingestão.)

        if msg.text and msg.text.strip().lower() == "!resetar":
            try:
                result = purge_dev_lead(identity)
                provider = get_provider(channel)
                if result.get("purged"):
                    await provider.send_text(identity, "Lead removido completamente do CRM. Pode comecar do zero.")
                else:
                    await provider.send_text(identity, f"Nada a remover: {result.get('reason', 'lead nao encontrado')}.")
            except ValueError:
                logger.warning("[RESET] !resetar ignorado: numero %s nao esta na whitelist de dev", msg.from_number)
            except Exception as e:
                logger.error(f"Failed to purge lead: {e}", exc_info=True)
            continue

        background_tasks.add_task(_track_inbound_message_time, identity)
        try:
            await push_to_buffer(redis, msg)
        except Exception as exc:
            # Buffering failed AFTER the wamid was marked as seen — clear the mark so
            # Meta's redelivery is reprocessed instead of silently deduped (data-loss window),
            # then re-raise so Meta receives a non-200 and retries.
            logger.error(
                "[BUFFER] push_to_buffer falhou para wamid=%s: %s — desfazendo dedup mark",
                msg.message_id, exc, exc_info=True,
            )
            if msg.message_id:
                await _unmark_wamid(redis, msg.message_id)
            raise

    return {"status": "ok"}

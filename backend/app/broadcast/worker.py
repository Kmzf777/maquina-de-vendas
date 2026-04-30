import asyncio
import logging
import random
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.db.supabase import get_supabase
from app.whatsapp.registry import get_provider
from app.channels.service import get_channel_by_id
from app.broadcast.service import (
    get_pending_broadcast_leads,
    mark_broadcast_lead_sent,
    mark_broadcast_lead_failed,
    increment_broadcast_sent,
    increment_broadcast_failed,
)
from app.cadence.service import create_enrollment
from app.conversations.service import get_or_create_conversation, update_conversation, save_message
from app.cadence.scheduler import (
    process_due_cadences,
    process_reengagements,
    process_stagnation_triggers,
    calculate_next_send_at,
)

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"

logger = logging.getLogger(__name__)

# Dynamic variable tokens that get resolved from the lead record at send time.
_LEAD_FIELD_TOKENS = {
    "{{first_name}}": lambda lead: (lead.get("name") or "").split()[0] if lead.get("name") else "",
    "{{lead_name}}":  lambda lead: lead.get("name") or "",
    "{{phone}}":      lambda lead: lead.get("phone") or "",
}


def _resolve_value(value: str, lead: dict) -> str:
    for token, resolver in _LEAD_FIELD_TOKENS.items():
        if value == token:
            return resolver(lead)
    return value


def _apply_variables(text: str, template_variables: dict, lead: dict) -> str:
    resolved = [
        _resolve_value(str(v), lead)
        for k, v in template_variables.items()
        if k != "components"
    ]
    for i, value in enumerate(resolved, start=1):
        text = text.replace(f"{{{{{i}}}}}", value)
    return text


async def _render_template_body(template_name: str, template_variables: dict, lead: dict, channel: dict | None = None) -> str:
    """Render template BODY text. Tries local DB first, falls back to Meta API and auto-syncs."""
    # 1. Try local message_templates table
    try:
        sb = get_supabase()
        result = sb.table("message_templates").select("components").eq("name", template_name).limit(1).execute()
        if result.data:
            components = result.data[0].get("components", [])
            body = next((c for c in components if c.get("type") == "BODY"), None)
            if body:
                return _apply_variables(body.get("text", ""), template_variables, lead)
    except Exception as e:
        logger.warning(f"[BROADCAST] Local template lookup failed for {template_name}: {e}")

    # 2. Fallback: fetch from Meta API and auto-sync into local DB
    if channel:
        try:
            config = channel.get("provider_config", {})
            waba_id = config.get("waba_id")
            access_token = config.get("access_token")
            if waba_id and access_token:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"https://graph.facebook.com/v21.0/{waba_id}/message_templates",
                        params={"name": template_name},
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    data = resp.json().get("data", [])
                    if data:
                        components = data[0].get("components", [])
                        body = next((c for c in components if c.get("type") == "BODY"), None)
                        if body:
                            rendered = _apply_variables(body.get("text", ""), template_variables, lead)
                            try:
                                sb = get_supabase()
                                sb.table("message_templates").insert({
                                    "channel_id": channel["id"],
                                    "name": template_name,
                                    "language": data[0].get("language", "pt_BR"),
                                    "requested_category": data[0].get("category", "UTILITY"),
                                    "category": data[0].get("category", "UTILITY"),
                                    "components": components,
                                    "meta_template_id": data[0].get("id"),
                                    "status": "approved",
                                }).execute()
                                logger.info(f"[BROADCAST] Auto-synced template {template_name} to local DB")
                            except Exception as sync_err:
                                logger.warning(f"[BROADCAST] Auto-sync failed for {template_name}: {sync_err}")
                            return rendered
        except Exception as e:
            logger.warning(f"[BROADCAST] Meta API template lookup failed for {template_name}: {e}")

    return f"[Template: {template_name}]"


def _build_template_components(template_variables: dict, lead: dict) -> list | None:
    """Convert {param_name: value} dict into Meta named-parameter components array."""
    if not template_variables:
        return None
    parameters = [
        {
            "type": "text",
            "parameter_name": k,
            "text": _resolve_value(str(v), lead),
        }
        for k, v in template_variables.items()
        if k != "components"  # skip legacy raw-components key
    ]
    if not parameters:
        return None
    return [{"type": "body", "parameters": parameters}]


async def run_worker():
    """Main worker loop: processes broadcasts, cadences, and stagnation triggers."""
    logger.info("Broadcast + Cadence worker started")

    while True:
        try:
            await process_broadcasts()
            await process_due_cadences()
            await process_reengagements()
            await process_stagnation_triggers()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)


async def process_broadcasts():
    """Find running broadcasts and send pending templates."""
    sb = get_supabase()
    broadcasts = (
        sb.table("broadcasts")
        .select("*")
        .eq("status", "running")
        .eq("env_tag", _ENV_TAG)
        .execute()
        .data
    )

    logger.info(f"[DEBUG-BROADCAST] tick — env_tag={_ENV_TAG} running_broadcasts={len(broadcasts)}")
    for broadcast in broadcasts:
        logger.info(f"[DEBUG-BROADCAST] picked broadcast id={broadcast['id']} name={broadcast.get('name')} env_tag={broadcast.get('env_tag')}")
        await process_single_broadcast(broadcast)


async def process_single_broadcast(broadcast: dict):
    sb = get_supabase()
    broadcast_id = broadcast["id"]

    pending_leads = get_pending_broadcast_leads(broadcast_id, limit=10)
    logger.info(f"[DEBUG-BROADCAST] broadcast={broadcast_id} pending_leads={len(pending_leads)}")

    if not pending_leads:
        # Check if all leads are processed
        remaining = (
            sb.table("broadcast_leads")
            .select("id", count="exact")
            .eq("broadcast_id", broadcast_id)
            .eq("status", "pending")
            .execute()
            .count
        )
        if not remaining:
            sb.table("broadcasts").update({"status": "completed"}).eq("id", broadcast_id).execute()
            logger.info(f"Broadcast {broadcast_id} completed")
        return

    for bl in pending_leads:
        # Check if still running
        current = sb.table("broadcasts").select("status").eq("id", broadcast_id).single().execute().data
        if current["status"] != "running":
            return

        lead = bl["leads"]

        try:
            channel_id = broadcast.get("channel_id")
            if not channel_id:
                logger.warning(
                    f"[BROADCAST] broadcast {broadcast_id} has no channel_id, skipping lead {lead['phone']}"
                )
                mark_broadcast_lead_failed(bl["id"], "broadcast has no channel_id")
                increment_broadcast_failed(broadcast_id)
                continue

            channel = get_channel_by_id(channel_id)
            if not channel:
                logger.error(f"[BROADCAST] Channel {channel_id} not found, skipping lead {lead['phone']}")
                mark_broadcast_lead_failed(bl["id"], f"channel {channel_id} not found")
                increment_broadcast_failed(broadcast_id)
                continue
            provider = get_provider(channel)
            components = _build_template_components(
                broadcast.get("template_variables") or {},
                lead,
            )
            logger.info(
                "[BROADCAST] sending template '%s' (%s) to %s — components: %s",
                broadcast["template_name"],
                broadcast.get("template_language_code", "pt_BR"),
                lead["phone"],
                components,
            )
            await provider.send_template(
                to=lead["phone"],
                template_name=broadcast["template_name"],
                components=components,
                language_code=broadcast.get("template_language_code", "pt_BR"),
            )
            mark_broadcast_lead_sent(bl["id"])
            increment_broadcast_sent(broadcast_id)

            # Always record conversation and persist outbound message
            conversation = None
            try:
                logger.info(f"[DEBUG-BROADCAST] step=get_or_create_conversation lead_id={lead['id']} channel_id={channel_id}")
                conversation = get_or_create_conversation(lead["id"], channel_id)
                logger.info(f"[DEBUG-BROADCAST] got conversation id={conversation.get('id') if conversation else None}")
                conv_updates = {"status": "template_sent"}
                if broadcast.get("agent_profile_id"):
                    conv_updates["agent_profile_id"] = broadcast["agent_profile_id"]
                    conv_updates["ai_enabled"] = True
                else:
                    conv_updates["ai_enabled"] = False
                logger.info(f"[DEBUG-BROADCAST] step=update_conversation id={conversation['id']} updates={conv_updates}")
                update_conversation(conversation["id"], **conv_updates)
                logger.info(f"[DEBUG-BROADCAST] update_conversation OK")
            except Exception as ce:
                logger.error(
                    f"[BROADCAST] Could not update conversation for {lead['phone']}: {ce}",
                    exc_info=True,
                )

            try:
                if conversation:
                    logger.info(f"[DEBUG-BROADCAST] step=save_message conv_id={conversation['id']} lead_id={lead['id']}")
                    rendered_content = await _render_template_body(
                        broadcast["template_name"],
                        broadcast.get("template_variables") or {},
                        lead,
                        channel,
                    )
                    saved = save_message(
                        conversation["id"],
                        lead["id"],
                        "assistant",
                        rendered_content,
                        sent_by="broadcast",
                    )
                    logger.info(f"[DEBUG-BROADCAST] save_message OK returned={saved}")
                else:
                    logger.error(
                        f"[BROADCAST] Skipping save_message for {lead['phone']}: no conversation"
                    )
            except Exception as ce:
                logger.error(
                    f"[BROADCAST] Could not save message for {lead['phone']}: {ce}",
                    exc_info=True,
                )

            # Enroll in cadence if configured
            if broadcast.get("cadence_id"):
                try:
                    cadence = sb.table("cadences").select("*").eq("id", broadcast["cadence_id"]).single().execute().data
                    if cadence:
                        first_step = (
                            sb.table("cadence_steps")
                            .select("delay_days")
                            .eq("cadence_id", cadence["id"])
                            .eq("step_order", 1)
                            .execute()
                            .data
                        )
                        delay = first_step[0]["delay_days"] if first_step else 1
                        next_send = calculate_next_send_at(
                            datetime.now(timezone.utc),
                            delay,
                            cadence.get("send_start_hour", 7),
                            cadence.get("send_end_hour", 18),
                        )
                        create_enrollment(
                            cadence_id=cadence["id"],
                            lead_id=lead["id"],
                            broadcast_id=broadcast_id,
                            next_send_at=next_send,
                        )
                except Exception as ce:
                    logger.warning(f"Could not enroll {lead['phone']} in cadence: {ce}")

            logger.info(f"Template sent to {lead['phone']}")

        except Exception as e:
            logger.error(f"Failed to send to {lead['phone']}: {e}")
            mark_broadcast_lead_failed(bl["id"], str(e))
            increment_broadcast_failed(broadcast_id)

        interval = random.randint(
            broadcast.get("send_interval_min", 3),
            broadcast.get("send_interval_max", 8),
        )
        await asyncio.sleep(interval)

import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta

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
    save_broadcast_lead_wamid,
)
from app.conversations.service import get_or_create_conversation, update_conversation, save_message
from app.leads.service import update_lead
from app.follow_up.scheduler import process_due_followups

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"

logger = logging.getLogger(__name__)

# Dynamic variable tokens that get resolved from the lead record at send time.
_LEAD_FIELD_TOKENS = {
    # New tokens (used by smart broadcast modal)
    "{{primeiro_nome}}": lambda lead: (lead.get("name") or "").split()[0] if lead.get("name") else "",
    "{{nome_completo}}": lambda lead: lead.get("name") or "",
    "{{telefone}}":      lambda lead: lead.get("phone") or "",
    "{{empresa}}":       lambda lead: lead.get("company") or lead.get("nome_fantasia") or "",
    # Legacy tokens kept for backward compatibility
    "{{first_name}}":    lambda lead: (lead.get("name") or "").split()[0] if lead.get("name") else "",
    "{{lead_name}}":     lambda lead: lead.get("name") or "",
    "{{phone}}":         lambda lead: lead.get("phone") or "",
}


def _resolve_value(value: str, lead: dict) -> str:
    for token, resolver in _LEAD_FIELD_TOKENS.items():
        if value == token:
            return resolver(lead)
    return value


def _apply_variables(text: str, template_variables: dict, lead: dict) -> str:
    params_type = template_variables.get("__params_type__", "named")
    body_vars = {
        k: v for k, v in template_variables.items()
        if not str(k).startswith("__") and k != "components"
    }
    if params_type == "positional":
        ordered = sorted(
            body_vars.items(),
            key=lambda x: int(str(x[0]).lstrip("0") or "0") if str(x[0]).isdigit() else 999,
        )
        for i, (_, v) in enumerate(ordered, start=1):
            text = text.replace(f"{{{{{i}}}}}", _resolve_value(str(v), lead))
    else:
        for k, v in body_vars.items():
            text = text.replace(f"{{{{{k}}}}}", _resolve_value(str(v), lead))
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
    """Build Meta template components from stored variable mappings.

    Supports:
    - Named params: {param_name: token_or_text, ...}
    - Positional params: {"1": token, "2": token, ...} with __params_type__="positional"
    - Media headers: __header_type__ = IMAGE|VIDEO|DOCUMENT, __header_url__ = url
    Reserved keys starting with __ control behaviour and are excluded from body params.
    Old broadcasts without __params_type__ default to named (backward compat).
    """
    if not template_variables:
        return None

    params_type = template_variables.get("__params_type__", "named")
    header_type = template_variables.get("__header_type__")
    header_url = template_variables.get("__header_url__")

    # Exclude reserved keys and legacy "components" key from body variables
    body_vars = {
        k: v for k, v in template_variables.items()
        if not str(k).startswith("__") and k != "components"
    }

    components: list = []

    # Header component — media types only (TEXT header has no parameters)
    if header_type in ("IMAGE", "VIDEO", "DOCUMENT") and header_url:
        media_key = header_type.lower()
        components.append({
            "type": "header",
            "parameters": [{"type": media_key, media_key: {"link": header_url}}],
        })

    # Body component
    if params_type == "positional":
        # Sort by numeric key (1, 2, 3…); non-numeric keys sort last
        ordered = sorted(
            body_vars.items(),
            key=lambda x: int(str(x[0]).lstrip("0") or "0") if str(x[0]).isdigit() else 999,
        )
        parameters = [
            {"type": "text", "text": _resolve_value(str(v), lead)}
            for _, v in ordered
        ]
    else:
        # Named params (default — also handles legacy broadcasts)
        parameters = [
            {
                "type": "text",
                "parameter_name": k,
                "text": _resolve_value(str(v), lead),
            }
            for k, v in body_vars.items()
        ]

    if parameters:
        components.append({"type": "body", "parameters": parameters})

    return components if components else None


def _build_conv_updates(broadcast: dict) -> dict:
    """Builds conversation-level updates for a broadcast dispatch.

    Only status and agent_profile_id — ai_enabled lives on the lead now.
    """
    conv_updates: dict = {"status": "template_sent"}
    if broadcast.get("agent_profile_id"):
        conv_updates["agent_profile_id"] = broadcast["agent_profile_id"]
    return conv_updates


def _broadcast_ai_enabled(broadcast: dict, channel: dict | None = None) -> bool:
    """Returns the ai_enabled value to set on the lead for this broadcast.

    Invariant: human channel → always False; ai channel with agent → True.
    """
    if channel and channel.get("mode", "ai") == "human":
        return False
    return bool(broadcast.get("agent_profile_id"))


def reconcile_broadcast_replies() -> None:
    """Catch-up job: fills first_replied_at for leads that replied but webhook failed.

    Scans broadcast_leads sent in the last 48h (minus the last 2min to avoid
    racing with the webhook). Limit 200 leads per tick.
    """
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=48)).isoformat()
    window_end = (now - timedelta(minutes=2)).isoformat()

    pending = (
        sb.table("broadcast_leads")
        .select("id, lead_id, sent_at")
        .in_("status", ["sent", "delivered"])
        .is_("first_replied_at", "null")
        .gte("sent_at", window_start)
        .lte("sent_at", window_end)
        .limit(200)
        .execute()
    )
    if not pending.data:
        return

    reconciled = 0
    for bl in pending.data:
        try:
            sent_at_dt = datetime.fromisoformat(bl["sent_at"].replace("Z", "+00:00"))
            reply_window_end = (sent_at_dt + timedelta(hours=48)).isoformat()
            reply = (
                sb.table("messages")
                .select("id, created_at")
                .eq("lead_id", bl["lead_id"])
                .eq("role", "user")
                .gt("created_at", bl["sent_at"])
                .lte("created_at", reply_window_end)
                .order("created_at")
                .limit(1)
                .execute()
            )
            if reply.data:
                sb.table("broadcast_leads").update({
                    "first_replied_at": reply.data[0]["created_at"],
                }).eq("id", bl["id"]).execute()
                reconciled += 1
        except Exception as e:
            logger.warning("[BROADCAST] reconcile error for bl=%s: %s", bl.get("id"), e)

    if reconciled:
        logger.info(
            "[BROADCAST] reconcile_broadcast_replies: %d leads atualizados",
            reconciled,
        )


async def run_worker():
    """Main worker loop: broadcasts, automation engine, follow-ups."""
    logger.info("Worker started")

    while True:
        try:
            from app.automation.engine import process_due_enrollments
            from app.automation.triggers import check_polling_triggers
            await process_scheduled_broadcasts()
            await process_broadcasts()
            await check_polling_triggers()
            await process_due_enrollments()
            await process_due_followups()
            reconcile_broadcast_replies()
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


async def process_scheduled_broadcasts():
    """Auto-inicia broadcasts cujo scheduled_at já passou."""
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    broadcasts = (
        sb.table("broadcasts")
        .select("id, name")
        .eq("status", "scheduled")
        .eq("env_tag", _ENV_TAG)
        .lte("scheduled_at", now)
        .execute()
        .data
    )
    for broadcast in broadcasts:
        broadcast_id = broadcast["id"]
        pending_count = (
            sb.table("broadcast_leads")
            .select("id", count="exact")
            .eq("broadcast_id", broadcast_id)
            .eq("status", "pending")
            .execute()
            .count
        ) or 0
        if not pending_count:
            logger.error(
                f"[SCHEDULER] broadcast {broadcast_id} sem leads pendentes — marcando como failed"
            )
            sb.table("broadcasts").update({"status": "failed"}).eq("id", broadcast_id).execute()
            continue
        sb.table("broadcasts").update({"status": "running"}).eq("id", broadcast_id).execute()
        logger.info(
            f"[SCHEDULER] broadcast {broadcast_id} ({broadcast.get('name')}) "
            f"iniciado automaticamente — {pending_count} leads"
        )


async def process_single_broadcast(broadcast: dict):
    sb = get_supabase()
    broadcast_id = broadcast["id"]

    # Recover leads stuck in 'processing' for over 5 minutes (worker crash/restart).
    # If wamid is set, the message reached Meta — mark as sent instead of re-queuing
    # to avoid sending the same template twice.
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    sb.table("broadcast_leads").update({
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("broadcast_id", broadcast_id).eq("status", "processing").lt(
        "claimed_at", cutoff
    ).filter("wamid", "not.is", "null").execute()
    sb.table("broadcast_leads").update({"status": "pending", "claimed_at": None}).eq(
        "broadcast_id", broadcast_id
    ).eq("status", "processing").lt("claimed_at", cutoff).filter("wamid", "is", "null").execute()

    # Pre-fetch pipeline_id for stage move once per batch — move_to_stage_id is the same for
    # every lead, so querying pipeline_stages inside the per-lead loop is wasteful.
    move_to_stage_id: str | None = broadcast.get("move_to_stage_id")
    target_pipeline_id: str | None = None
    if move_to_stage_id:
        try:
            stage_row = sb.table("pipeline_stages").select("pipeline_id").eq("id", move_to_stage_id).limit(1).execute()
            if stage_row.data:
                target_pipeline_id = stage_row.data[0]["pipeline_id"]
            else:
                logger.warning(
                    "[BROADCAST] move_to_stage_id %s not found in pipeline_stages — stage move skipped for broadcast %s",
                    move_to_stage_id, broadcast_id,
                )
        except Exception as stage_err:
            logger.warning("[BROADCAST] Failed to fetch pipeline for move_to_stage_id %s: %s", move_to_stage_id, stage_err)

    pending_leads = get_pending_broadcast_leads(broadcast_id, limit=10)
    logger.info(f"[DEBUG-BROADCAST] broadcast={broadcast_id} pending_leads={len(pending_leads)}")

    if not pending_leads:
        # Count both pending and processing — don't mark complete while another worker holds claims
        remaining = (
            sb.table("broadcast_leads")
            .select("id", count="exact")
            .eq("broadcast_id", broadcast_id)
            .in_("status", ["pending", "processing"])
            .execute()
            .count
        )
        if not remaining:
            sb.table("broadcasts").update({"status": "completed"}).eq("id", broadcast_id).execute()
            logger.info(f"Broadcast {broadcast_id} completed")
        return

    for bl in pending_leads:
        # Atomic claim: only proceeds if this worker wins the race
        claim = (
            sb.table("broadcast_leads")
            .update({"status": "processing", "claimed_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", bl["id"])
            .eq("status", "pending")
            .execute()
        )
        if not claim.data:
            logger.info(f"[BROADCAST] Lead {bl['id']} already claimed by another worker, skipping")
            continue
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
            send_response = await provider.send_template(
                to=lead["phone"],
                template_name=broadcast["template_name"],
                components=components,
                language_code=broadcast.get("template_language_code", "pt_BR"),
            )
            # Save wamid BEFORE marking as sent so the crash-recovery window can detect
            # that the message already reached Meta and avoid a duplicate send.
            wamid = None
            try:
                wamid = (send_response.get("messages") or [{}])[0].get("id")
                if wamid:
                    save_broadcast_lead_wamid(bl["id"], wamid)
            except Exception as wamid_err:
                logger.warning("[BROADCAST] Could not save wamid for lead %s: %s", lead["phone"], wamid_err)
            mark_broadcast_lead_sent(bl["id"])
            increment_broadcast_sent(broadcast_id)

            # Fire post_broadcast automation trigger (fire-and-forget)
            try:
                from app.automation.triggers import fire_trigger as _fire_trigger
                asyncio.create_task(_fire_trigger("post_broadcast", str(lead["id"]), {
                    "broadcast_id": str(broadcast_id),
                    "replied_only": False,
                }))
            except Exception as trig_err:
                logger.warning("[BROADCAST] post_broadcast trigger error: %s", trig_err)

            # Move lead's deal to configured Kanban stage if set
            if move_to_stage_id and target_pipeline_id:
                try:
                    # Update ALL deals for this lead in the pipeline at once.
                    # Using limit(1) on the previous SELECT+UPDATE left older deals in
                    # the original stage, causing leads to reappear in stage filters.
                    update_result = (
                        sb.table("deals")
                        .update({
                            "stage_id": move_to_stage_id,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        })
                        .eq("lead_id", lead["id"])
                        .eq("pipeline_id", target_pipeline_id)
                        .select("id")
                        .execute()
                    )
                    if not update_result.data:
                        # No deal found in this pipeline — create one so the lead is tracked
                        title = (lead.get("name") or lead.get("phone") or "Lead") + " - Oportunidade"
                        sb.table("deals").insert({
                            "lead_id": lead["id"],
                            "title": title,
                            "stage": "novo",
                            "pipeline_id": target_pipeline_id,
                            "stage_id": move_to_stage_id,
                        }).execute()
                    logger.info(
                        "[BROADCAST] Moved/created deal for lead %s to pipeline %s stage %s (deals_updated=%d)",
                        lead["id"], target_pipeline_id, move_to_stage_id, len(update_result.data),
                    )
                    # Track the move timestamp on the broadcast_lead row
                    try:
                        sb.table("broadcast_leads").update({
                            "deal_moved_at": datetime.now(timezone.utc).isoformat(),
                        }).eq("id", bl["id"]).execute()
                    except Exception as track_err:
                        logger.debug("[BROADCAST] deal_moved_at not tracked (run migration): %s", track_err)
                except Exception as move_err:
                    logger.warning(
                        "[BROADCAST] Failed to move deal for lead %s: %s",
                        lead["id"], move_err,
                    )

            # Always record conversation and persist outbound message
            conversation = None
            try:
                logger.info(f"[DEBUG-BROADCAST] step=get_or_create_conversation lead_id={lead['id']} channel_id={channel_id}")
                conversation = get_or_create_conversation(lead["id"], channel_id)
                logger.info(f"[DEBUG-BROADCAST] got conversation id={conversation.get('id') if conversation else None}")
                conv_updates = _build_conv_updates(broadcast)
                logger.info(f"[DEBUG-BROADCAST] step=update_conversation id={conversation['id']} updates={conv_updates}")
                update_conversation(conversation["id"], **conv_updates)
                logger.info(f"[DEBUG-BROADCAST] update_conversation OK")
            except Exception as ce:
                logger.error(
                    f"[BROADCAST] Could not update conversation for {lead['phone']}: {ce}",
                    exc_info=True,
                )

            # Update ai_enabled on the lead regardless of whether conversation update succeeded.
            # This is the gate that controls whether Valeria responds when the lead replies.
            try:
                ai_enabled = _broadcast_ai_enabled(broadcast, channel=channel)
                lead_updates: dict = {"ai_enabled": ai_enabled}
                if ai_enabled:
                    lead_updates["human_control"] = False
                logger.info(f"[DEBUG-BROADCAST] step=update_lead updates={lead_updates} lead_id={lead['id']}")
                update_lead(lead["id"], **lead_updates)
                logger.info(f"[DEBUG-BROADCAST] update_lead OK")
            except Exception as ce:
                logger.error(
                    f"[BROADCAST] Could not update lead ai_enabled for {lead['phone']}: {ce}",
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
                        wamid=wamid,
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

            # Enroll in campaign if configured
            if broadcast.get("campaign_id"):
                try:
                    from app.campaigns.service import (
                        get_campaign, list_nodes, create_enrollment as create_campaign_enrollment,
                        is_already_enrolled,
                    )
                    campaign = get_campaign(broadcast["campaign_id"])
                    if campaign and campaign["status"] == "active":
                        nodes = list_nodes(campaign["id"])
                        trigger = next((n for n in nodes if n["type"] == "trigger"), None)
                        if trigger and trigger.get("next_node_id") and not is_already_enrolled(campaign["id"], lead["id"]):
                            create_campaign_enrollment(
                                campaign_id=campaign["id"],
                                lead_id=lead["id"],
                                current_node_id=trigger["next_node_id"],
                                next_execute_at=datetime.now(timezone.utc),
                            )
                except Exception as ce:
                    logger.warning("[CAMPAIGNS] Could not enroll lead %s from broadcast: %s", lead.get("phone", lead["id"]), ce)

            logger.info(f"Template sent to {lead['phone']}")

        except httpx.HTTPStatusError as http_err:
            try:
                meta_err = http_err.response.json().get("error", {})
                detail = meta_err.get("message", str(http_err))
                code = meta_err.get("code", "")
                error_msg = f"Meta {http_err.response.status_code}: {detail}"
                if code:
                    error_msg += f" (código {code})"
            except Exception:
                error_msg = str(http_err)
            logger.error(f"[BROADCAST] Meta API error para {lead['phone']}: {error_msg}")
            mark_broadcast_lead_failed(bl["id"], error_msg)
            increment_broadcast_failed(broadcast_id)
        except Exception as e:
            logger.error(f"Failed to send to {lead['phone']}: {e}")
            mark_broadcast_lead_failed(bl["id"], str(e))
            increment_broadcast_failed(broadcast_id)

        interval = random.randint(
            broadcast.get("send_interval_min", 3),
            broadcast.get("send_interval_max", 8),
        )
        await asyncio.sleep(interval)

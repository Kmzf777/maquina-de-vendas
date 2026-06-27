import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta

from app.campaigns.service import (
    get_campaigns_with_trigger_type,
    is_already_enrolled,
    create_enrollment,
    get_due_enrollments,
    update_enrollment,
    complete_enrollment,
    cancel_enrollment,
    pause_enrollment,
)
from app.db.supabase import get_supabase
from app.config import get_settings
from app.automation.retry import calculate_next_retry

logger = logging.getLogger(__name__)

# Status HTTP da Meta que não adianta retentar (template/locale/param errados):
# o disparo nunca vai ser aceito — cancelar a enrollment em vez de re-armar.
_PERMANENT_STATUS = {400, 403, 404}


def _is_permanent_error(exc: Exception) -> bool:
    """True para rejeições da Meta que não mudam com retry (4xx de template/param).

    Cobre dois formatos: httpx.HTTPStatusError (raise_for_status em 4xx) e o
    RuntimeError que send_template/send_text levantam quando a Meta devolve HTTP 200
    com erro embutido ('... rejected (missing messages ...)').
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in _PERMANENT_STATUS:
        return True
    if isinstance(exc, RuntimeError) and "rejected" in str(exc):
        return True
    return False


def decide_failure_update(exc: Exception, retry_count: int, now: datetime) -> dict:
    """Pure: kwargs para update_enrollment que SEMPRE tiram a enrollment do estado
    imediatamente-due — raiz do loop que inflou meta_webhook_logs.

    - Erro permanente (4xx / rejeição embutida): status='cancelled'.
    - Erro transitório: backoff via calculate_next_retry (1h/4h/24h, teto 3);
      ao estourar o teto, cancela.
    """
    err = str(exc)[:500]
    if _is_permanent_error(exc):
        return {"status": "cancelled", "last_error": err}
    next_at, new_count, final = calculate_next_retry(retry_count, now)
    if final:
        return {"status": "cancelled", "last_error": err}
    iso = next_at.isoformat()
    return {
        "retry_count": new_count,
        "next_retry_at": iso,
        "next_execute_at": iso,
        "last_error": err,
    }


_ENV_TAG = "dev" if get_settings().is_dev_env else "production"

BRT_OFFSET = timedelta(hours=-3)


def _is_within_window(now_utc: datetime, start_hour: int = 7, end_hour: int = 18) -> bool:
    brt = now_utc + BRT_OFFSET
    return start_hour <= brt.hour < end_hour


def _next_window_start(now_utc: datetime, start_hour: int = 7) -> datetime:
    brt = now_utc + BRT_OFFSET
    if brt.hour < start_hour:
        target = brt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    else:
        target = (brt + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return target - BRT_OFFSET


async def check_campaign_triggers(now: datetime | None = None) -> None:
    """Detect leads that satisfy trigger conditions and auto-enroll them."""
    now = now or datetime.now(timezone.utc)
    sb = get_supabase()

    # ── no_message triggers ────────────────────────────────────────────────────
    for trigger_node in get_campaigns_with_trigger_type("no_message"):
        cfg = trigger_node["config"]
        days = cfg.get("days", 30)
        stage_filter = cfg.get("stage_filter")
        cutoff = (now - timedelta(days=days)).isoformat()

        query = sb.table("leads").select("id, phone").eq("env_tag", _ENV_TAG).lte("last_msg_at", cutoff)
        if stage_filter:
            query = query.eq("stage", stage_filter)
        leads = query.limit(20).execute().data

        for lead in leads:
            campaign_id = trigger_node["campaign_id"]
            if is_already_enrolled(campaign_id, lead["id"]):
                continue
            if not trigger_node.get("next_node_id"):
                continue
            try:
                create_enrollment(
                    campaign_id=campaign_id,
                    lead_id=lead["id"],
                    current_node_id=trigger_node["next_node_id"],
                    next_execute_at=now,
                )
                logger.info("[CAMPAIGNS] Enrolled lead %s via no_message trigger", lead["phone"])
            except Exception as e:
                logger.warning("[CAMPAIGNS] Failed to enroll %s: %s", lead["id"], e)

    # ── stage_stagnation triggers ──────────────────────────────────────────────
    for trigger_node in get_campaigns_with_trigger_type("stage_stagnation"):
        cfg = trigger_node["config"]
        days = cfg.get("days", 7)
        stage = cfg.get("stage_filter")
        if not stage:
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        leads = sb.table("leads").select("id, phone").eq("env_tag", _ENV_TAG).eq("stage", stage).lte("entered_stage_at", cutoff).limit(20).execute().data
        for lead in leads:
            campaign_id = trigger_node["campaign_id"]
            if is_already_enrolled(campaign_id, lead["id"]) or not trigger_node.get("next_node_id"):
                continue
            try:
                create_enrollment(campaign_id=campaign_id, lead_id=lead["id"], current_node_id=trigger_node["next_node_id"], next_execute_at=now)
                logger.info("[CAMPAIGNS] Enrolled lead %s via stage_stagnation trigger", lead["phone"])
            except Exception as e:
                logger.warning("[CAMPAIGNS] Failed to enroll %s: %s", lead["id"], e)

    # ── stage_enter triggers ───────────────────────────────────────────────────
    for trigger_node in get_campaigns_with_trigger_type("stage_enter"):
        cfg = trigger_node["config"]
        stage = cfg.get("stage_filter")
        if not stage:
            continue
        leads = sb.table("leads").select("id, phone").eq("env_tag", _ENV_TAG).eq("stage", stage).limit(20).execute().data
        for lead in leads:
            campaign_id = trigger_node["campaign_id"]
            if is_already_enrolled(campaign_id, lead["id"]) or not trigger_node.get("next_node_id"):
                continue
            try:
                create_enrollment(campaign_id=campaign_id, lead_id=lead["id"], current_node_id=trigger_node["next_node_id"], next_execute_at=now)
            except Exception as e:
                logger.warning("[CAMPAIGNS] Failed to enroll %s: %s", lead["id"], e)


async def process_campaign_enrollments(now: datetime | None = None) -> None:
    """Execute the current node for each due enrollment."""
    now = now or datetime.now(timezone.utc)
    enrollments = get_due_enrollments(now, limit=20)

    for enrollment in enrollments:
        node = enrollment.get("campaign_nodes")
        lead = enrollment["leads"]
        if not node:
            complete_enrollment(enrollment["id"])
            continue

        node_type = node["type"]
        cfg = node.get("config", {})

        try:
            if node_type == "send":
                await _execute_send_node(enrollment, node, lead, now)

            elif node_type == "wait":
                days = cfg.get("days", 1)
                start_hour = cfg.get("send_start_hour", 7)
                target = now + timedelta(days=days)
                if not _is_within_window(target, start_hour, cfg.get("send_end_hour", 18)):
                    target = _next_window_start(target, start_hour)
                update_enrollment(enrollment["id"], next_execute_at=target.isoformat())
                logger.info("[CAMPAIGNS] Enrollment %s waiting %d days", enrollment["id"], days)
                continue

            elif node_type == "condition":
                _execute_condition_node(enrollment, node, lead, now)
                continue

            elif node_type == "action":
                _execute_action_node(enrollment, node, lead)

            elif node_type == "end":
                _execute_end_node(enrollment, node, lead)
                complete_enrollment(enrollment["id"])
                continue

            # Advance to next_node_id
            next_id = node.get("next_node_id")
            if next_id:
                update_enrollment(enrollment["id"], current_node_id=next_id, next_execute_at=now.isoformat(), retry_count=0)
            else:
                complete_enrollment(enrollment["id"])

        except Exception as e:
            logger.error("[CAMPAIGNS] Error processing enrollment %s node %s: %s", enrollment["id"], node.get("id"), e, exc_info=True)
            try:
                upd = decide_failure_update(e, enrollment.get("retry_count") or 0, now)
                update_enrollment(enrollment["id"], **upd)
            except Exception as inner:
                logger.error("[CAMPAIGNS] Failed to record enrollment failure %s: %s", enrollment["id"], inner)

        await asyncio.sleep(random.randint(2, 5))


async def _execute_send_node(enrollment: dict, node: dict, lead: dict, now: datetime) -> None:
    from app.whatsapp.registry import get_provider
    from app.channels.service import get_channel_for_lead
    from app.broadcast.worker import (
        _build_template_components, _render_template_body, _broadcast_ai_enabled,
    )
    from app.conversations.service import get_or_create_conversation, update_conversation, save_message
    from app.leads.service import update_lead, record_dispatch_note

    cfg = node["config"]
    template_name = cfg["template_name"]
    template_variables = cfg.get("template_variables", {})
    channel_id = cfg.get("channel_id")

    channel = None
    if channel_id:
        from app.channels.service import get_channel_by_id
        channel = get_channel_by_id(channel_id)
    if not channel:
        channel = get_channel_for_lead(enrollment["lead_id"])
    if not channel:
        logger.warning("[CAMPAIGNS] No channel for lead %s, skipping send", lead["phone"])
        return

    provider = get_provider(channel)
    components = _build_template_components(template_variables, lead)
    send_resp = await provider.send_template(
        to=lead["phone"],
        template_name=template_name,
        components=components,
        language_code=cfg.get("template_language", "pt_BR"),
    )

    wamid = None
    try:
        wamid = (send_resp.get("messages") or [{}])[0].get("id")
    except Exception:
        pass

    # Registra observação analítica de disparo no card de CRM (fail-soft).
    record_dispatch_note(enrollment["lead_id"], template_name)

    # Persist conversation + message
    try:
        conv = get_or_create_conversation(enrollment["lead_id"], channel["id"])
        update_conversation(conv["id"], status="template_sent")
        rendered = await _render_template_body(template_name, template_variables, lead, channel)
        save_message(conv["id"], enrollment["lead_id"], "assistant", rendered, sent_by="campaign", wamid=wamid)
    except Exception as e:
        logger.warning("[CAMPAIGNS] Could not persist conversation for %s: %s", lead["phone"], e)

    # Update ai_enabled
    try:
        agent_profile_id = cfg.get("agent_profile_id")
        fake_broadcast = {"agent_profile_id": agent_profile_id}
        ai_enabled = _broadcast_ai_enabled(fake_broadcast, channel)
        update_lead(enrollment["lead_id"], ai_enabled=ai_enabled)
    except Exception as e:
        logger.warning("[CAMPAIGNS] Could not update ai_enabled for %s: %s", lead["phone"], e)

    logger.info("[CAMPAIGNS] Sent template '%s' to %s", template_name, lead["phone"])


def _execute_condition_node(enrollment: dict, node: dict, lead: dict, now: datetime) -> None:
    from app.db.supabase import get_supabase
    cfg = node["config"]
    cond = cfg.get("condition_type", "replied_recently")
    result = False

    if cond == "replied_recently":
        days = cfg.get("days", 5)
        cutoff = (now - timedelta(days=days)).isoformat()
        sb = get_supabase()
        msgs = sb.table("messages").select("id").eq("lead_id", enrollment["lead_id"]).eq("role", "user").gte("created_at", cutoff).limit(1).execute()
        result = len(msgs.data) > 0

    elif cond == "in_stage":
        result = lead.get("stage") == cfg.get("stage")

    elif cond == "has_deal":
        sb = get_supabase()
        deals = sb.table("deals").select("id").eq("lead_id", enrollment["lead_id"]).limit(1).execute()
        result = len(deals.data) > 0

    next_node_id = node["yes_node_id"] if result else node["no_node_id"]
    if next_node_id:
        update_enrollment(enrollment["id"], current_node_id=next_node_id, next_execute_at=now.isoformat())
    else:
        complete_enrollment(enrollment["id"])

    logger.info("[CAMPAIGNS] Condition '%s' for %s → %s", cond, lead["phone"], "YES" if result else "NO")


def _execute_action_node(enrollment: dict, node: dict, lead: dict) -> None:
    from app.db.supabase import get_supabase
    cfg = node["config"]
    action_type = cfg.get("action_type")
    sb = get_supabase()

    if action_type == "move_stage":
        stage_id = cfg.get("stage_id")
        if stage_id:
            stage_row = sb.table("pipeline_stages").select("pipeline_id, label").eq("id", stage_id).limit(1).execute().data
            if stage_row:
                sb.table("deals").update({"stage_id": stage_id}).eq("lead_id", enrollment["lead_id"]).execute()

    elif action_type == "activate_agent":
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], ai_enabled=True, human_control=False)

    elif action_type == "deactivate_agent":
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], ai_enabled=False)

    logger.info("[CAMPAIGNS] Action '%s' executed for lead %s", action_type, lead["phone"])


def _execute_end_node(enrollment: dict, node: dict, lead: dict) -> None:
    cfg = node.get("config", {})
    for action in cfg.get("final_actions", []):
        fake_node = {"config": action, "type": "action"}
        _execute_action_node(enrollment, fake_node, lead)
    logger.info("[CAMPAIGNS] Enrollment %s completed (end node)", enrollment["id"])


def handle_campaign_reply(lead_id: str) -> None:
    """Called by webhook when a lead sends a message. Pauses (or cancels) the
    active enrollment regardless of which node it is currently parked on.

    Previously this only acted when the current node was `send`; enrollments
    sitting in `wait` / `condition` / `action` ignored the reply and would
    advance to the next `send`, mailing the lead despite engagement. We now
    treat any inbound message as a signal to pause; the seller can resume
    manually if needed. on_reply='cancel' is still honored on `send` nodes.
    """
    from app.campaigns.service import get_active_enrollment_for_lead
    enrollment = get_active_enrollment_for_lead(lead_id)
    if not enrollment:
        return
    node = enrollment.get("campaign_nodes") or {}
    on_reply = (node.get("config") or {}).get("on_reply", "pause")
    if node.get("type") == "send" and on_reply == "cancel":
        cancel_enrollment(enrollment["id"])
        logger.info(
            "[CAMPAIGNS] Cancelled enrollment %s — lead replied (on_reply=cancel)",
            enrollment["id"],
        )
        return
    pause_enrollment(enrollment["id"])
    logger.info(
        "[CAMPAIGNS] Paused enrollment %s — lead replied (node_type=%s)",
        enrollment["id"], node.get("type"),
    )

import logging
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase
from app.campaigns.service import (
    get_campaigns_with_trigger_type,
    is_already_enrolled,
    create_enrollment,
)
from app.automation import engine as _engine

logger = logging.getLogger(__name__)


def _get_env_tag() -> str:
    try:
        from app.config import settings
        return "dev" if getattr(settings, "is_dev_env", False) else "production"
    except Exception:
        return "production"


async def fire_trigger(event_type: str, lead_id: str, data: dict | None = None) -> None:
    """Event-driven: enroll lead in all active campaigns with matching trigger."""
    try:
        data = data or {}
        now = datetime.now(timezone.utc)

        if event_type == "message_received":
            message_body = (data.get("body") or "").lower()
            for tn in get_campaigns_with_trigger_type("keyword_received"):
                cfg = tn.get("config") or {}
                keywords = [k.lower() for k in (cfg.get("keywords") or []) if k]
                if not keywords or not any(k in message_body for k in keywords):
                    continue
                if is_already_enrolled(tn["campaign_id"], lead_id) or not tn.get("next_node_id"):
                    continue
                if _engine._conversation_followup_disabled(lead_id, tn.get("channel_id")):
                    logger.info("[AUTOMATION] keyword_received: conversation finalized — skip enrollment for lead %s", lead_id)
                    continue
                try:
                    create_enrollment(
                        campaign_id=tn["campaign_id"],
                        lead_id=lead_id,
                        current_node_id=tn["next_node_id"],
                        next_execute_at=now,
                    )
                    logger.info("[AUTOMATION] Enrolled %s via keyword_received", lead_id)
                except Exception as enroll_err:
                    logger.warning("[AUTOMATION] Failed to enroll %s via keyword_received: %s", lead_id, enroll_err)
            return

        for trigger_node in get_campaigns_with_trigger_type(event_type):
            if not _passes_filter(event_type, trigger_node.get("config") or {}, data):
                continue
            if is_already_enrolled(trigger_node["campaign_id"], lead_id):
                continue
            if not trigger_node.get("next_node_id"):
                continue
            try:
                create_enrollment(
                    campaign_id=trigger_node["campaign_id"],
                    lead_id=lead_id,
                    current_node_id=trigger_node["next_node_id"],
                    next_execute_at=now,
                    deal_id=data.get("deal_id"),
                )
                logger.info("[AUTOMATION] Enrolled %s via %s", lead_id, event_type)
            except Exception as enroll_err:
                logger.warning("[AUTOMATION] Failed to enroll %s via %s: %s", lead_id, event_type, enroll_err)
    except Exception as e:
        logger.error("[AUTOMATION] fire_trigger(%s, lead=%s) failed: %s", event_type, lead_id, e)


def _passes_filter(event_type: str, cfg: dict, data: dict) -> bool:
    if event_type in ("stage_enter", "deal_stage_enter"):
        stage_filter = cfg.get("stage_filter")
        return not stage_filter or data.get("stage") == stage_filter

    if event_type == "sale_created":
        if cfg.get("min_value") and float(data.get("value", 0)) < cfg["min_value"]:
            return False
        if cfg.get("product_filter"):
            if cfg["product_filter"].lower() not in (data.get("product") or "").lower():
                return False
        return True

    if event_type == "tag_added":
        tag_filter = cfg.get("tag_name")
        return not tag_filter or data.get("tag_name") == tag_filter

    return True  # deal_closed_lost, post_broadcast — no additional filter


async def check_polling_triggers(now: datetime | None = None) -> None:
    """Polling: detect inactivity-based conditions and enroll leads."""
    now = now or datetime.now(timezone.utc)
    sb = get_supabase()
    env_tag = _get_env_tag()

    # ── no_message ────────────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("no_message"):
        cfg = tn.get("config") or {}
        days, stage_filter = cfg.get("days", 30), cfg.get("stage_filter")
        cutoff = (now - timedelta(days=days)).isoformat()
        q = sb.table("leads").select("id, phone").eq("ai_enabled", True).lte("last_msg_at", cutoff)
        if stage_filter:
            q = q.eq("stage", stage_filter)
        for lead in q.limit(20).execute().data:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── stage_stagnation ──────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("stage_stagnation"):
        cfg = tn.get("config") or {}
        stage, days = cfg.get("stage_filter"), cfg.get("days", 7)
        if not stage:
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        leads = (
            sb.table("leads").select("id, phone")
            .eq("ai_enabled", True).eq("stage", stage)
            .not_.is_("entered_stage_at", "null").lte("entered_stage_at", cutoff)
            .limit(20).execute().data
        )
        for lead in leads:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── repurchase_window ─────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("repurchase_window"):
        cfg = tn.get("config") or {}
        days = cfg.get("days", 30)
        cutoff = (now - timedelta(days=days)).isoformat()
        results = sb.rpc("get_leads_for_repurchase", {"cutoff_date": cutoff, "p_env_tag": env_tag}).execute().data or []
        for lead in results:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── no_sale_in_stage ──────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("no_sale_in_stage"):
        cfg = tn.get("config") or {}
        stage, days = cfg.get("stage_filter"), cfg.get("days", 7)
        if not stage:
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        results = sb.rpc("get_leads_no_sale_in_stage", {"p_stage": stage, "cutoff_date": cutoff, "p_env_tag": env_tag}).execute().data or []
        for lead in results:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)


def _safe_enroll(trigger_node: dict, lead_id: str, now: datetime) -> None:
    if _engine._conversation_followup_disabled(lead_id, trigger_node.get("channel_id")):
        logger.info("[AUTOMATION] polling: conversation finalized — skip enrollment for lead %s", lead_id)
        return
    try:
        create_enrollment(trigger_node["campaign_id"], lead_id, trigger_node["next_node_id"], now)
        logger.info("[AUTOMATION] polling enrolled %s via %s", lead_id, trigger_node.get("type"))
    except Exception as e:
        logger.warning("[AUTOMATION] polling enroll failed: %s", e)



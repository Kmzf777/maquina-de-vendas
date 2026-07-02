import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta, date

from app.db.supabase import get_supabase
from app.automation.variables import substitute_variables
from app.automation.retry import calculate_next_retry

logger = logging.getLogger(__name__)
BRT_OFFSET = timedelta(hours=-3)


def _get_env_tag() -> str:
    try:
        from app.config import settings
        return "dev" if getattr(settings, "is_dev_env", False) else "production"
    except Exception:
        return "production"


def check_frequency_cap(lead_id: str, cap: int) -> bool:
    sb = get_supabase()
    today = date.today().isoformat()
    result = (
        sb.table("lead_daily_sends")
        .select("count")
        .eq("lead_id", lead_id)
        .eq("date", today)
        .execute()
    )
    current = result.data[0]["count"] if result.data else 0
    return current < cap


def record_daily_send(lead_id: str) -> None:
    sb = get_supabase()
    sb.rpc("increment_daily_send", {
        "p_lead_id": lead_id,
        "p_date": date.today().isoformat(),
    }).execute()


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


def _compare(actual: float, op: str, target: float) -> bool:
    return {
        "gte": actual >= target,
        "lte": actual <= target,
        "gt":  actual > target,
        "lt":  actual < target,
        "eq":  actual == target,
    }.get(op, False)


def _conversation_followup_disabled(lead_id: str, channel_id: str | None) -> bool:
    """True if the lead's conversation in the campaign's channel was finalized
    by the seller (followup_enabled=false). Mirrors the gate the legacy
    follow_up system already respects, so the cadence engine no longer
    disturbs conversations marked as closed via /conversas."""
    if not channel_id:
        return False
    sb = get_supabase()
    rows = (
        sb.table("conversations")
        .select("followup_enabled")
        .eq("lead_id", lead_id)
        .eq("channel_id", channel_id)
        .limit(1)
        .execute()
        .data
    )
    return bool(rows) and not rows[0].get("followup_enabled", True)


def _conversation_window(lead_id: str, channel_id: str | None) -> str | None:
    """Última mensagem do cliente NESTE canal (conversations.last_customer_message_at).

    Fonte da janela de 24h por canal. Retorna None se não há canal ou conversa —
    nesse caso o chamador trata como "sem janela conhecida" (não bloqueia o envio)."""
    if not channel_id:
        return None
    sb = get_supabase()
    rows = (
        sb.table("conversations")
        .select("last_customer_message_at")
        .eq("lead_id", lead_id)
        .eq("channel_id", channel_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0].get("last_customer_message_at") if rows else None


def _resolve_channel(node_cfg: dict, campaign: dict) -> dict:
    """Resolve channel: node override → campaign default → raise."""
    channel_id = node_cfg.get("channel_id") or campaign.get("channel_id")
    if not channel_id:
        raise ValueError("Nenhum canal configurado para este nó nem para a campanha")
    sb = get_supabase()
    rows = sb.table("channels").select("*").eq("id", channel_id).limit(1).execute().data
    if not rows:
        raise ValueError(f"Canal {channel_id} não encontrado")
    return rows[0]


def get_due_enrollments(now: datetime, limit: int = 20) -> list[dict]:
    sb = get_supabase()
    env_tag = _get_env_tag()
    return (
        sb.table("campaign_enrollments")
        .select(
            "*, "
            "leads!inner(id, phone, name, company, stage, ai_enabled, last_customer_message_at, assigned_to), "
            "campaign_nodes!campaign_enrollments_current_node_id_fkey(*), "
            "campaigns!inner(id, name, status, priority, frequency_cap, send_start_hour, send_end_hour, channel_id)"
        )
        .eq("status", "active")
        .eq("env_tag", env_tag)
        .lte("next_execute_at", now.isoformat())
        .limit(limit)
        .execute()
        .data
    )


def _update(enrollment_id: str, **kwargs) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update(kwargs).eq("id", enrollment_id).execute()


def _complete(enrollment_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update({
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", enrollment_id).execute()


def _fail_enrollment(enrollment_id: str, retry_count: int, error: str, now: datetime) -> None:
    next_retry, new_count, final = calculate_next_retry(retry_count, now)
    if final:
        _update(enrollment_id, status="failed", last_error=error[:500])
    else:
        _update(enrollment_id,
                retry_count=new_count,
                last_error=error[:500],
                next_execute_at=next_retry.isoformat(),
                next_retry_at=next_retry.isoformat())


async def process_due_enrollments(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    enrollments = get_due_enrollments(now)
    enrollments.sort(key=lambda e: (e.get("campaigns") or {}).get("priority", 5), reverse=True)
    for enrollment in enrollments:
        await _process_one(enrollment, now)
        await asyncio.sleep(random.randint(1, 3))


async def _process_one(enrollment: dict, now: datetime) -> None:
    node = enrollment.get("campaign_nodes")
    lead = enrollment["leads"]
    campaign = enrollment.get("campaigns") or {}

    if not node or campaign.get("status") != "active":
        return
    if not lead.get("ai_enabled", True):
        return

    # Gate: respect "Finalizar Conversa" toggle set by the seller in /conversas.
    # Pause (not cancel) so the seller can resume by re-enabling the conversation.
    if _conversation_followup_disabled(lead["id"], campaign.get("channel_id")):
        logger.info(
            "[AUTOMATION] enrollment=%s — conversation finalized, pausing",
            enrollment["id"],
        )
        _update(
            enrollment["id"],
            status="paused",
            last_error="conversation_finalized",
        )
        return

    node_type = node["type"]
    cfg = node.get("config") or {}

    try:
        if node_type in ("send", "send_text"):
            start_h = campaign.get("send_start_hour", 7)
            end_h   = campaign.get("send_end_hour", 18)
            if not _is_within_window(now, start_h, end_h):
                _update(enrollment["id"], next_execute_at=_next_window_start(now, start_h).isoformat())
                return
            if not check_frequency_cap(lead["id"], campaign.get("frequency_cap", 1)):
                _update(enrollment["id"], next_execute_at=_next_window_start(now, start_h).isoformat())
                return
            if node_type == "send":
                await _execute_send(enrollment, node, lead, now, campaign)
            else:
                await _execute_send_text(enrollment, node, lead, now, campaign)
            record_daily_send(lead["id"])

        elif node_type == "wait":
            days    = cfg.get("days", 1)
            start_h = cfg.get("send_start_hour", 7)
            end_h   = cfg.get("send_end_hour", 18)
            target  = now + timedelta(days=days)
            if not _is_within_window(target, start_h, end_h):
                target = _next_window_start(target, start_h)
            _update(enrollment["id"], next_execute_at=target.isoformat())
            return

        elif node_type == "condition":
            _execute_condition(enrollment, node, lead, now)
            return

        elif node_type == "action":
            _execute_action(enrollment, node, lead)

        elif node_type == "end":
            _execute_end(enrollment, node, lead)
            _complete(enrollment["id"])
            return

        next_id = node.get("next_node_id")
        if next_id:
            _update(enrollment["id"],
                    current_node_id=next_id,
                    next_execute_at=now.isoformat(),
                    retry_count=0,
                    last_error=None)
        else:
            _complete(enrollment["id"])

    except Exception as e:
        logger.error("[AUTOMATION] enrollment=%s node=%s error=%s",
                     enrollment["id"], node.get("id"), e, exc_info=True)
        _fail_enrollment(enrollment["id"], enrollment.get("retry_count", 0), str(e), now)


async def _execute_send(enrollment: dict, node: dict, lead: dict, now: datetime, campaign: dict | None = None) -> None:
    from app.campaigns.worker import _execute_send_node
    campaign = campaign or {}
    node_with_channel = dict(node)
    cfg = dict(node_with_channel.get("config") or {})
    if not cfg.get("channel_id") and campaign.get("channel_id"):
        cfg["channel_id"] = campaign["channel_id"]
    node_with_channel["config"] = cfg
    await _execute_send_node(enrollment, node_with_channel, lead, now)


async def _execute_send_text(enrollment: dict, node: dict, lead: dict, now: datetime, campaign: dict | None = None) -> None:
    from app.whatsapp.registry import get_provider
    from app.leads.service import save_message

    cfg = node.get("config") or {}
    campaign = campaign or {}

    # Janela de 24h POR CANAL: a fonte é a conversa (lead+canal) deste envio, não o
    # campo global do lead. Um lead pode ter a janela aberta em outro canal.
    channel_id = cfg.get("channel_id") or campaign.get("channel_id")
    last_msg = _conversation_window(enrollment["lead_id"], channel_id)
    if last_msg:
        from dateutil.parser import parse
        if isinstance(last_msg, str):
            last_msg = parse(last_msg)
        if (now - last_msg).total_seconds() > 86400:
            _update(enrollment["id"], last_error="24h_window_expired")
            return

    message = substitute_variables(cfg.get("message_text", ""), lead, enrollment)
    channel = _resolve_channel(cfg, campaign)

    provider = get_provider(channel)
    await provider.send_text(lead["phone"], message)

    save_message(
        lead_id=enrollment["lead_id"],
        role="assistant",
        content=message,
        stage=lead.get("stage"),
        sent_by="automation",
    )
    logger.info("[AUTOMATION] send_text → %s", lead["phone"])


def _execute_condition(enrollment: dict, node: dict, lead: dict, now: datetime) -> None:
    sb = get_supabase()
    cfg = node.get("config") or {}
    cond = cfg.get("condition_type", "replied_recently")
    result = False

    if cond == "replied_recently":
        cutoff = (now - timedelta(days=cfg.get("days", 5))).isoformat()
        msgs = sb.table("messages").select("id").eq("lead_id", enrollment["lead_id"]).eq("role", "user").gte("created_at", cutoff).limit(1).execute()
        result = len(msgs.data) > 0

    elif cond == "in_stage":
        fresh = sb.table("leads").select("stage").eq("id", enrollment["lead_id"]).single().execute().data
        result = (fresh or {}).get("stage") == cfg.get("stage")

    elif cond == "has_deal":
        result = bool(sb.table("deals").select("id").eq("lead_id", enrollment["lead_id"]).limit(1).execute().data)

    elif cond == "sale_count":
        res = sb.table("sales").select("id", count="exact").eq("lead_id", enrollment["lead_id"]).execute()
        result = _compare(res.count or 0, cfg.get("operator", "gte"), cfg.get("value", 1))

    elif cond == "total_spend":
        rows = sb.table("sales").select("value").eq("lead_id", enrollment["lead_id"]).execute().data or []
        total = sum(float(r["value"]) for r in rows)
        result = _compare(total, cfg.get("operator", "gte"), cfg.get("value", 0))

    elif cond == "last_sale_value":
        rows = sb.table("sales").select("value").eq("lead_id", enrollment["lead_id"]).order("sold_at", desc=True).limit(1).execute().data
        val = float(rows[0]["value"]) if rows else 0
        result = _compare(val, cfg.get("operator", "gte"), cfg.get("value", 0))

    elif cond == "deal_value":
        rows = sb.table("deals").select("value").eq("lead_id", enrollment["lead_id"]).order("created_at", desc=True).limit(1).execute().data
        val = float(rows[0]["value"]) if rows else 0
        result = _compare(val, cfg.get("operator", "gte"), cfg.get("value", 0))

    elif cond == "has_tag":
        tag_name = cfg.get("tag_name", "")
        tag_row = sb.table("tags").select("id").eq("name", tag_name).limit(1).execute().data
        if tag_row:
            lt = sb.table("lead_tags").select("id").eq("lead_id", enrollment["lead_id"]).eq("tag_id", tag_row[0]["id"]).limit(1).execute()
            result = bool(lt.data)

    elif cond == "repurchase_days":
        rows = sb.table("sales").select("sold_at").eq("lead_id", enrollment["lead_id"]).order("sold_at", desc=True).limit(1).execute().data
        if rows:
            from dateutil.parser import parse
            sold_at = parse(rows[0]["sold_at"]) if isinstance(rows[0]["sold_at"], str) else rows[0]["sold_at"]
            days_since = (now - sold_at).days
            result = _compare(days_since, cfg.get("operator", "gte"), cfg.get("value", 30))

    next_node_id = node["yes_node_id"] if result else node["no_node_id"]
    if next_node_id:
        _update(enrollment["id"], current_node_id=next_node_id, next_execute_at=now.isoformat())
    else:
        _complete(enrollment["id"])
    logger.info("[AUTOMATION] condition '%s' → %s for %s", cond, "YES" if result else "NO", lead["phone"])


def _execute_action(enrollment: dict, node: dict, lead: dict) -> None:
    sb = get_supabase()
    cfg = node.get("config") or {}
    action_type = cfg.get("action_type")

    if action_type == "move_stage":
        # Move the LEAD in the lead-Kanban (leads.stage is a TEXT name, not a UUID).
        stage_name = cfg.get("stage") or cfg.get("stage_name")
        if stage_name:
            from app.leads.service import update_lead
            update_lead(enrollment["lead_id"], stage=stage_name)

    elif action_type == "activate_agent":
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], ai_enabled=True, human_control=False)

    elif action_type == "deactivate_agent":
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], ai_enabled=False)

    elif action_type == "add_tag":
        tag_name = (cfg.get("tag_name") or "").strip()
        if tag_name:
            tag_row = sb.table("tags").select("id").eq("name", tag_name).limit(1).execute().data
            if tag_row:
                try:
                    sb.table("lead_tags").insert({"lead_id": enrollment["lead_id"], "tag_id": tag_row[0]["id"]}).execute()
                except Exception:
                    pass

    elif action_type == "remove_tag":
        tag_name = (cfg.get("tag_name") or "").strip()
        if tag_name:
            tag_row = sb.table("tags").select("id").eq("name", tag_name).limit(1).execute().data
            if tag_row:
                sb.table("lead_tags").delete().eq("lead_id", enrollment["lead_id"]).eq("tag_id", tag_row[0]["id"]).execute()

    elif action_type == "create_deal":
        from app.leads.service import create_deal
        title = substitute_variables(cfg.get("title_template", "Deal automático"), lead, enrollment)
        create_deal(enrollment["lead_id"], title, cfg.get("category"))

    elif action_type == "assign_to":
        user_id = cfg.get("user_id")
        if user_id:
            from app.leads.service import update_lead
            update_lead(enrollment["lead_id"], assigned_to=user_id)

    elif action_type in ("mark_deal_won", "mark_deal_lost", "move_deal_stage"):
        stage_id = cfg.get("stage_id")
        if not stage_id:
            return
        rows = (
            sb.table("deals")
            .select("id")
            .eq("lead_id", enrollment["lead_id"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            sb.table("deals").update({"stage_id": stage_id}).eq("id", rows[0]["id"]).execute()
            # Venda confirmada → dispara conversão outbound (Meta CAPI / Google). Fail-soft:
            # uma falha de disparo nunca pode interromper a automação. Disparo é no-op se
            # não houver credenciais nem click id (ctwa_clid/fbclid/gclid) no lead.
            if action_type == "mark_deal_won":
                try:
                    from app.campaigns.conversions import fire_stage_conversion_background
                    from app.leads.service import get_lead
                    lead_row = get_lead(enrollment["lead_id"]) or {}
                    fire_stage_conversion_background(
                        lead_row, rows[0]["id"], "purchase", value=cfg.get("value")
                    )
                except Exception as exc:
                    logger.warning("[AUTOMATION] mark_deal_won: falha ao disparar conversão: %s", exc)

    elif action_type == "add_note":
        template = cfg.get("note_template") or ""
        if template:
            content = substitute_variables(template, lead, enrollment)
            sb.table("lead_notes").insert({
                "lead_id": enrollment["lead_id"],
                "content": content,
            }).execute()

    elif action_type == "assign_round_robin":
        user_ids = cfg.get("user_ids") or []
        campaign_id = enrollment.get("campaign_id")
        if not user_ids or not campaign_id:
            return
        camp = (
            sb.table("campaigns")
            .select("last_assigned_index")
            .eq("id", campaign_id)
            .single()
            .execute()
            .data
        ) or {}
        last_idx = camp.get("last_assigned_index", -1)
        next_idx = (last_idx + 1) % len(user_ids)
        next_user = user_ids[next_idx]
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], assigned_to=next_user)
        sb.table("campaigns").update({"last_assigned_index": next_idx}).eq("id", campaign_id).execute()

    logger.info("[AUTOMATION] action '%s' for %s", action_type, lead.get("phone"))


def _execute_end(enrollment: dict, node: dict, lead: dict) -> None:
    for action_cfg in (node.get("config") or {}).get("final_actions", []):
        fake_node = {"config": action_cfg, "type": "action"}
        _execute_action(enrollment, fake_node, lead)

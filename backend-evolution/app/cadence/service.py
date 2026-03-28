from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase


def create_cadence_state(
    lead_id: str,
    campaign_id: str,
    max_messages: int = 8,
    next_send_at: datetime | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    data = {
        "lead_id": lead_id,
        "campaign_id": campaign_id,
        "status": "active",
        "current_step": 0,
        "total_messages_sent": 0,
        "max_messages": max_messages,
        "next_send_at": next_send_at.isoformat() if next_send_at else None,
    }
    result = sb.table("cadence_state").insert(data).execute()
    return result.data[0]


def get_cadence_state(lead_id: str, status: str = "active") -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("status", status)
        .execute()
    )
    return result.data[0] if result.data else None


def get_cadence_state_any(lead_id: str) -> dict[str, Any] | None:
    """Get cadence state regardless of status (active or responded)."""
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*")
        .eq("lead_id", lead_id)
        .in_("status", ["active", "responded"])
        .execute()
    )
    return result.data[0] if result.data else None


def pause_cadence(state_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({
            "status": "responded",
            "responded_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def resume_cadence(state_id: str, next_send_at: datetime) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({
            "status": "active",
            "next_send_at": next_send_at.isoformat(),
            "cooldown_until": None,
        })
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def advance_cadence(
    state_id: str,
    new_step: int,
    total_sent: int,
    next_send_at: datetime,
) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({
            "current_step": new_step,
            "total_messages_sent": total_sent,
            "next_send_at": next_send_at.isoformat(),
        })
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def exhaust_cadence(state_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({"status": "exhausted"})
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def cool_cadence(state_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .update({"status": "cooled"})
        .eq("id", state_id)
        .execute()
    )
    return result.data[0]


def get_next_step(campaign_id: str, stage: str, step_order: int) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("stage", stage)
        .eq("step_order", step_order)
        .execute()
    )
    return result.data[0] if result.data else None


def get_due_cadences(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*, leads!inner(phone, stage, human_control), campaigns!inner(status, cadence_send_start_hour, cadence_send_end_hour, cadence_interval_hours)")
        .eq("status", "active")
        .lte("next_send_at", now.isoformat())
        .limit(limit)
        .execute()
    )
    return result.data


def get_reengagement_cadences(now: datetime) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*, leads!inner(phone, last_msg_at, human_control), campaigns!inner(status, cadence_cooldown_hours)")
        .eq("status", "responded")
        .lte("responded_at", now.isoformat())
        .execute()
    )
    return result.data

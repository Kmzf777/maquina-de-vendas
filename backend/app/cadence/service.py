from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase

import os
_ENV_TAG = "dev" if os.environ.get("IS_DEV_ENV") == "true" else "production"


def create_enrollment(
    cadence_id: str,
    lead_id: str,
    deal_id: str | None = None,
    broadcast_id: str | None = None,
    next_send_at: datetime | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    cadence = sb.table("cadences").select("env_tag").eq("id", cadence_id).single().execute().data
    if cadence and cadence.get("env_tag") != _ENV_TAG:
        raise ValueError(
            f"env_tag mismatch: cadence='{cadence.get('env_tag')}', current env='{_ENV_TAG}'"
        )
    data = {
        "cadence_id": cadence_id,
        "lead_id": lead_id,
        "status": "active",
        "current_step": 0,
        "total_messages_sent": 0,
        "next_send_at": next_send_at.isoformat() if next_send_at else None,
        "env_tag": _ENV_TAG,
    }
    if deal_id:
        data["deal_id"] = deal_id
    if broadcast_id:
        data["broadcast_id"] = broadcast_id
    result = sb.table("cadence_enrollments").insert(data).execute()
    return result.data[0]


def get_active_enrollment(lead_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("*, cadences!inner(id, name, cooldown_hours)")
        .eq("lead_id", lead_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def pause_enrollment(enrollment_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "status": "responded",
            "responded_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def resume_enrollment(enrollment_id: str, next_send_at: datetime) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "status": "active",
            "current_step": 0,
            "next_send_at": next_send_at.isoformat(),
            "cooldown_until": None,
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def advance_enrollment(
    enrollment_id: str,
    new_step: int,
    total_sent: int,
    next_send_at: datetime,
) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "current_step": new_step,
            "total_messages_sent": total_sent,
            "next_send_at": next_send_at.isoformat(),
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def exhaust_enrollment(enrollment_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "status": "exhausted",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def complete_enrollment(enrollment_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", enrollment_id)
        .execute()
    )
    return result.data[0]


def get_next_step(cadence_id: str, step_order: int) -> dict[str, Any] | None:
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .select("*")
        .eq("cadence_id", cadence_id)
        .eq("step_order", step_order)
        .execute()
    )
    return result.data[0] if result.data else None


def get_due_enrollments(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("*, leads!inner(phone, stage, human_control, name, company), cadences!inner(id, name, send_start_hour, send_end_hour, max_messages, status)")
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .lte("next_send_at", now.isoformat())
        .limit(limit)
        .execute()
    )
    return result.data


def get_reengagement_enrollments(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("*, leads!inner(phone, last_msg_at, human_control), cadences!inner(id, cooldown_hours, status)")
        .eq("status", "responded")
        .eq("env_tag", _ENV_TAG)
        .lte("responded_at", now.isoformat())
        .limit(limit)
        .execute()
    )
    return result.data


def get_stagnation_cadences() -> list[dict[str, Any]]:
    """Get active cadences that have stagnation triggers configured."""
    sb = get_supabase()
    result = (
        sb.table("cadences")
        .select("*")
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .not_.is_("stagnation_days", "null")
        .execute()
    )
    return result.data


def is_enrolled(cadence_id: str, lead_id: str) -> bool:
    sb = get_supabase()
    result = (
        sb.table("cadence_enrollments")
        .select("id")
        .eq("cadence_id", cadence_id)
        .eq("lead_id", lead_id)
        .in_("status", ["active", "paused", "responded"])
        .limit(1)
        .execute()
    )
    return len(result.data) > 0

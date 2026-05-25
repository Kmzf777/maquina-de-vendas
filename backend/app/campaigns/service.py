from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase
from app.config import get_settings

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"


# ─── Campaigns ────────────────────────────────────────────────────────────────

def list_campaigns() -> list[dict[str, Any]]:
    sb = get_supabase()
    return sb.table("campaigns").select("*").eq("env_tag", _ENV_TAG).order("created_at", desc=True).execute().data


def get_campaign(campaign_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("campaigns").select("*").eq("id", campaign_id).single().execute()
    return result.data


def create_campaign(name: str, description: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaigns").insert({
        "name": name,
        "description": description,
        "status": "draft",
        "env_tag": _ENV_TAG,
    }).execute().data[0]


def update_campaign(campaign_id: str, **kwargs) -> dict[str, Any]:
    sb = get_supabase()
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    return sb.table("campaigns").update(kwargs).eq("id", campaign_id).execute().data[0]


def delete_campaign(campaign_id: str) -> None:
    sb = get_supabase()
    sb.table("campaigns").delete().eq("id", campaign_id).execute()


# ─── Nodes ────────────────────────────────────────────────────────────────────

def list_nodes(campaign_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    return sb.table("campaign_nodes").select("*").eq("campaign_id", campaign_id).execute().data


def create_node(campaign_id: str, type: str, config: dict, position_x: int = 0, position_y: int = 0) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaign_nodes").insert({
        "campaign_id": campaign_id,
        "type": type,
        "config": config,
        "position_x": position_x,
        "position_y": position_y,
    }).execute().data[0]


def update_node(node_id: str, **kwargs) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaign_nodes").update(kwargs).eq("id", node_id).execute().data[0]


def delete_node(node_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_nodes").delete().eq("id", node_id).execute()


# ─── Enrollments ──────────────────────────────────────────────────────────────

def list_enrollments(campaign_id: str, status: str | None = None) -> list[dict[str, Any]]:
    sb = get_supabase()
    q = sb.table("campaign_enrollments").select("*, leads!inner(id, name, phone, stage)").eq("campaign_id", campaign_id)
    if status:
        q = q.eq("status", status)
    return q.order("enrolled_at", desc=True).execute().data


def create_enrollment(campaign_id: str, lead_id: str, current_node_id: str, next_execute_at: datetime, deal_id: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaign_enrollments").insert({
        "campaign_id": campaign_id,
        "lead_id": lead_id,
        "deal_id": deal_id,
        "current_node_id": current_node_id,
        "next_execute_at": next_execute_at.isoformat(),
        "env_tag": _ENV_TAG,
    }).execute().data[0]


def get_due_enrollments(now: datetime, limit: int = 20) -> list[dict[str, Any]]:
    sb = get_supabase()
    return (
        sb.table("campaign_enrollments")
        .select("*, leads!inner(id, phone, name, company, stage, ai_enabled), campaign_nodes!campaign_enrollments_current_node_id_fkey(*)")
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .lte("next_execute_at", now.isoformat())
        .limit(limit)
        .execute()
        .data
    )


def update_enrollment(enrollment_id: str, **kwargs) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaign_enrollments").update(kwargs).eq("id", enrollment_id).execute().data[0]


def complete_enrollment(enrollment_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update({
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", enrollment_id).execute()


def cancel_enrollment(enrollment_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update({"status": "cancelled"}).eq("id", enrollment_id).execute()


def pause_enrollment(enrollment_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update({
        "status": "paused",
        "paused_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", enrollment_id).execute()


def get_active_enrollment_for_lead(lead_id: str) -> dict[str, Any] | None:
    """Used by webhook to check if incoming reply should affect a campaign."""
    sb = get_supabase()
    result = (
        sb.table("campaign_enrollments")
        .select("*, campaign_nodes!campaign_enrollments_current_node_id_fkey(type, config)")
        .eq("lead_id", lead_id)
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_campaigns_with_trigger_type(trigger_type: str) -> list[dict[str, Any]]:
    """Returns active campaigns that have a trigger node of the given type."""
    sb = get_supabase()
    campaigns = sb.table("campaigns").select("id").eq("status", "active").eq("env_tag", _ENV_TAG).execute().data
    if not campaigns:
        return []
    campaign_ids = [c["id"] for c in campaigns]
    nodes = (
        sb.table("campaign_nodes")
        .select("*, campaigns!inner(id, status, channel_id)")
        .eq("type", "trigger")
        .in_("campaign_id", campaign_ids)
        .execute()
        .data
    )
    # Flatten channel_id onto the node so trigger callers can gate enrollment
    # by the lead's conversation followup_enabled in that channel.
    out = []
    for n in nodes:
        if n["config"].get("trigger_type") == trigger_type:
            n["channel_id"] = (n.get("campaigns") or {}).get("channel_id")
            out.append(n)
    return out


def is_already_enrolled(campaign_id: str, lead_id: str) -> bool:
    sb = get_supabase()
    result = (
        sb.table("campaign_enrollments")
        .select("id")
        .eq("campaign_id", campaign_id)
        .eq("lead_id", lead_id)
        .in_("status", ["active", "paused"])
        .limit(1)
        .execute()
    )
    return len(result.data) > 0

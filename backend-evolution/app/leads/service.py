from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase


def get_or_create_lead(phone: str) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("phone", phone).execute()

    if result.data:
        return result.data[0]

    new_lead = {"phone": phone, "stage": "pending", "status": "imported"}
    result = sb.table("leads").insert(new_lead).execute()
    return result.data[0]


def update_lead(lead_id: str, **fields) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").update(fields).eq("id", lead_id).execute()
    return result.data[0]


def activate_lead(lead_id: str) -> dict[str, Any]:
    return update_lead(
        lead_id,
        status="active",
        stage="secretaria",
        last_msg_at=datetime.now(timezone.utc).isoformat(),
    )


def save_message(lead_id: str, role: str, content: str, stage: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    msg = {
        "lead_id": lead_id,
        "role": role,
        "content": content,
        "stage": stage,
    }
    result = sb.table("messages").insert(msg).execute()
    return result.data[0]


def get_history(lead_id: str, limit: int = 30) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("role, content, stage, created_at")
        .eq("lead_id", lead_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data

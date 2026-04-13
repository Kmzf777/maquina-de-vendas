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


def reset_lead(lead_id: str) -> None:
    """Reset lead: delete message history and reset stage to secretaria."""
    sb = get_supabase()
    sb.table("messages").delete().eq("lead_id", lead_id).execute()
    sb.table("leads").update({
        "stage": "secretaria",
        "status": "active",
    }).eq("id", lead_id).execute()


def save_message(lead_id: str, role: str, content: str, stage: str | None = None, sent_by: str = "agent", conversation_id: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    msg = {
        "lead_id": lead_id,
        "role": role,
        "content": content,
        "stage": stage,
        "sent_by": sent_by,
    }
    if conversation_id:
        msg["conversation_id"] = conversation_id
    result = sb.table("messages").insert(msg).execute()
    return result.data[0]


def create_deal(lead_id: str, title: str, category: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    deal = {
        "lead_id": lead_id,
        "title": title,
        "stage": "novo",
        "category": category,
    }
    result = sb.table("deals").insert(deal).execute()
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

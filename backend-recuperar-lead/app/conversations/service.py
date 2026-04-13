from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase


def get_or_create_conversation(lead_id: str, channel_id: str) -> dict[str, Any]:
    """Get existing conversation or create new one for lead+channel pair."""
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("channel_id", channel_id)
        .execute()
    )

    if result.data:
        return result.data[0]

    new_conv = {
        "lead_id": lead_id,
        "channel_id": channel_id,
        "stage": "secretaria",
        "status": "active",
    }
    result = sb.table("conversations").insert(new_conv).execute()
    return result.data[0]


def get_conversation(conversation_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("*, leads(*), channels(id, name, phone, provider)")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    return result.data


def list_conversations(
    channel_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    query = (
        sb.table("conversations")
        .select("*, leads(id, phone, name, company), channels(id, name, phone, provider)")
    )

    if channel_id:
        query = query.eq("channel_id", channel_id)
    if status:
        query = query.eq("status", status)

    result = (
        query.order("last_msg_at", desc=True, nullsfirst=False)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return result.data


def update_conversation(conversation_id: str, **fields) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .update(fields)
        .eq("id", conversation_id)
        .execute()
    )
    return result.data[0]


def activate_conversation(conversation_id: str) -> dict[str, Any]:
    """Activate a conversation (when lead first responds)."""
    return update_conversation(
        conversation_id,
        status="active",
        stage="secretaria",
        last_msg_at=datetime.now(timezone.utc).isoformat(),
    )


def save_message(
    conversation_id: str,
    lead_id: str,
    role: str,
    content: str,
    stage: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    msg = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "role": role,
        "content": content,
        "stage": stage,
    }
    result = sb.table("messages").insert(msg).execute()
    return result.data[0]


def get_history(conversation_id: str, limit: int = 30) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("role, content, stage, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data

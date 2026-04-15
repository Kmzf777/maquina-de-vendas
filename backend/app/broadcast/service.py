from typing import Any
from app.db.supabase import get_supabase


def get_broadcast(broadcast_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("broadcasts").select("*").eq("id", broadcast_id).single().execute()
    return result.data


def get_pending_broadcast_leads(broadcast_id: str, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("broadcast_leads")
        .select("*, leads!inner(id, phone, stage)")
        .eq("broadcast_id", broadcast_id)
        .eq("status", "pending")
        .limit(limit)
        .execute()
    )
    return result.data


def mark_broadcast_lead_sent(bl_id: str) -> None:
    from datetime import datetime, timezone
    sb = get_supabase()
    sb.table("broadcast_leads").update({
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", bl_id).execute()


def mark_broadcast_lead_failed(bl_id: str, error: str) -> None:
    sb = get_supabase()
    sb.table("broadcast_leads").update({
        "status": "failed",
        "error_message": error,
    }).eq("id", bl_id).execute()


def increment_broadcast_sent(broadcast_id: str) -> None:
    sb = get_supabase()
    broadcast = sb.table("broadcasts").select("sent").eq("id", broadcast_id).single().execute().data
    sb.table("broadcasts").update({"sent": broadcast["sent"] + 1}).eq("id", broadcast_id).execute()


def increment_broadcast_failed(broadcast_id: str) -> None:
    sb = get_supabase()
    broadcast = sb.table("broadcasts").select("failed").eq("id", broadcast_id).single().execute().data
    sb.table("broadcasts").update({"failed": broadcast["failed"] + 1}).eq("id", broadcast_id).execute()

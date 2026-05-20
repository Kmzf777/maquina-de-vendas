import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def get_broadcast(broadcast_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("broadcasts").select("*").eq("id", broadcast_id).single().execute()
    return result.data


def get_pending_broadcast_leads(broadcast_id: str, limit: int = 10) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("broadcast_leads")
        .select("*, leads!inner(id, phone, stage, name)")
        .eq("broadcast_id", broadcast_id)
        .eq("status", "pending")
        .limit(limit)
        .execute()
    )
    return result.data


def mark_broadcast_lead_sent(bl_id: str) -> None:
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
    sb.rpc("increment_broadcast_sent", {"broadcast_id_param": broadcast_id}).execute()


def increment_broadcast_failed(broadcast_id: str) -> None:
    sb = get_supabase()
    sb.rpc("increment_broadcast_failed", {"broadcast_id_param": broadcast_id}).execute()


def save_broadcast_lead_wamid(bl_id: str, wamid: str) -> None:
    sb = get_supabase()
    sb.table("broadcast_leads").update({"wamid": wamid}).eq("id", bl_id).execute()


def find_broadcast_lead_by_wamid(wamid: str) -> dict | None:
    sb = get_supabase()
    result = (
        sb.table("broadcast_leads")
        .select("id, broadcast_id, delivered_at")
        .eq("wamid", wamid)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def mark_broadcast_lead_delivered(bl_id: str) -> bool:
    """Atomically mark bl as delivered only if not already marked.

    Returns True if the row was updated (first delivery), False if already
    delivered (duplicate webhook). Caller must only increment the counter
    when this returns True.
    """
    sb = get_supabase()
    result = sb.table("broadcast_leads").update({
        "status": "delivered",
        "delivered_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", bl_id).is_("delivered_at", "null").execute()
    return bool(result.data)


def increment_broadcast_delivered(broadcast_id: str) -> None:
    sb = get_supabase()
    sb.rpc("increment_broadcast_delivered", {"broadcast_id_param": broadcast_id}).execute()


def record_broadcast_reply(lead_id: str) -> None:
    """Marks the most recent active broadcast_lead for this lead as replied (48h window).

    Idempotent: if first_replied_at is already set, the query returns no rows
    and no update is made.
    """
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    result = (
        sb.table("broadcast_leads")
        .select("id")
        .eq("lead_id", lead_id)
        .in_("status", ["sent", "delivered"])
        .is_("first_replied_at", "null")
        .gte("sent_at", cutoff)
        .order("sent_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        bl_id = result.data[0]["id"]
        sb.table("broadcast_leads").update({
            "first_replied_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bl_id).execute()
        logger.info(
            "[BROADCAST] Resposta registrada: lead=%s broadcast_lead=%s",
            lead_id, bl_id,
        )
    else:
        logger.debug(
            "[BROADCAST] Nenhum broadcast_lead ativo encontrado para resposta do lead=%s",
            lead_id,
        )

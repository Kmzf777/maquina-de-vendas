"""Supabase helpers for the rehearsal runner.

Reuses the backend's Supabase client (service-role credentials already configured).
"""
import logging
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def get_lead_by_phone(phone: str) -> dict | None:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("phone", phone).execute()
    return result.data[0] if result.data else None


def wipe_lead(phone: str) -> None:
    """Delete lead and all related rows. Safe to call when no lead exists."""
    sb = get_supabase()
    lead = get_lead_by_phone(phone)
    if not lead:
        logger.info(f"wipe_lead: no lead for {phone}, nothing to delete")
        return
    lead_id = lead["id"]
    # Order matters due to foreign keys: children first
    for table in ("messages", "conversations", "deals"):
        sb.table(table).delete().eq("lead_id", lead_id).execute()
    sb.table("leads").delete().eq("id", lead_id).execute()
    logger.info(f"wipe_lead: deleted lead {lead_id} (phone={phone})")


def get_messages_since(lead_id: str, since_iso: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("id, role, content, stage, created_at")
        .eq("lead_id", lead_id)
        .gt("created_at", since_iso)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def get_all_messages(lead_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("id, role, content, stage, created_at")
        .eq("lead_id", lead_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def get_system_events(lead_id: str) -> list[dict[str, Any]]:
    """Return messages with role=system. The orchestrator saves tool effects
    (stage changes, forwarding, pedido registered, photos sent) with role=system,
    so this list is the canonical event log for verification."""
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("id, content, stage, created_at")
        .eq("lead_id", lead_id)
        .eq("role", "system")
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


async def wipe_redis_buffer(phone: str, redis) -> None:
    """Delete all buffer/state Redis keys scoped to this phone number."""
    keys = [
        f"buffer:{phone}",
        f"buffer:{phone}:lock",
        f"buffer:{phone}:deadline",
        f"pushname:{phone}",
        f"channel:{phone}",
    ]
    for key in keys:
        await redis.delete(key)

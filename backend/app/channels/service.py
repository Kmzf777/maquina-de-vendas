import logging
from fastapi import HTTPException
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def list_channels() -> list:
    """Return all channels."""
    sb = get_supabase()
    res = sb.table("channels").select("*, agent_profiles(*)").execute()
    return res.data or []


def get_channel(channel_id: str) -> dict:
    """Get a channel by ID, raising 404 if not found."""
    sb = get_supabase()
    res = (
        sb.table("channels")
        .select("*, agent_profiles(*)")
        .eq("id", channel_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, f"Channel {channel_id} not found")
    return res.data[0]


def create_channel(data: dict) -> dict:
    """Create a new channel."""
    sb = get_supabase()
    res = sb.table("channels").insert(data).execute()
    return res.data[0]


def update_channel(channel_id: str, data: dict) -> dict:
    """Update an existing channel."""
    sb = get_supabase()
    res = sb.table("channels").update(data).eq("id", channel_id).execute()
    if not res.data:
        raise HTTPException(404, f"Channel {channel_id} not found")
    return res.data[0]


def delete_channel(channel_id: str) -> None:
    """Delete a channel."""
    sb = get_supabase()
    sb.table("channels").delete().eq("id", channel_id).execute()


def get_channel_by_phone(phone: str, provider: str) -> dict | None:
    """Find a channel by phone number and provider."""
    sb = get_supabase()
    res = (
        sb.table("channels")
        .select("*, agent_profiles(*)")
        .eq("phone", phone)
        .eq("provider", provider)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_channel_by_provider_config(key: str, value: str, provider: str) -> dict | None:
    """Find a channel by a key inside provider_config JSON."""
    sb = get_supabase()
    res = (
        sb.table("channels")
        .select("*, agent_profiles(*)")
        .eq(f"provider_config->>{key}", value)
        .eq("provider", provider)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_channel_by_id(channel_id: str) -> dict | None:
    """Get a channel by its ID."""
    sb = get_supabase()
    res = (
        sb.table("channels")
        .select("*, agent_profiles(*)")
        .eq("id", channel_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_active_channel() -> dict | None:
    """Get the first active channel (used as default for operations without explicit channel)."""
    sb = get_supabase()
    res = (
        sb.table("channels")
        .select("*")
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def update_channel_phone(channel_id: str, phone: str) -> None:
    """Update a channel's phone number (e.g., after Evolution QR scan)."""
    sb = get_supabase()
    sb.table("channels").update({"phone": phone}).eq("id", channel_id).execute()


def get_channel_for_lead(lead_id: str) -> dict | None:
    """Return the channel associated with a lead's most recent active conversation.

    Returns None if no conversation or channel is found.
    """
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("channel_id, channels!inner(*)")
        .eq("lead_id", lead_id)
        .eq("status", "active")
        .order("last_msg_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]["channels"]

import logging
import os
from fastapi import HTTPException
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def _inject_meta_credentials(config: dict) -> dict:
    """Fill missing Meta Cloud API credentials from global env vars.

    access_token, verify_token, app_secret and waba_id are project-wide
    constants shared across all numbers on the same WABA.
    """
    config = dict(config)
    if not config.get("access_token"):
        config["access_token"] = os.environ.get("META_ACCESS_TOKEN", "")
    if not config.get("verify_token"):
        config["verify_token"] = os.environ.get("META_VERIFY_TOKEN", "")
    if not config.get("app_secret"):
        config["app_secret"] = os.environ.get("META_APP_SECRET", "")
    if not config.get("waba_id"):
        config["waba_id"] = os.environ.get("META_WABA_ID", "")
    return config


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
    if data.get("provider") == "meta_cloud":
        data = {**data, "provider_config": _inject_meta_credentials(data.get("provider_config") or {})}
    sb = get_supabase()
    res = sb.table("channels").insert(data).execute()
    return res.data[0]


def update_channel(channel_id: str, data: dict) -> dict:
    """Update an existing channel."""
    if "provider_config" in data:
        sb = get_supabase()
        existing = sb.table("channels").select("provider").eq("id", channel_id).limit(1).execute()
        if existing.data and existing.data[0].get("provider") == "meta_cloud":
            data = {**data, "provider_config": _inject_meta_credentials(data["provider_config"])}
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

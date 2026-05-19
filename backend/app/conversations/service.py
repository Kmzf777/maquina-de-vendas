import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def _compute_window_expiration(conversation: dict[str, Any]) -> str | None:
    """Retorna ISO da expiração da janela 24h ou None se nunca houve inbound."""
    leads = conversation.get("leads")
    if not leads:
        return None
    last = leads.get("last_customer_message_at")
    if not last:
        return None
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except Exception:
        return None
    return (last_dt + timedelta(hours=24)).isoformat()


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
    data = result.data
    if data:
        data["whatsapp_window_expires_at"] = _compute_window_expiration(data)
    return data


def list_conversations(
    channel_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    query = (
        sb.table("conversations")
        .select(
            "*, "
            "leads(id, phone, name, company, last_customer_message_at), "
            "channels(id, name, phone, provider)"
        )
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
    rows = result.data or []
    for row in rows:
        row["whatsapp_window_expires_at"] = _compute_window_expiration(row)
    return rows


def update_conversation(conversation_id: str, **fields) -> dict[str, Any]:
    sb = get_supabase()
    sb.table("conversations").update(fields).eq("id", conversation_id).execute()
    return {}


def activate_conversation(conversation_id: str) -> dict[str, Any]:
    """Activate a conversation (when lead first responds after template dispatch).
    Does NOT reset stage — preserves existing stage for outbound recovery flows.
    """
    return update_conversation(
        conversation_id,
        status="active",
        last_msg_at=datetime.now(timezone.utc).isoformat(),
    )


def save_message(
    conversation_id: str,
    lead_id: str,
    role: str,
    content: str,
    stage: str | None = None,
    sent_by: str = "agent",
    media_url: str | None = None,
    message_type: str | None = None,
    wamid: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    msg = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "role": role,
        "content": content,
        "stage": stage,
        "sent_by": sent_by,
    }
    if media_url is not None:
        msg["media_url"] = media_url
    if message_type is not None:
        msg["message_type"] = message_type
    if wamid is not None:
        msg["wamid"] = wamid
        msg["delivery_status"] = "sent"
    logger.info(f"[DEBUG-SAVE_MESSAGE] enter payload={msg}")
    try:
        result = sb.table("messages").insert(msg).execute()
    except Exception as e:
        logger.error(f"[DEBUG-SAVE_MESSAGE] insert raised {type(e).__name__}: {e}", exc_info=True)
        raise
    logger.info(f"[DEBUG-SAVE_MESSAGE] insert OK data_len={len(result.data) if result.data else 0} data={result.data}")
    if not result.data:
        logger.error(f"[DEBUG-SAVE_MESSAGE] insert returned empty data — NADA SALVO (payload={msg})")
        return {}

    # Keep conversations.last_msg_at current; zero unread badge on outbound
    try:
        update_fields: dict = {"last_msg_at": datetime.now(timezone.utc).isoformat()}
        if role == "assistant":
            update_fields["unread_count"] = 0
        sb.table("conversations").update(update_fields).eq("id", conversation_id).execute()
    except Exception as e:
        logger.warning(f"[DEBUG-SAVE_MESSAGE] failed to update last_msg_at: {e}")

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


def reset_unread_count(conversation_id: str) -> dict[str, Any]:
    """Zera o contador de mensagens não-lidas. Chamado quando o vendedor abre a conversa."""
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .update({"unread_count": 0})
        .eq("id", conversation_id)
        .select("id, unread_count")
        .execute()
    )
    if not result.data:
        return {}
    return result.data[0]

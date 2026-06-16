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
    conversation = result.data[0]

    # Injeta contexto de qualificação se o lead foi encaminhado pela Valéria
    try:
        lead_result = (
            sb.table("leads")
            .select("metadata")
            .eq("id", lead_id)
            .single()
            .execute()
        )
        lead_meta = (lead_result.data or {}).get("metadata") or {}
        handoff_summary = lead_meta.get("handoff_summary")
        if handoff_summary:
            sb.table("messages").insert({
                "conversation_id": conversation["id"],
                "lead_id": lead_id,
                "role": "system",
                "content": handoff_summary,
                "sent_by": "handoff_context",
                "stage": "secretaria",
            }).execute()
            logger.info(
                "get_or_create_conversation: handoff_context injetado para lead %s conv %s",
                lead_id, conversation["id"],
            )
    except Exception as exc:
        logger.warning(
            "get_or_create_conversation: falha ao injetar handoff_context para lead %s: %s",
            lead_id, exc,
        )

    return conversation


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
    document_name: str | None = None,
    media_mime: str | None = None,
    metadata: dict | None = None,
    quoted_wamid: str | None = None,
    agent_persona: str | None = None,
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
    # Rastreabilidade: persona (prompt_key) que gerou a resposta. NULL p/ não-persona.
    if agent_persona is not None:
        msg["agent_persona"] = agent_persona
    if media_url is not None:
        msg["media_url"] = media_url
    if message_type is not None:
        msg["message_type"] = message_type
    if wamid is not None:
        msg["wamid"] = wamid
        msg["delivery_status"] = "sent"
    if document_name is not None:
        msg["document_name"] = document_name
    if media_mime is not None:
        msg["media_mime"] = media_mime
    if metadata is not None:
        msg["metadata"] = metadata
    if quoted_wamid is not None:
        msg["quoted_wamid"] = quoted_wamid
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


def resolve_message_text_by_wamid(wamid: str) -> str | None:
    """Return the content of a previously stored message by its Meta wamid, or None.

    Fail-open: returns None on any error (missing row, DB hiccup) so callers
    degrade gracefully — they should fall back to a soft marker.
    """
    if not wamid:
        # Empty/None wamid (ex.: reação sem target_wamid) — nada a resolver.
        # Evita query que ignoraria o índice parcial (WHERE wamid IS NOT NULL).
        return None
    try:
        sb = get_supabase()
        result = (
            sb.table("messages")
            .select("content")
            .eq("wamid", wamid)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["content"]
        return None
    except Exception as exc:
        logger.warning(
            "resolve_message_text_by_wamid: falha ao resolver wamid=%s: %s",
            wamid, exc,
        )
        return None


def resolve_message_texts_by_wamids(wamids: list[str]) -> dict[str, str]:
    """Batch-resolve message contents by wamid in a single query.

    Returns {wamid: content} for the wamids that exist. Fail-open: returns the
    partial map gathered so far (or {}) on error. Use this instead of calling
    resolve_message_text_by_wamid in a loop to avoid N sequential round-trips.
    """
    unique = [w for w in {*wamids} if w]
    if not unique:
        return {}
    try:
        sb = get_supabase()
        result = (
            sb.table("messages")
            .select("wamid, content")
            .in_("wamid", unique)
            .execute()
        )
        return {
            row["wamid"]: row["content"]
            for row in (result.data or [])
            if row.get("wamid")
        }
    except Exception as exc:
        logger.warning(
            "resolve_message_texts_by_wamids: falha ao resolver %d wamids: %s",
            len(unique), exc,
        )
        return {}


def get_history(conversation_id: str, limit: int = 30) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("role, content, stage, created_at, wamid, quoted_wamid, message_type, metadata")
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

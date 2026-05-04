import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.config import get_settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"


def schedule_followup(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
) -> None:
    """Cancela jobs pendentes anteriores e cria 2 novos (1h e 23h)."""
    sb = get_supabase()
    now = datetime.now(timezone.utc)

    # Cancela pending da mesma conversa (idempotência)
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": "rescheduled",
    }).eq("conversation_id", conversation_id).eq("status", "pending").execute()

    jobs = [
        {
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": 1,
            "fire_at": (now + timedelta(hours=1)).isoformat(),
            "status": "pending",
            "env_tag": _ENV_TAG,
        },
        {
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": 2,
            "fire_at": (now + timedelta(hours=23)).isoformat(),
            "status": "pending",
            "env_tag": _ENV_TAG,
        },
    ]
    sb.table("follow_up_jobs").insert(jobs).execute()
    logger.info(f"[FOLLOWUP] Agendado seq=1 e seq=2 conversation={conversation_id}")


def cancel_followups(conversation_id: str, reason: str) -> None:
    """Cancela todos os jobs pending de uma conversa."""
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": reason,
    }).eq("conversation_id", conversation_id).eq("status", "pending").execute()
    logger.info(f"[FOLLOWUP] Cancelado reason={reason} conversation={conversation_id}")


def cancel_followups_by_phone(phone: str, reason: str) -> None:
    """Cancela follow-ups pending de todas as conversas de um lead pelo phone."""
    sb = get_supabase()

    lead_result = (
        sb.table("leads")
        .select("id")
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    if not lead_result.data:
        return

    lead_id = lead_result.data[0]["id"]

    conversations = (
        sb.table("conversations")
        .select("id")
        .eq("lead_id", lead_id)
        .execute()
    )
    if not conversations.data:
        return

    conv_ids = [c["id"] for c in conversations.data]
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": reason,
    }).in_("conversation_id", conv_ids).eq("status", "pending").execute()
    logger.info(f"[FOLLOWUP] Cancelado reason={reason} phone={phone}")


def get_due_followups(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    """Retorna jobs pending cujo fire_at já passou."""
    sb = get_supabase()
    result = (
        sb.table("follow_up_jobs")
        .select(
            "*, "
            "leads!inner(id, phone, last_customer_message_at), "
            "channels!inner(id, name, provider, provider_config), "
            "conversations!inner(id, stage, followup_enabled)"
        )
        .eq("status", "pending")
        .eq("env_tag", _ENV_TAG)
        .lte("fire_at", now.isoformat())
        .order("fire_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data

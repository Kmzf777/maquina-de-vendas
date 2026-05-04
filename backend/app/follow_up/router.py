# backend/app/follow_up/router.py
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.follow_up.service import schedule_followup, cancel_followups
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["follow_up"])


class FollowupToggle(BaseModel):
    enabled: bool


@router.patch("/{conversation_id}/followup")
async def toggle_followup(conversation_id: str, body: FollowupToggle):
    """Ativa/desativa follow-up automático para a conversa."""
    sb = get_supabase()

    result = (
        sb.table("conversations")
        .update({"followup_enabled": body.enabled})
        .eq("id", conversation_id)
        .select("id, followup_enabled")
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not body.enabled:
        try:
            cancel_followups(conversation_id, reason="manual")
        except Exception as e:
            logger.error(f"[FOLLOWUP] Falha ao cancelar jobs ao desativar toggle conversation={conversation_id}: {e}")

    return result.data[0]


@router.post("/{conversation_id}/followup/schedule")
async def schedule_followup_for_conversation(conversation_id: str):
    """Agenda follow-ups para a conversa (chamado após vendedor humano enviar mensagem)."""
    sb = get_supabase()

    conv = (
        sb.table("conversations")
        .select("id, lead_id, channel_id, followup_enabled")
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    data = conv.data[0]
    if not data.get("followup_enabled", True):
        return {"status": "skipped", "reason": "followup_disabled"}

    schedule_followup(
        conversation_id=conversation_id,
        lead_id=data["lead_id"],
        channel_id=data["channel_id"],
    )
    return {"status": "scheduled"}

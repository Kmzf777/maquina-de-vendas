from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.conversations.service import reset_unread_count

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class AgentUpdate(BaseModel):
    ai_enabled: bool | None = None
    agent_profile_id: str | None = None


@router.patch("/{conversation_id}/agent")
async def update_conversation_agent(conversation_id: str, body: AgentUpdate):
    """Toggle AI on/off or switch agent profile for a conversation."""
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    sb = get_supabase()

    result = (
        sb.table("conversations")
        .update(data)
        .eq("id", conversation_id)
        .select("id, ai_enabled, agent_profile_id")
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result.data[0]


@router.post("/{conversation_id}/mark-read", status_code=204)
async def mark_conversation_read(conversation_id: str):
    """Zera unread_count da conversa (chamado quando o vendedor abre a conversa)."""
    result = reset_unread_count(conversation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)

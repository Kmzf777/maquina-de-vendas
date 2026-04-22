from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase

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

    # Verify conversation exists
    check = (
        sb.table("conversations")
        .select("id, ai_enabled, agent_profile_id")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    if not check.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = (
        sb.table("conversations")
        .update(data)
        .eq("id", conversation_id)
        .select("id, ai_enabled, agent_profile_id, agent_profiles(id, name)")
        .single()
        .execute()
    )
    return result.data

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.channels.service import (
    list_channels, get_channel, create_channel, update_channel, delete_channel,
)

router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelCreate(BaseModel):
    name: str
    phone: str
    provider: str  # "meta_cloud" | "evolution"
    provider_config: dict
    agent_profile_id: str | None = None


class ChannelUpdate(BaseModel):
    name: str | None = None
    provider_config: dict | None = None
    agent_profile_id: str | None = None
    is_active: bool | None = None


@router.get("")
async def api_list_channels():
    return {"data": list_channels()}


@router.get("/{channel_id}")
async def api_get_channel(channel_id: str):
    return get_channel(channel_id)


@router.post("")
async def api_create_channel(body: ChannelCreate):
    if body.provider not in ("meta_cloud", "evolution"):
        raise HTTPException(400, "Provider must be 'meta_cloud' or 'evolution'")
    return create_channel(body.model_dump(exclude_none=True))


@router.put("/{channel_id}")
async def api_update_channel(channel_id: str, body: ChannelUpdate):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    return update_channel(channel_id, data)


@router.delete("/{channel_id}")
async def api_delete_channel(channel_id: str):
    delete_channel(channel_id)
    return {"status": "deleted"}


class SendMessage(BaseModel):
    conversation_id: str | None = None
    to: str
    text: str


@router.post("/{channel_id}/send")
async def send_message(channel_id: str, body: SendMessage):
    """Send a message through a channel (used by CRM for human chat)."""
    from app.whatsapp.registry import get_provider  # updated import (Task 9)
    from app.conversations.service import save_message

    channel = get_channel(channel_id)
    provider = get_provider(channel)

    await provider.send_text(body.to, body.text)

    if body.conversation_id:
        from app.db.supabase import get_supabase
        sb = get_supabase()
        conv = (
            sb.table("conversations")
            .select("lead_id, stage")
            .eq("id", body.conversation_id)
            .single()
            .execute()
            .data
        )
        save_message(body.conversation_id, conv["lead_id"], "assistant", body.text, conv.get("stage"))

    return {"status": "sent"}

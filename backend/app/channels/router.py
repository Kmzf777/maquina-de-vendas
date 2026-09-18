import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.auth.dependencies import require_role

from app.channels.service import (
    list_channels, get_channel, create_channel, update_channel, delete_channel,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/channels",
    tags=["channels"],
    dependencies=[Depends(require_role(["admin"]))],
)


class ChannelCreate(BaseModel):
    name: str
    phone: str
    provider: str  # "meta_cloud" | "evolution"
    provider_config: dict
    agent_profile_id: str | None = None
    mode: str = "ai"


class ChannelUpdate(BaseModel):
    name: str | None = None
    provider_config: dict | None = None
    agent_profile_id: str | None = None
    is_active: bool | None = None
    mode: str | None = None


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
    if body.mode not in ("ai", "human"):
        raise HTTPException(400, "mode must be 'ai' or 'human'")
    return create_channel(body.model_dump(exclude_none=True))


@router.put("/{channel_id}")
async def api_update_channel(channel_id: str, body: ChannelUpdate):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    if "mode" in data and data["mode"] not in ("ai", "human"):
        raise HTTPException(400, "mode must be 'ai' or 'human'")
    return update_channel(channel_id, data)


@router.delete("/{channel_id}")
async def api_delete_channel(channel_id: str):
    delete_channel(channel_id)
    return {"status": "deleted"}


class SendMessage(BaseModel):
    conversation_id: str | None = None
    to: str
    text: str


def _conversa_do_envio(conversation_id: str | None) -> dict | None:
    """Lê `lead_id`/`stage` da conversa do envio manual, fail-soft.

    Extraída da própria rota: a consulta já existia, só rodava DEPOIS do envio. Agora
    precisa rodar antes (é dela que sai o `lead_id` do guarda de bloqueio) e por isso
    precisa ser fail-soft — uma falha de leitura aqui não pode derrubar o envio do
    operador, exatamente como `is_lead_blacklisted` não derruba.
    """
    if not conversation_id:
        return None
    try:
        from app.db.supabase import get_supabase
        return (
            get_supabase()
            .table("conversations")
            .select("lead_id, stage")
            .eq("id", conversation_id)
            .single()
            .execute()
            .data
        )
    except Exception as exc:
        logger.warning("[CHANNELS] conversa %s não lida antes do envio: %s", conversation_id, exc)
        return None


@router.post("/{channel_id}/send")
async def send_message(channel_id: str, body: SendMessage):
    """Send a message through a channel (used by CRM for human chat)."""
    from app.whatsapp.registry import get_provider  # updated import (Task 9)
    from app.conversations.service import save_message
    from app.leads.service import is_lead_blacklisted

    channel = get_channel(channel_id)
    provider = get_provider(channel)

    # BLOQUEIO: esta rota é o envio manual do operador pelo backend e não passava por
    # nenhuma camada. O lead sai pelo `conversation_id` — a MESMA consulta que a rota já
    # fazia depois do envio, agora antecipada. Sem `conversation_id` não há como
    # identificar o lead e o envio segue (fail-open): a proteção vem das camadas somadas.
    conv = _conversa_do_envio(body.conversation_id)
    lead_id = (conv or {}).get("lead_id")
    if lead_id and is_lead_blacklisted(lead_id):
        logger.warning(
            "[CHANNELS][BLACKLIST] envio manual barrado — lead %s (conversa %s, destino %s)",
            lead_id, body.conversation_id, body.to,
        )
        raise HTTPException(403, "Lead bloqueado — desbloqueie para voltar a conversar.")

    await provider.send_text(body.to, body.text)

    if conv:
        save_message(body.conversation_id, conv["lead_id"], "assistant", body.text, conv.get("stage"))

    return {"status": "sent"}

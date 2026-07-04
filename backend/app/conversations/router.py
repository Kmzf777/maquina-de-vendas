import logging

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.conversations.service import (
    get_latest_inbound_wamid,
    reset_unread_count,
    save_message,
)
from app.channels.service import get_channel_by_id
from app.whatsapp.registry import get_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class AgentUpdate(BaseModel):
    ai_enabled: bool | None = None
    agent_profile_id: str | None = None


@router.patch("/{conversation_id}/agent")
async def update_conversation_agent(conversation_id: str, body: AgentUpdate):
    """Toggle AI on/off or switch agent profile for a conversation.

    ai_enabled is stored on the lead (single source of truth).
    agent_profile_id is stored on the conversation.
    """
    if body.ai_enabled is None and body.agent_profile_id is None:
        raise HTTPException(status_code=400, detail="No fields to update")

    sb = get_supabase()

    if body.ai_enabled is not None:
        conv = (
            sb.table("conversations")
            .select("id, lead_id")
            .eq("id", conversation_id)
            .single()
            .execute()
        )
        if not conv.data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        lead_id = conv.data["lead_id"]
        sb.table("leads").update({"ai_enabled": body.ai_enabled}).eq("id", lead_id).execute()

        # OBSERVABILIDADE (auditoria lead 5551991295543): registra no histórico TODA vez que
        # um operador liga/desliga a IA. Antes, o toggle manual não deixava rastro — a IA
        # aparecia desligada sem nenhuma explicação no banco (auditoria cega). Fail-soft:
        # falha ao logar nunca derruba o toggle em si.
        acao = "ativada" if body.ai_enabled else "desativada"
        try:
            save_message(
                conversation_id,
                lead_id,
                "system",
                f"[crm] IA {acao} manualmente pelo operador",
            )
        except Exception as exc:
            logger.warning(
                "[CRM TOGGLE] falha ao registrar system message (conv=%s, ai_enabled=%s): %s",
                conversation_id, body.ai_enabled, exc,
            )

    conv_data: dict = {}
    if body.agent_profile_id is not None:
        conv_data["agent_profile_id"] = body.agent_profile_id

    if conv_data:
        sb.table("conversations").update(conv_data).eq("id", conversation_id).execute()

    result = (
        sb.table("conversations")
        .select("id, agent_profile_id, leads(id, ai_enabled)")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result.data


@router.post("/{conversation_id}/mark-read", status_code=204)
async def mark_conversation_read(conversation_id: str):
    """Zera unread_count da conversa (chamado quando o vendedor abre a conversa)."""
    result = reset_unread_count(conversation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)


@router.post("/{conversation_id}/read-receipt")
async def send_read_receipt(conversation_id: str):
    """Dispara o recibo de leitura (tique azul) da ÚLTIMA mensagem inbound do cliente.

    Regra de negócio (atendimento humano / handoff): o recibo de leitura só deve ser
    enviado DEPOIS que um vendedor humano responde a conversa pela plataforma — nunca
    antes. Garante o princípio "nunca lido sem resposta": o cliente só vê o tique azul
    quando já existe uma resposta a caminho. É chamado fire-and-forget pelo frontend logo
    após o envio bem-sucedido da resposta humana.

    Marcar a última inbound como lida é CUMULATIVO no WhatsApp (cobre todas as pendentes
    anteriores da mesma conversa). Toda a lógica é fail-soft: qualquer falha de
    Meta/provider responde 200 com marked=False, nunca 500 — o recibo é acessório e não
    pode quebrar o fluxo de envio da resposta.
    """
    sb = get_supabase()

    # 1. Resolve o canal da conversa (necessário para instanciar o provider Meta correto).
    conv = (
        sb.table("conversations")
        .select("channel_id")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    channel_id = conv.data["channel_id"]

    # 2. Última inbound pendente. Sem inbound com wamid → no-op (nada a marcar como lido).
    wamid = get_latest_inbound_wamid(conversation_id)
    if not wamid:
        return {"marked": False, "wamid": None}

    # 3. Canal → provider. Canal ausente é fail-soft: a resposta humana já foi enviada.
    channel = get_channel_by_id(channel_id)
    if not channel:
        logger.warning(
            "send_read_receipt: canal %s não encontrado (conv=%s); recibo não enviado",
            channel_id, conversation_id,
        )
        return {"marked": False, "wamid": wamid}

    # 4. Dispara o recibo via provider. Fail-soft: erro de Meta/rede nunca vira 500.
    try:
        provider = get_provider(channel)
        await provider.mark_read(wamid)
    except Exception as exc:
        logger.warning(
            "send_read_receipt: falha ao marcar wamid=%s como lido (conv=%s): %s",
            wamid, conversation_id, exc,
        )
        return {"marked": False, "wamid": wamid}

    return {"marked": True, "wamid": wamid}

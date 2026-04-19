import logging

from app.config import settings
from app.channels.service import get_channel_by_id
from app.leads.service import get_or_create_lead, update_lead
from app.conversations.service import get_or_create_conversation, update_conversation, save_message
from app.whatsapp.registry import get_provider

logger = logging.getLogger(__name__)

TEMPLATE_TEXT = (
    "oi, tudo bem?\n\n"
    "aqui é a Valeria, do comercial da Café Canastra\n\n"
    "a gente trabalha com café especial — atacado, private label e exportação\n\n"
    "queria entender se faz sentido pra você, tem um minutinho?"
)


async def dispatch_to_lead(phone: str, lead_context: dict) -> dict:
    """
    Envia mensagem de re-engajamento para um lead via o provider configurado no channel.

    Args:
        phone: número no formato +5511999999999
        lead_context: deve conter 'channel_id' (obrigatório) e opcionalmente
                      name, company, previous_stage, notes.

    Returns:
        {"status": "sent", "phone": phone, "lead_id": str}
    """
    channel_id = lead_context.get("channel_id", "")
    if not channel_id:
        raise ValueError("channel_id is required in lead_context to dispatch a message")

    channel = get_channel_by_id(channel_id)
    provider = get_provider(channel)

    await provider.send_text(phone, TEMPLATE_TEXT)

    lead = get_or_create_lead(phone)
    lead_id = lead["id"]

    try:
        update_lead(lead_id, status="template_sent")
    except Exception as e:
        logger.error(f"[DISPATCH] Failed to update lead status for {lead_id}: {e}", exc_info=True)

    conversation = None
    try:
        conversation = get_or_create_conversation(lead_id, channel_id)
        update_conversation(conversation["id"], status="template_sent")
    except Exception as e:
        logger.error(
            f"[DISPATCH] Failed to update conversation state for lead {lead_id}: {e}",
            exc_info=True,
        )

    try:
        if conversation:
            save_message(conversation["id"], lead_id, "assistant", TEMPLATE_TEXT, "secretaria")
        else:
            logger.error(f"[DISPATCH] Skipping save_message for {lead_id}: no conversation")
    except Exception as e:
        logger.error(
            f"[DISPATCH] Failed to save message for lead {lead_id}: {e}",
            exc_info=True,
        )

    logger.info(f"[DISPATCH] Message dispatched to {phone} (lead_id={lead_id})")
    return {"status": "sent", "phone": phone, "lead_id": lead_id}

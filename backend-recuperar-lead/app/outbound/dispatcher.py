import logging

import httpx

from app.config import settings
from app.leads.service import get_or_create_lead, update_lead
from app.conversations.service import get_or_create_conversation, update_conversation, save_message

logger = logging.getLogger(__name__)

META_API_BASE = "https://graph.facebook.com/v21.0"

# ---------------------------------------------------------------------------
# Template hardcoded — primeiro contato ativo com o lead
# Substituir pelo template aprovado pela Meta antes de ir a producao.
# NOTA: a Meta só aceita type="template" para contatos fora da janela de 24h.
# Para testes com janela aberta, pode usar type="text" comentando o payload abaixo.
# ---------------------------------------------------------------------------
TEMPLATE_NAME = "recuperar_lead_v1"  # nome do template aprovado na Meta

TEMPLATE_TEXT = (
    "oi, tudo bem?\n\n"
    "aqui é a Valeria, do comercial da Café Canastra\n\n"
    "a gente trabalha com café especial — atacado, private label e exportação\n\n"
    "queria entender se faz sentido pra você, tem um minutinho?"
)


async def dispatch_to_lead(phone: str, lead_context: dict) -> dict:
    """
    Envia o template de re-engajamento para um lead via Meta Cloud API.

    - Salva a mensagem no histórico como role=assistant para o agent ter contexto.
    - Atualiza lead.status = template_sent.
    - Cria/atualiza conversation.status = template_sent para o processor
      chamar activate_conversation quando o lead responder.

    Args:
        phone: número no formato +5511999999999
        lead_context: dados opcionais do CRM: name, company, previous_stage,
                      notes, channel_id (obrigatório para criar conversation)

    Returns:
        {"status": "sent", "phone": phone, "lead_id": str}
    """
    if not settings.meta_access_token:
        raise ValueError("META_ACCESS_TOKEN nao configurado")
    if not settings.meta_phone_number_id:
        raise ValueError("META_PHONE_NUMBER_ID nao configurado")

    url = f"{META_API_BASE}/{settings.meta_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }
    # Use text for now (works within 24h window); swap to template payload for cold leads
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": TEMPLATE_TEXT},
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    # Resolve or create lead
    lead = get_or_create_lead(phone)
    lead_id = lead["id"]

    # Mark lead as template_sent so processor knows to activate on first reply
    try:
        update_lead(lead_id, status="template_sent")
    except Exception as e:
        logger.error(f"[DISPATCH] Failed to update lead status for {lead_id}: {e}", exc_info=True)

    # Create/get conversation and mark as template_sent
    channel_id = lead_context.get("channel_id", "")
    if not channel_id:
        raise ValueError("channel_id is required in lead_context to create conversation record")

    try:
        conversation = get_or_create_conversation(lead_id, channel_id)
        update_conversation(conversation["id"], status="template_sent")
        save_message(conversation["id"], lead_id, "assistant", TEMPLATE_TEXT, "secretaria")
    except Exception as e:
        logger.error(
            f"[DISPATCH] Failed to update conversation state for lead {lead_id}: {e}",
            exc_info=True,
        )

    logger.info(f"[DISPATCH] Template sent to {phone} (lead_id={lead_id}), wamid={result}")
    return {"status": "sent", "phone": phone, "lead_id": lead_id}

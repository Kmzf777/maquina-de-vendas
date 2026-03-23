import asyncio
import logging

from app.leads.service import get_or_create_lead, activate_lead, update_lead
from app.agent.orchestrator import run_agent
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay
from app.whatsapp.client import send_text
from app.whatsapp.media import transcribe_audio, describe_image

logger = logging.getLogger(__name__)


async def process_buffered_messages(phone: str, combined_text: str):
    """Process accumulated buffer messages: resolve media, run agent, humanize, send."""
    try:
        # Resolve any media placeholders
        resolved_text = await _resolve_media(combined_text)

        # Get or create lead
        lead = get_or_create_lead(phone)

        # Activate lead if pending/template_sent
        if lead.get("status") in ("imported", "template_sent"):
            lead = activate_lead(lead["id"])

        # Run agent
        response = await run_agent(lead, resolved_text)

        # Humanize and send
        bubbles = split_into_bubbles(response)
        for bubble in bubbles:
            delay = calculate_typing_delay(bubble)
            await asyncio.sleep(delay)
            await send_text(phone, bubble)

        # Update last_msg timestamp
        from datetime import datetime, timezone
        update_lead(lead["id"], last_msg_at=datetime.now(timezone.utc).isoformat())

    except Exception as e:
        logger.error(f"Error processing messages for {phone}: {e}", exc_info=True)


async def _resolve_media(text: str) -> str:
    """Replace media placeholders with actual content."""
    import re

    # Pattern: [audio: media_url=xxx] or [image: media_url=xxx]
    audio_pattern = r"\[audio: media_url=(\S+)\]"
    image_pattern = r"\[image: media_url=(\S+)\]"

    for match in re.finditer(audio_pattern, text):
        media_url = match.group(1)
        try:
            transcription = await transcribe_audio(media_url)
            text = text.replace(match.group(0), f"[audio transcrito: {transcription}]")
        except Exception as e:
            logger.warning(f"Failed to transcribe audio: {e}")
            text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for match in re.finditer(image_pattern, text):
        media_url = match.group(1)
        try:
            description = await describe_image(media_url)
            text = text.replace(match.group(0), f"[imagem recebida: {description}]")
        except Exception as e:
            logger.warning(f"Failed to describe image: {e}")
            text = text.replace(match.group(0), "[imagem: nao foi possivel descrever]")

    return text

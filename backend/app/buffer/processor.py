import asyncio
import logging
import re
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.config import settings
from app.leads.service import get_or_create_lead
from app.conversations.service import (
    get_or_create_conversation, activate_conversation,
    update_conversation, save_message,
)
from app.agent.orchestrator import run_agent
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay
from app.providers.registry import get_provider
from app.agent_profiles.service import get_agent_profile

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


async def process_buffered_messages(phone: str, combined_text: str, channel: dict):
    """Process accumulated buffer messages for a specific channel."""
    try:
        provider = get_provider(channel)

        # Resolve any media placeholders
        resolved_text = await _resolve_media(combined_text, provider)

        # Get or create lead (global by phone)
        lead = get_or_create_lead(phone)

        # Get or create conversation (per lead+channel)
        conversation = get_or_create_conversation(lead["id"], channel["id"])

        # Activate conversation if imported/template_sent
        if conversation.get("status") in ("imported", "template_sent"):
            conversation = activate_conversation(conversation["id"])

        # Check if channel has an agent profile
        agent_profile_id = channel.get("agent_profile_id")

        if agent_profile_id:
            # Load agent profile
            profile = get_agent_profile(agent_profile_id)

            # Enrich conversation with lead data for the agent
            conversation["leads"] = lead

            # Run agent
            response = await run_agent(conversation, profile, resolved_text)

            # Humanize and send
            bubbles = split_into_bubbles(response)
            for bubble in bubbles:
                delay = calculate_typing_delay(bubble)
                await asyncio.sleep(delay)
                await provider.send_text(phone, bubble)
        else:
            # No agent — human-only channel. Save message, no auto-reply.
            save_message(
                conversation["id"], lead["id"], "user", resolved_text,
                conversation.get("stage"),
            )

        # Update last_msg timestamp
        update_conversation(
            conversation["id"],
            last_msg_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        logger.error(f"Error processing messages for {phone} on channel {channel.get('name')}: {e}", exc_info=True)


async def _resolve_media(text: str, provider) -> str:
    """Replace media placeholders with actual content."""
    # Meta-style: [audio: media_id=xxx]
    audio_id_pattern = r"\[audio: media_id=(\S+)\]"
    image_id_pattern = r"\[image: media_id=(\S+)\]"

    # Evolution-style: [audio: media_url=xxx]
    audio_url_pattern = r"\[audio: media_url=(\S+)\]"
    image_url_pattern = r"\[image: media_url=(\S+)\]"

    for pattern in [audio_id_pattern, audio_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            try:
                audio_bytes, content_type = await provider.download_media(media_ref)
                ext = "ogg" if "ogg" in content_type else "mp4"
                transcript = await _get_openai().audio.transcriptions.create(
                    model="whisper-1",
                    file=(f"audio.{ext}", audio_bytes, content_type),
                )
                text = text.replace(match.group(0), f"[audio transcrito: {transcript.text}]")
            except Exception as e:
                logger.warning(f"Failed to transcribe audio {media_ref}: {e}")
                text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for pattern in [image_id_pattern, image_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            try:
                import base64
                image_bytes, content_type = await provider.download_media(media_ref)
                b64 = base64.b64encode(image_bytes).decode()
                response = await _get_openai().chat.completions.create(
                    model="gpt-4o",
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Descreva esta imagem em uma frase curta em portugues. Se for uma foto de produto, descreva o produto."},
                            {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
                        ],
                    }],
                    max_tokens=150,
                )
                description = response.choices[0].message.content
                text = text.replace(match.group(0), f"[imagem recebida: {description}]")
            except Exception as e:
                logger.warning(f"Failed to describe image {media_ref}: {e}")
                text = text.replace(match.group(0), "[imagem: nao foi possivel descrever]")

    return text

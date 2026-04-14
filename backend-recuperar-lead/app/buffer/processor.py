import asyncio
import base64
import logging
import re
from datetime import datetime, timedelta, timezone

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
from app.channels.service import get_channel_by_id
from app.cadence.service import get_active_enrollment, pause_enrollment
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )
    return _openai_client


def _is_recent_duplicate(
    conversation_id: str, content: str, role: str, window_seconds: int = 30
) -> bool:
    """Return True if an identical message was saved in this conversation within the last N seconds."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("id")
        .eq("conversation_id", conversation_id)
        .eq("role", role)
        .eq("content", content)
        .gte("created_at", cutoff)
        .limit(1)
        .execute()
    )
    return len(result.data) > 0


async def process_buffered_messages(
    phone: str, combined_text: str, channel_id: str = ""
):
    """Process accumulated buffer messages for a lead on a specific channel."""
    try:
        lead = get_or_create_lead(phone)
        channel = get_channel_by_id(channel_id) if channel_id else None
        if not channel:
            logger.warning(f"No channel found for {phone} (channel_id={channel_id}), skipping")
            return

        provider = get_provider(channel)
        conversation = get_or_create_conversation(lead["id"], channel_id)
    except Exception as e:
        logger.error(f"Fatal setup error for {phone}: {e}", exc_info=True)
        return

    # Activate conversation when lead first responds after template dispatch
    if conversation.get("status") in ("imported", "template_sent"):
        try:
            conversation = activate_conversation(conversation["id"])
        except Exception as e:
            logger.warning(f"Failed to activate conversation {conversation['id']}: {e}")

    # Resolve media placeholders
    try:
        resolved_text = await _resolve_media(combined_text, provider)
    except Exception as e:
        logger.warning(f"Failed to resolve media for {phone}: {e}")
        resolved_text = combined_text

    # Dedup: skip if this exact message was already processed recently
    if _is_recent_duplicate(conversation["id"], resolved_text, "user"):
        logger.warning(f"Duplicate user message detected for {phone}, skipping")
        return

    # Pause cadence if lead is enrolled in one
    try:
        enrollment = get_active_enrollment(lead["id"])
        if enrollment:
            pause_enrollment(enrollment["id"])
            logger.info(f"[CADENCE] Lead {phone} responded — pausing enrollment")
    except Exception as e:
        logger.warning(f"Failed to pause cadence for {phone}: {e}")

    # Always save the incoming user message
    try:
        save_message(
            conversation["id"], lead["id"], "user",
            resolved_text, conversation.get("stage"),
        )
    except Exception as e:
        logger.error(f"Failed to save user message for {phone}: {e}", exc_info=True)
        # Abort: do not run agent without persistence — avoids unlogged AI responses
        return

    # If human already took control, stop here — message is saved, agent skipped
    if lead.get("human_control"):
        logger.info(f"[HUMAN CONTROL] Lead {phone} is under human control — agent skipped")
        _update_last_msg(conversation["id"])
        return

    # Check if channel has an agent profile
    agent_profile = channel.get("agent_profiles")
    if not agent_profile:
        logger.info(f"No agent profile for channel {channel_id}, human-only mode")
        _update_last_msg(conversation["id"])
        return

    # Run AI agent
    try:
        conversation["leads"] = lead
        response = await run_agent(conversation, resolved_text)
    except Exception as e:
        logger.error(f"Agent error for {phone}: {e}", exc_info=True)
        _update_last_msg(conversation["id"])
        return

    # Save assistant response
    try:
        save_message(
            conversation["id"], lead["id"], "assistant",
            response, conversation.get("stage"),
        )
    except Exception as e:
        logger.error(f"Failed to save assistant message for {phone}: {e}", exc_info=True)

    # Send bubbles
    bubbles = split_into_bubbles(response)
    for bubble in bubbles:
        delay = calculate_typing_delay(bubble)
        await asyncio.sleep(delay)
        try:
            await provider.send_text(phone, bubble)
        except Exception as e:
            logger.error(f"Failed to send bubble to {phone}: {e}", exc_info=True)
            break

    _update_last_msg(conversation["id"])


def _update_last_msg(conversation_id: str) -> None:
    try:
        update_conversation(
            conversation_id,
            last_msg_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.warning(f"Failed to update last_msg_at for {conversation_id}: {e}")


async def _resolve_media(text: str, provider) -> str:
    """Replace media placeholders with actual content using Gemini."""
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
                    model="gemini-3-flash-preview",
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
                image_bytes, content_type = await provider.download_media(media_ref)
                b64 = base64.b64encode(image_bytes).decode()
                response = await _get_openai().chat.completions.create(
                    model="gemini-3-flash-preview",
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

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

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )
    return _openai_client


async def process_buffered_messages(
    phone: str, combined_text: str, channel: dict, push_name: str | None = None
):
    """Process accumulated buffer messages for a specific channel.

    Error handling is stratified: each layer is independently protected so
    that a failure in AI inference or message sending does not prevent the
    incoming user message from being persisted.
    """
    # --- Layer 1: Setup (provider, media, lead, conversation) ---
    try:
        provider = get_provider(channel)
        resolved_text = await _resolve_media(combined_text, provider)
        lead = get_or_create_lead(phone, name=push_name)
        conversation = get_or_create_conversation(lead["id"], channel["id"])
    except Exception as e:
        logger.error(
            f"Fatal setup error for {phone} on channel {channel.get('name')}: {e}",
            exc_info=True,
        )
        return

    if conversation.get("status") in ("imported", "template_sent"):
        try:
            conversation = activate_conversation(conversation["id"])
        except Exception as e:
            logger.warning(f"Failed to activate conversation {conversation['id']}: {e}")

    # --- Layer 2: Always persist the incoming user message ---
    try:
        save_message(
            conversation["id"], lead["id"], "user",
            resolved_text, conversation.get("stage"),
        )
    except Exception as e:
        logger.error(f"Failed to save user message for {phone}: {e}", exc_info=True)

    # --- Layer 3: AI agent or MVP auto-reply ---
    agent_profile_id = channel.get("agent_profile_id")

    # MVP fallback: if no AI agent is configured, send a static auto-reply
    # configured via channel.provider_config.auto_reply_message
    if not agent_profile_id:
        auto_reply = channel.get("provider_config", {}).get("auto_reply_message")
        if auto_reply:
            try:
                save_message(
                    conversation["id"], lead["id"], "assistant",
                    auto_reply, conversation.get("stage"),
                )
            except Exception as e:
                logger.error(f"Failed to save auto-reply for {phone}: {e}", exc_info=True)
            try:
                await provider.send_text(phone, auto_reply)
            except Exception as e:
                logger.error(f"Failed to send auto-reply to {phone}: {e}", exc_info=True)
        _update_last_msg(conversation["id"])
        return

    try:
        profile = get_agent_profile(agent_profile_id)
        conversation["leads"] = lead
        response = await run_agent(conversation, profile, resolved_text)
    except Exception as e:
        logger.error(
            f"Agent error for {phone} on channel {channel.get('name')}: {e}",
            exc_info=True,
        )
        _update_last_msg(conversation["id"])
        return

    # --- Layer 4: Persist assistant response ---
    try:
        save_message(
            conversation["id"], lead["id"], "assistant",
            response, conversation.get("stage"),
        )
    except Exception as e:
        logger.error(f"Failed to save assistant message for {phone}: {e}", exc_info=True)

    # --- Layer 5: Send bubbles (each bubble independently) ---
    bubbles = split_into_bubbles(response)
    for bubble in bubbles:
        delay = calculate_typing_delay(bubble)
        await asyncio.sleep(delay)
        try:
            await provider.send_text(phone, bubble)
        except Exception as e:
            logger.error(f"Failed to send bubble to {phone}: {e}", exc_info=True)
            break  # Don't send subsequent bubbles if one failed

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
                import base64
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

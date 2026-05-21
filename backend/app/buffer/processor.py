import asyncio
import base64
import json
import os
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
from app.whatsapp.registry import get_provider
from app.channels.service import get_channel_by_id
from app.cadence.service import get_active_enrollment, pause_enrollment
from app.follow_up.service import schedule_followup as _schedule_followup

# Kill switch global — mude para True para reativar a Valéria
VALERIA_ENABLED = True
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def _bubble_delays(count: int, is_rehearsal: bool) -> list[float]:
    """Returns per-bubble pre-send delay in seconds.

    Production: first bubble immediate, second after 4s, rest after 2s.
    Rehearsal: no delays to keep tests fast.
    """
    if is_rehearsal or count == 0:
        return [0.0] * count
    delays = [0.0]
    for i in range(1, count):
        delays.append(4.0 if i == 1 else 2.0)
    return delays

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


def _resolve_agent_profile_id(conversation: dict, channel: dict) -> str | None:
    """Resolve which agent_profile_id to use for this conversation.

    Priority:
    1. conversation.agent_profile_id (set by broadcast worker)
    2. channel.agent_profiles.id (default channel agent)
    3. None (human-only mode)
    """
    conv_agent = conversation.get("agent_profile_id")
    if conv_agent:
        return conv_agent
    channel_profile = channel.get("agent_profiles")
    if channel_profile:
        return channel_profile.get("id")
    return None


def _is_recent_duplicate(
    conversation_id: str, content: str, role: str, window_seconds: int = 30
) -> bool:
    """Return True only if an identical user message was recently saved AND received an assistant reply.

    A user message without a following assistant reply means the agent crashed — allow retry.
    """
    if role != "user":
        # For non-user roles, use simple time-based dedup
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

    # For user messages: only deduplicate if an assistant reply followed the last identical message
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    sb = get_supabase()

    # Find the most recent identical user message within window
    dup = (
        sb.table("messages")
        .select("id, created_at")
        .eq("conversation_id", conversation_id)
        .eq("role", "user")
        .eq("content", content)
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not dup.data:
        return False  # No duplicate found

    dup_created_at = dup.data[0]["created_at"]

    # Check if an assistant reply was sent AFTER that duplicate user message
    reply = (
        sb.table("messages")
        .select("id")
        .eq("conversation_id", conversation_id)
        .eq("role", "assistant")
        .gt("created_at", dup_created_at)
        .limit(1)
        .execute()
    )
    # Only skip if a real reply was already sent — otherwise allow retry
    return len(reply.data) > 0


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
            activate_conversation(conversation["id"])
            conversation["status"] = "active"
        except Exception as e:
            logger.warning(f"Failed to activate conversation {conversation['id']}: {e}")

    # Resolve media placeholders (also uploads audio to Supabase Storage)
    _media_url: str | None = None
    _message_type: str | None = None
    _document_name: str | None = None
    _metadata: dict | None = None
    try:
        resolved_text, _media_url, _message_type, _document_name, _metadata = await _resolve_media(combined_text, provider)
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
            sent_by="user",
            media_url=_media_url,
            message_type=_message_type,
            document_name=_document_name,
            metadata=_metadata,
        )
    except Exception as e:
        logger.error(f"Failed to save user message for {phone}: {e}", exc_info=True)
        # Abort: do not run agent without persistence — avoids unlogged AI responses
        return

    # Registrar resposta ao disparo se o lead tiver um broadcast_lead ativo
    try:
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply(lead["id"])
    except Exception as e:
        logger.warning("Failed to record broadcast reply for %s: %s", phone, e)

    # Notify campaign worker of reply
    try:
        from app.campaigns.worker import handle_campaign_reply
        handle_campaign_reply(lead["id"])
    except Exception as ce:
        logger.debug("[CAMPAIGNS] handle_campaign_reply error: %s", ce)

    # Track last inbound message time for WhatsApp 24h window enforcement
    try:
        sb = get_supabase()
        sb.table("leads").update(
            {"last_customer_message_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", lead["id"]).execute()
    except Exception as e:
        logger.warning(f"Failed to update last_customer_message_at for {lead['id']}: {e}")

    # Incrementa contador de não-lidas para o vendedor (resetado quando o vendedor responde)
    try:
        sb = get_supabase()
        current = (
            sb.table("conversations")
            .select("unread_count")
            .eq("id", conversation["id"])
            .single()
            .execute()
        )
        new_count = (current.data.get("unread_count") or 0) + 1
        sb.table("conversations").update({"unread_count": new_count}).eq("id", conversation["id"]).execute()
    except Exception as e:
        logger.warning(f"Failed to increment unread_count for {conversation['id']}: {e}")

    # Channel-level gate: human channels never run AI or schedule follow-ups
    if channel.get("mode", "ai") == "human":
        logger.info(
            f"[HUMAN CHANNEL] mode=human — IA e follow-up desativados "
            f"channel_id={channel_id} phone={phone}"
        )
        _update_last_msg(conversation["id"])
        return

    # If AI is disabled globally, skip agent
    if not VALERIA_ENABLED:
        logger.info(
            f"[AI DISABLED] kill switch ativo — conv={conversation['id']} phone={phone}"
        )
        _update_last_msg(conversation["id"])
        return

    # Single AI gate: lead.ai_enabled is the sole source of truth
    if not lead.get("ai_enabled", True):
        logger.info(
            f"[AI DISABLED] lead.ai_enabled=false — conv={conversation['id']} phone={phone}"
        )
        _update_last_msg(conversation["id"])
        return

    # Channel gate: if AI_PHONE_NUMBER_ID is configured, only that channel runs AI
    allowed_phone_number_id = settings.ai_phone_number_id
    if allowed_phone_number_id:
        channel_phone_number_id = (channel.get("provider_config") or {}).get("phone_number_id")
        if channel_phone_number_id != allowed_phone_number_id:
            logger.info(
                f"[AI DISABLED] channel phone_number_id={channel_phone_number_id!r} not in allowlist "
                f"— conv={conversation['id']} phone={phone}"
            )
            _update_last_msg(conversation["id"])
            return

    # Resolve agent profile: conversation takes priority over channel default
    # None means no explicit profile — orchestrator defaults to valeria_inbound
    agent_profile_id = _resolve_agent_profile_id(conversation, channel)

    # Run AI agent
    try:
        conversation["leads"] = lead
        lead_context = lead.get("metadata") or {}
        response = await run_agent(conversation, resolved_text, lead_context=lead_context, agent_profile_id=agent_profile_id)

        if not response or not response.strip():
            logger.error(
                f"[AGENT EMPTY RESPONSE] run_agent returned empty string for {phone} "
                f"(conv={conversation['id']}, stage={conversation.get('stage')}). "
                "Likely cause: tool loop exhausted without producing text content."
            )
            _update_last_msg(conversation["id"])
            return
    except Exception as e:
        logger.error(f"Agent error for {phone}: {e}", exc_info=True)
        _update_last_msg(conversation["id"])
        return

    # Send bubbles — persist only after all bubbles are delivered
    is_rehearsal = os.environ.get("REHEARSAL_MODE", "").lower() == "true"
    bubbles = split_into_bubbles(response)
    delays = _bubble_delays(len(bubbles), is_rehearsal)
    send_ok = True
    for delay, bubble in zip(delays, bubbles):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            await provider.send_text(phone, bubble)
        except Exception as e:
            logger.error(f"Failed to send bubble to {phone}: {e}", exc_info=True)
            send_ok = False
            break

    if send_ok:
        try:
            save_message(
                conversation["id"], lead["id"], "assistant",
                response, conversation.get("stage"),
            )
        except Exception as e:
            logger.error(f"Failed to save assistant message for {phone}: {e}", exc_info=True)

        # Agenda follow-up se habilitado para a conversa
        if conversation.get("followup_enabled", True) and channel:
            try:
                _schedule_followup(
                    conversation_id=conversation["id"],
                    lead_id=lead["id"],
                    channel_id=channel["id"],
                )
            except Exception as e:
                logger.warning(f"[FOLLOWUP] Falha ao agendar follow-up para {phone}: {e}")

    _update_last_msg(conversation["id"])


def _update_last_msg(conversation_id: str) -> None:
    try:
        update_conversation(
            conversation_id,
            last_msg_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.warning(f"Failed to update last_msg_at for {conversation_id}: {e}")


def _upload_audio_to_storage(audio_bytes: bytes, content_type: str, media_ref: str, ext: str) -> str | None:
    """Upload audio to Supabase Storage and return permanent public URL."""
    try:
        from app.db.supabase import get_supabase
        sb = get_supabase()
        path = f"{media_ref}.{ext}"
        sb.storage.from_("audio").upload(
            path, audio_bytes,
            file_options={"content-type": content_type, "x-upsert": "true"},
        )
        return sb.storage.from_("audio").get_public_url(path)
    except Exception as e:
        logger.warning(f"Failed to upload audio to storage: {e}")
        return None


async def _resolve_media(
    text: str, provider
) -> tuple[str, str | None, str | None, str | None, dict | None]:
    """Replace media placeholders with type/url metadata.

    Returns (resolved_text, media_url, message_type, document_name, metadata).
    Audio: downloaded, transcribed, uploaded to Supabase Storage.
    Image/video/document/sticker: media_id extracted only, no download.
    Location/contact/reaction: metadata dict extracted from base64 JSON.
    """
    audio_id_pattern = r"\[audio: media_id=(\S+)\]"
    audio_url_pattern = r"\[audio: media_url=(\S+)\]"
    image_id_pattern = r"\[image: media_id=(\S+)\]"
    image_url_pattern = r"\[image: media_url=(\S+)\]"
    video_id_pattern = r"\[video: media_id=(\S+)\]"
    video_url_pattern = r"\[video: media_url=(\S+)\]"
    doc_url_pattern = r"\[document: media_url=(\S+?)(?:\s+filename_b64=([A-Za-z0-9+/=]+))?\]"
    sticker_url_pattern = r"\[sticker: media_url=(\S+)\]"
    meta_b64_pattern = r"\[(\w+): meta_b64=([A-Za-z0-9+/=]+)\]"

    storage_url: str | None = None
    message_type: str | None = None
    document_name: str | None = None
    metadata: dict | None = None

    for pattern in [audio_id_pattern, audio_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            message_type = "audio"
            storage_url = media_ref

            try:
                audio_bytes, content_type = await provider.download_media(media_ref)
            except Exception as e:
                logger.warning(f"Failed to download audio {media_ref}: {e}")
                text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")
                continue

            ext = "ogg" if "ogg" in content_type else "mp4"
            uploaded_url = _upload_audio_to_storage(audio_bytes, content_type, media_ref, ext)
            if uploaded_url:
                storage_url = uploaded_url

            try:
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
            if message_type is None:
                message_type = "image"
                storage_url = media_ref
            text = text.replace(match.group(0), "")

    for pattern in [video_id_pattern, video_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            if message_type is None:
                message_type = "video"
                storage_url = media_ref
            text = text.replace(match.group(0), "")

    for match in re.finditer(doc_url_pattern, text):
        media_ref = match.group(1)
        fname_b64 = match.group(2)
        if message_type is None:
            message_type = "document"
            storage_url = media_ref
            if fname_b64:
                try:
                    document_name = base64.b64decode(fname_b64).decode()
                except Exception:
                    pass
        text = text.replace(match.group(0), "")

    for match in re.finditer(sticker_url_pattern, text):
        media_ref = match.group(1)
        if message_type is None:
            message_type = "sticker"
            storage_url = media_ref
        text = text.replace(match.group(0), "")

    for match in re.finditer(meta_b64_pattern, text):
        meta_type = match.group(1)
        if meta_type in ("location", "contact", "reaction") and message_type is None:
            try:
                metadata = json.loads(base64.b64decode(match.group(2)).decode())
                message_type = meta_type
            except Exception as e:
                logger.warning(f"Failed to decode metadata for {meta_type}: {e}")
        text = text.replace(match.group(0), "")

    return text.strip(), storage_url, message_type, document_name, metadata

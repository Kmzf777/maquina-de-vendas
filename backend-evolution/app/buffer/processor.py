import asyncio
import logging

from app.leads.service import get_or_create_lead, activate_lead, update_lead
from app.agent.orchestrator import run_agent
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay
from app.whatsapp.factory import get_whatsapp_client
from app.whatsapp.media import transcribe_audio, describe_image
from app.cadence.service import get_active_enrollment, pause_enrollment
from app.agent.token_tracker import track_token_usage
from app.channels.service import get_channel_by_id
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def _get_or_create_conversation(lead_id: str, channel_id: str, stage: str) -> dict:
    """Get or create a conversation record for a lead+channel pair."""
    sb = get_supabase()
    res = (
        sb.table("conversations")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("channel_id", channel_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    res = (
        sb.table("conversations")
        .insert({
            "lead_id": lead_id,
            "channel_id": channel_id,
            "stage": stage,
            "status": "active",
            "last_msg_at": now,
        })
        .select()
        .single()
        .execute()
    )
    return res.data


async def process_buffered_messages(phone: str, combined_text: str, channel_id: str = ""):
    """Process accumulated buffer messages: resolve media, run agent, humanize, send."""
    try:
        lead = get_or_create_lead(phone)

        # Look up channel for sending
        channel = get_channel_by_id(channel_id) if channel_id else None
        if not channel:
            logger.warning(f"No channel found for {phone} (channel_id={channel_id}), skipping")
            return

        # Get WhatsApp client for this channel
        wa_client = get_whatsapp_client(channel)

        # Ensure conversation record exists
        stage = lead.get("stage", "secretaria")
        conversation = _get_or_create_conversation(lead["id"], channel_id, stage)

        # Resolve any media placeholders
        resolved_text = await _resolve_media(combined_text, lead)

        # Pause cadence if active
        enrollment = get_active_enrollment(lead["id"])
        if enrollment:
            pause_enrollment(enrollment["id"])
            logger.info(f"[CADENCE] Lead {phone} responded — pausing enrollment")

        # Activate lead if pending/template_sent
        if lead.get("status") in ("imported", "template_sent"):
            lead = activate_lead(lead["id"])

        # Check if channel has an agent profile
        agent_profile = channel.get("agent_profiles")
        if agent_profile:
            # Run AI agent with profile context
            response = await run_agent(lead, resolved_text, channel, conversation_id=conversation["id"])
            # Humanize and send
            bubbles = split_into_bubbles(response)
            for bubble in bubbles:
                delay = calculate_typing_delay(bubble)
                await asyncio.sleep(delay)
                await wa_client.send_text(phone, bubble)
        else:
            # Human-only mode: just save the message, don't run agent
            from app.leads.service import save_message
            save_message(lead["id"], "user", resolved_text, lead.get("stage", "secretaria"), conversation_id=conversation["id"])
            logger.info(f"Human-only channel for {phone} — message saved, no agent response")

        # Update last_msg timestamp on lead and conversation
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        update_lead(lead["id"], last_msg_at=now)
        sb = get_supabase()
        sb.table("conversations").update({"last_msg_at": now, "stage": lead.get("stage", stage)}).eq("id", conversation["id"]).execute()

    except Exception as e:
        logger.error(f"Error processing messages for {phone}: {e}", exc_info=True)


async def _resolve_media(text: str, lead: dict) -> str:
    """Replace media placeholders with actual content and track usage."""
    import re

    stage = lead.get("stage", "secretaria")

    # Pattern: [audio: media_url=xxx] or [image: media_url=xxx]
    audio_pattern = r"\[audio: media_url=(\S+)\]"
    image_pattern = r"\[image: media_url=(\S+)\]"

    for match in re.finditer(audio_pattern, text):
        media_url = match.group(1)
        try:
            transcription, usage_info = await transcribe_audio(media_url)
            text = text.replace(match.group(0), f"[audio transcrito: {transcription}]")

            track_token_usage(
                lead_id=lead["id"],
                stage=stage,
                model=usage_info["model"],
                call_type="media_transcription",
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
                total_cost_override=usage_info.get("estimated_cost"),
            )
        except Exception as e:
            logger.warning(f"Failed to transcribe audio: {e}")
            text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for match in re.finditer(image_pattern, text):
        media_url = match.group(1)
        try:
            description, usage_info = await describe_image(media_url)
            text = text.replace(match.group(0), f"[imagem recebida: {description}]")

            track_token_usage(
                lead_id=lead["id"],
                stage=stage,
                model=usage_info["model"],
                call_type="media_description",
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
            )
        except Exception as e:
            logger.warning(f"Failed to describe image: {e}")
            text = text.replace(match.group(0), "[imagem: nao foi possivel descrever]")

    return text

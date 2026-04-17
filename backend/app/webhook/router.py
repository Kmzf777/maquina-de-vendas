import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request

from app.webhook.parser import parse_webhook_payload
from app.whatsapp.registry import get_provider
from app.buffer.manager import push_to_buffer
from app.leads.service import get_or_create_lead, reset_lead
from app.channels.service import get_channel_by_provider_config
from app.dev_router.service import is_dev_number
from app.dev_router.forwarder import forward_to_dev
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _find_evolution_channel(payload: dict) -> dict | None:
    instance_name = ""
    instance_data = payload.get("instance")
    if isinstance(instance_data, dict):
        instance_name = instance_data.get("instanceName", "")
    elif isinstance(instance_data, str):
        instance_name = instance_data

    if not instance_name:
        instance_name = payload.get("instanceName", "")

    if instance_name:
        channel = get_channel_by_provider_config("instance", instance_name, "evolution")
        if channel:
            return channel

    logger.warning(f"No Evolution channel found for instance={instance_name}")
    return None


@router.post("/webhook/evolution")
async def receive_evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    payload_bytes = await request.body()
    payload = json.loads(payload_bytes)
    logger.info(f"Evolution webhook event: {payload.get('event', 'unknown')}")

    channel = _find_evolution_channel(payload)
    if not channel:
        return {"status": "ok"}

    if not channel.get("is_active"):
        logger.info(f"Channel {channel['id']} is inactive, skipping")
        return {"status": "ok"}

    messages = parse_webhook_payload(payload)
    redis = request.app.state.redis

    for msg in messages:
        logger.info(f"Message from {msg.from_number} ({msg.push_name}): type={msg.type}")
        msg.channel_id = channel["id"]

        if await is_dev_number(redis, msg.from_number):
            logger.info(f"Dev routing: forwarding {msg.from_number} to {settings.dev_server_url}")
            background_tasks.add_task(
                forward_to_dev,
                dev_url=settings.dev_server_url,
                path="/webhook/evolution",
                headers=dict(request.headers),
                body=payload_bytes,
            )
            continue

        try:
            provider = get_provider(channel)
            await provider.mark_read(msg.message_id, msg.remote_jid)
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        if msg.text and msg.text.strip().lower() == "!resetar":
            try:
                lead = get_or_create_lead(msg.from_number)
                reset_lead(lead["id"])
                provider = get_provider(channel)
                await provider.send_text(msg.from_number, "Memoria resetada! Pode comecar uma nova conversa do zero.")
            except Exception as e:
                logger.error(f"Failed to reset lead: {e}", exc_info=True)
            continue

        await push_to_buffer(redis, msg)

    return {"status": "ok"}


@router.post("/webhook")
async def receive_webhook_legacy(request: Request, background_tasks: BackgroundTasks):
    return await receive_evolution_webhook(request, background_tasks)

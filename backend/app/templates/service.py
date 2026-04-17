# backend/app/templates/service.py
import logging
from fastapi import HTTPException
from app.db.supabase import get_supabase
from app.channels.service import get_channel
from app.whatsapp.meta_templates import MetaTemplateClient

logger = logging.getLogger(__name__)


def _get_meta_client(channel: dict) -> MetaTemplateClient:
    if channel.get("provider") != "meta_cloud":
        raise HTTPException(400, "Templates are only supported for meta_cloud channels")
    config = channel.get("provider_config", {})
    waba_id = config.get("waba_id")
    if not waba_id:
        raise HTTPException(400, "Channel provider_config is missing 'waba_id'")
    return MetaTemplateClient(waba_id=waba_id, access_token=config["access_token"])


async def create_template(channel_id: str, data: dict) -> tuple[dict, str]:
    channel = get_channel(channel_id)
    meta_client = _get_meta_client(channel)

    requested_category = data["category"]
    payload = {
        "name": data["name"],
        "language": data["language"],
        "category": requested_category,
        "components": data["components"],
    }

    try:
        meta_response = await meta_client.create_template(payload)
    except Exception:
        raise HTTPException(502, "Failed to create template on Meta")

    meta_category = meta_response.get("category", requested_category)
    meta_template_id = meta_response.get("id")
    category_changed = meta_category != requested_category
    status = "pending_category_review" if category_changed else "pending"

    sb = get_supabase()
    record = (
        sb.table("message_templates")
        .insert({
            "channel_id": channel_id,
            "name": data["name"],
            "language": data["language"],
            "requested_category": requested_category,
            "category": meta_category,
            "components": data["components"],
            "meta_template_id": meta_template_id,
            "status": status,
        })
        .execute()
        .data[0]
    )

    result: dict = {"status": status, "template": record}
    if category_changed:
        result["suggested_category"] = meta_category
    return result, status


async def confirm_template(channel_id: str, template_id: str) -> dict:
    pass


async def delete_template(channel_id: str, template_id: str) -> dict:
    pass

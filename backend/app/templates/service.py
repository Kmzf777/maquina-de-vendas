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
    access_token = config.get("access_token")
    if not access_token:
        raise HTTPException(400, "Channel provider_config is missing 'access_token'")
    return MetaTemplateClient(waba_id=waba_id, access_token=access_token)


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
        logger.exception("Failed to call Meta Templates API for channel %s", channel_id)
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
    sb = get_supabase()
    res = (
        sb.table("message_templates")
        .select("*")
        .eq("id", template_id)
        .eq("channel_id", channel_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Template not found")
    template = res.data[0]
    if template["status"] != "pending_category_review":
        raise HTTPException(409, "Template is not in pending_category_review state")

    updated = (
        sb.table("message_templates")
        .update({"status": "pending"})
        .eq("id", template_id)
        .execute()
        .data[0]
    )
    return {"status": "pending", "template": updated}


async def delete_template(channel_id: str, template_id: str) -> dict:
    channel = get_channel(channel_id)
    meta_client = _get_meta_client(channel)

    sb = get_supabase()
    res = (
        sb.table("message_templates")
        .select("*")
        .eq("id", template_id)
        .eq("channel_id", channel_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Template not found")
    template = res.data[0]

    meta_template_id = template.get("meta_template_id")
    if meta_template_id:
        try:
            await meta_client.delete_template(meta_template_id)
        except Exception:
            logger.warning(
                "Failed to delete template %s from Meta, proceeding with local cancellation",
                meta_template_id,
            )

    sb.table("message_templates").update({"status": "cancelled"}).eq("id", template_id).execute()
    return {"status": "cancelled"}

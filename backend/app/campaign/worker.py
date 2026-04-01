import asyncio
import logging
import random

from app.db.supabase import get_supabase
from app.channels.service import get_channel
from app.providers.registry import get_provider

logger = logging.getLogger(__name__)


async def run_worker():
    """Main worker loop: polls for running campaigns and sends templates."""
    logger.info("Campaign worker started")

    while True:
        try:
            await process_campaigns()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)


async def process_campaigns():
    sb = get_supabase()

    campaigns = (
        sb.table("campaigns")
        .select("*")
        .eq("status", "running")
        .execute()
        .data
    )

    for campaign in campaigns:
        await process_single_campaign(campaign)


async def process_single_campaign(campaign: dict):
    sb = get_supabase()
    campaign_id = campaign["id"]
    channel_id = campaign.get("channel_id")

    if not channel_id:
        logger.error(f"Campaign {campaign_id} has no channel_id")
        return

    channel = get_channel(channel_id)
    if not channel.get("is_active"):
        logger.warning(f"Campaign {campaign_id} channel {channel_id} is inactive, skipping")
        return
    provider = get_provider(channel)

    # Get next batch of conversations to send
    convs = (
        sb.table("conversations")
        .select("id, lead_id, leads(id, phone)")
        .eq("campaign_id", campaign_id)
        .eq("status", "imported")
        .limit(10)
        .execute()
        .data
    )

    if not convs:
        sb.table("campaigns").update({"status": "completed"}).eq("id", campaign_id).execute()
        logger.info(f"Campaign {campaign_id} completed")
        return

    for conv in convs:
        # Check if campaign is still running
        current = sb.table("campaigns").select("status").eq("id", campaign_id).single().execute().data
        if current["status"] != "running":
            logger.info(f"Campaign {campaign_id} paused, stopping")
            return

        lead = conv.get("leads", {})
        phone = lead.get("phone") if lead else None
        if not phone:
            continue

        try:
            await provider.send_template(
                to=phone,
                template_name=campaign["template_name"],
                components=campaign.get("template_params", {}).get("components") if campaign.get("template_params") else None,
            )
            sb.table("conversations").update({"status": "template_sent"}).eq("id", conv["id"]).execute()
            sb.rpc("increment_campaign_sent", {"campaign_id_param": campaign_id}).execute()
            logger.info(f"Template sent to {phone}")

        except Exception as e:
            logger.error(f"Failed to send to {phone}: {e}")
            sb.table("conversations").update({"status": "failed"}).eq("id", conv["id"]).execute()

        interval = random.randint(
            campaign.get("send_interval_min", 3),
            campaign.get("send_interval_max", 8),
        )
        await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())

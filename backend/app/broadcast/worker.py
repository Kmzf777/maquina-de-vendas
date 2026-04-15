import asyncio
import logging
import random
from datetime import datetime, timezone

from app.db.supabase import get_supabase
from app.whatsapp.client import send_template
from app.broadcast.service import (
    get_pending_broadcast_leads,
    mark_broadcast_lead_sent,
    mark_broadcast_lead_failed,
    increment_broadcast_sent,
    increment_broadcast_failed,
)
from app.cadence.service import create_enrollment
from app.cadence.scheduler import (
    process_due_cadences,
    process_reengagements,
    process_stagnation_triggers,
    calculate_next_send_at,
)

logger = logging.getLogger(__name__)


async def run_worker():
    """Main worker loop: processes broadcasts, cadences, and stagnation triggers."""
    logger.info("Broadcast + Cadence worker started")

    while True:
        try:
            await process_broadcasts()
            await process_due_cadences()
            await process_reengagements()
            await process_stagnation_triggers()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)


async def process_broadcasts():
    """Find running broadcasts and send pending templates."""
    sb = get_supabase()
    broadcasts = (
        sb.table("broadcasts")
        .select("*")
        .eq("status", "running")
        .execute()
        .data
    )

    for broadcast in broadcasts:
        await process_single_broadcast(broadcast)


async def process_single_broadcast(broadcast: dict):
    sb = get_supabase()
    broadcast_id = broadcast["id"]

    pending_leads = get_pending_broadcast_leads(broadcast_id, limit=10)

    if not pending_leads:
        # Check if all leads are processed
        remaining = (
            sb.table("broadcast_leads")
            .select("id", count="exact")
            .eq("broadcast_id", broadcast_id)
            .eq("status", "pending")
            .execute()
            .count
        )
        if not remaining:
            sb.table("broadcasts").update({"status": "completed"}).eq("id", broadcast_id).execute()
            logger.info(f"Broadcast {broadcast_id} completed")
        return

    for bl in pending_leads:
        # Check if still running
        current = sb.table("broadcasts").select("status").eq("id", broadcast_id).single().execute().data
        if current["status"] != "running":
            return

        lead = bl["leads"]

        try:
            await send_template(
                to=lead["phone"],
                template_name=broadcast["template_name"],
                components=broadcast.get("template_variables", {}).get("components"),
            )
            mark_broadcast_lead_sent(bl["id"])
            increment_broadcast_sent(broadcast_id)

            # Enroll in cadence if configured
            if broadcast.get("cadence_id"):
                try:
                    cadence = sb.table("cadences").select("*").eq("id", broadcast["cadence_id"]).single().execute().data
                    if cadence:
                        first_step = (
                            sb.table("cadence_steps")
                            .select("delay_days")
                            .eq("cadence_id", cadence["id"])
                            .eq("step_order", 1)
                            .execute()
                            .data
                        )
                        delay = first_step[0]["delay_days"] if first_step else 1
                        next_send = calculate_next_send_at(
                            datetime.now(timezone.utc),
                            delay,
                            cadence.get("send_start_hour", 7),
                            cadence.get("send_end_hour", 18),
                        )
                        create_enrollment(
                            cadence_id=cadence["id"],
                            lead_id=lead["id"],
                            broadcast_id=broadcast_id,
                            next_send_at=next_send,
                        )
                except Exception as ce:
                    logger.warning(f"Could not enroll {lead['phone']} in cadence: {ce}")

            logger.info(f"Template sent to {lead['phone']}")

        except Exception as e:
            logger.error(f"Failed to send to {lead['phone']}: {e}")
            mark_broadcast_lead_failed(bl["id"], str(e))
            increment_broadcast_failed(broadcast_id)

        interval = random.randint(
            broadcast.get("send_interval_min", 3),
            broadcast.get("send_interval_max", 8),
        )
        await asyncio.sleep(interval)

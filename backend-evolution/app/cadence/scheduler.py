import logging
import random
import asyncio
from datetime import datetime, timezone, timedelta

from app.cadence.service import (
    get_due_cadences,
    get_reengagement_cadences,
    get_next_step,
    advance_cadence,
    cool_cadence,
    exhaust_cadence,
    resume_cadence,
)
from app.leads.service import save_message
from app.whatsapp.client import send_text
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# Brazil timezone offset (UTC-3)
BRT_OFFSET = timedelta(hours=-3)


def is_within_send_window(now_utc: datetime, start_hour: int = 7, end_hour: int = 18) -> bool:
    """Check if current time in BRT is within the send window."""
    brt_time = now_utc + BRT_OFFSET
    return start_hour <= brt_time.hour < end_hour


def calculate_next_send_at(
    now_utc: datetime,
    interval_hours: int,
    start_hour: int = 7,
    end_hour: int = 18,
) -> datetime:
    """Calculate the next send time, respecting the send window."""
    candidate = now_utc + timedelta(hours=interval_hours)
    candidate_brt = candidate + BRT_OFFSET

    if candidate_brt.hour < start_hour:
        # Before window — push to start_hour same day
        candidate_brt = candidate_brt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        return candidate_brt - BRT_OFFSET
    elif candidate_brt.hour >= end_hour:
        # After window — push to start_hour next day
        next_day = candidate_brt + timedelta(days=1)
        next_day = next_day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        return next_day - BRT_OFFSET

    return candidate


async def process_due_cadences(now: datetime | None = None):
    """Process all cadence states that are due for sending."""
    now = now or datetime.now(timezone.utc)
    cadences = get_due_cadences(now, limit=10)

    for cadence in cadences:
        lead = cadence["leads"]
        campaign = cadence["campaigns"]

        # Skip guards
        if campaign["status"] != "running":
            logger.info(f"[CADENCE] Skipping {lead['phone']} — campaign not running")
            continue
        if lead.get("human_control"):
            logger.info(f"[CADENCE] Skipping {lead['phone']} — human control active")
            continue
        if not is_within_send_window(now, campaign["cadence_send_start_hour"], campaign["cadence_send_end_hour"]):
            logger.info(f"[CADENCE] Skipping {lead['phone']} — outside send window")
            continue

        stage = lead["stage"]
        next_step_order = cadence["current_step"] + 1
        step = get_next_step(cadence["campaign_id"], stage, next_step_order)

        if step is None:
            # No more steps for this stage
            cool_cadence(cadence["id"])
            sb = get_supabase()
            sb.rpc("increment_cadence_cooled", {"campaign_id_param": cadence["campaign_id"]}).execute()
            logger.info(f"[CADENCE] Lead {lead['phone']} cooled — no more steps for stage {stage}")
            continue

        try:
            await send_text(lead["phone"], step["message_text"])

            new_total = cadence["total_messages_sent"] + 1

            # Save to message history
            save_message(
                lead_id=cadence["lead_id"],
                role="assistant",
                content=step["message_text"],
                stage=stage,
                sent_by="cadence",
            )

            # Increment campaign counter
            sb = get_supabase()
            sb.rpc("increment_cadence_sent", {"campaign_id_param": cadence["campaign_id"]}).execute()

            # Check if exhausted after this send
            if new_total >= cadence["max_messages"]:
                exhaust_cadence(cadence["id"])
                sb.rpc("increment_cadence_exhausted", {"campaign_id_param": cadence["campaign_id"]}).execute()
                logger.info(f"[CADENCE] Lead {lead['phone']} exhausted — {new_total} messages sent")
            else:
                next_send = calculate_next_send_at(
                    now,
                    campaign["cadence_interval_hours"],
                    campaign["cadence_send_start_hour"],
                    campaign["cadence_send_end_hour"],
                )
                advance_cadence(cadence["id"], new_step=next_step_order, total_sent=new_total, next_send_at=next_send)
                logger.info(f"[CADENCE] Sent step {next_step_order} to {lead['phone']} (stage={stage})")

        except Exception as e:
            logger.error(f"[CADENCE] Failed to send to {lead['phone']}: {e}", exc_info=True)

        # Random delay between sends (2-5s)
        await asyncio.sleep(random.randint(2, 5))


async def process_reengagements(now: datetime | None = None):
    """Check for leads that responded but went silent — resume their cadence."""
    now = now or datetime.now(timezone.utc)
    cadences = get_reengagement_cadences(now)

    for cadence in cadences:
        lead = cadence["leads"]
        campaign = cadence["campaigns"]

        if campaign["status"] != "running":
            continue
        if lead.get("human_control"):
            continue
        if cadence["total_messages_sent"] >= cadence["max_messages"]:
            exhaust_cadence(cadence["id"])
            continue

        # Check if lead actually went silent (last_msg_at hasn't changed since responded_at)
        responded_at = cadence["responded_at"]
        last_msg_at = lead.get("last_msg_at")
        cooldown_hours = campaign["cadence_cooldown_hours"]

        # Parse responded_at if string
        if isinstance(responded_at, str):
            from dateutil.parser import parse
            responded_at = parse(responded_at)

        cooldown_deadline = responded_at + timedelta(hours=cooldown_hours)
        if now < cooldown_deadline:
            continue

        # If last_msg_at is after responded_at, lead is still active — skip
        if last_msg_at:
            if isinstance(last_msg_at, str):
                from dateutil.parser import parse
                last_msg_at = parse(last_msg_at)
            if last_msg_at > responded_at:
                continue

        # Resume cadence — reset step to 0 for current stage
        next_send = calculate_next_send_at(now, 0, 7, 18)  # Send ASAP within window
        resume_cadence(cadence["id"], next_send_at=next_send)
        logger.info(f"[CADENCE] Lead {lead['phone']} re-engaged — resuming cadence")

import logging
import random
import asyncio
from datetime import datetime, timezone, timedelta

from app.cadence.service import (
    get_due_enrollments,
    get_reengagement_enrollments,
    get_stagnation_cadences,
    get_next_step,
    advance_enrollment,
    complete_enrollment,
    exhaust_enrollment,
    resume_enrollment,
    create_enrollment,
    is_enrolled,
)
from app.leads.service import save_message
from app.whatsapp.client import send_text
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

BRT_OFFSET = timedelta(hours=-3)


def is_within_send_window(now_utc: datetime, start_hour: int = 7, end_hour: int = 18) -> bool:
    brt_time = now_utc + BRT_OFFSET
    return start_hour <= brt_time.hour < end_hour


def calculate_next_send_at(
    now_utc: datetime,
    delay_days: int = 0,
    start_hour: int = 7,
    end_hour: int = 18,
) -> datetime:
    candidate = now_utc + timedelta(days=delay_days)
    candidate_brt = candidate + BRT_OFFSET

    if candidate_brt.hour < start_hour:
        candidate_brt = candidate_brt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        return candidate_brt - BRT_OFFSET
    elif candidate_brt.hour >= end_hour:
        next_day = candidate_brt + timedelta(days=1)
        next_day = next_day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        return next_day - BRT_OFFSET

    return candidate


def _substitute_variables(text: str, lead: dict) -> str:
    """Replace {{nome}}, {{empresa}}, {{telefone}} with lead data."""
    text = text.replace("{{nome}}", lead.get("name") or "")
    text = text.replace("{{empresa}}", lead.get("company") or "")
    text = text.replace("{{telefone}}", lead.get("phone") or "")
    return text


async def process_due_cadences(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    enrollments = get_due_enrollments(now, limit=10)

    for enrollment in enrollments:
        lead = enrollment["leads"]
        cadence = enrollment["cadences"]

        if cadence["status"] != "active":
            continue
        if lead.get("human_control"):
            continue
        if not is_within_send_window(now, cadence["send_start_hour"], cadence["send_end_hour"]):
            continue

        next_step_order = enrollment["current_step"] + 1
        step = get_next_step(enrollment["cadence_id"], next_step_order)

        if step is None:
            complete_enrollment(enrollment["id"])
            logger.info(f"[CADENCE] Lead {lead['phone']} completed cadence — no more steps")
            continue

        try:
            message = _substitute_variables(step["message_text"], lead)
            await send_text(lead["phone"], message)

            new_total = enrollment["total_messages_sent"] + 1

            save_message(
                lead_id=enrollment["lead_id"],
                role="assistant",
                content=message,
                stage=lead.get("stage"),
                sent_by="cadence",
            )

            max_msgs = cadence["max_messages"]
            if new_total >= max_msgs:
                exhaust_enrollment(enrollment["id"])
                logger.info(f"[CADENCE] Lead {lead['phone']} exhausted — {new_total} messages")
            else:
                next_step = get_next_step(enrollment["cadence_id"], next_step_order + 1)
                delay = next_step["delay_days"] if next_step else 1
                next_send = calculate_next_send_at(now, delay, cadence["send_start_hour"], cadence["send_end_hour"])
                advance_enrollment(enrollment["id"], new_step=next_step_order, total_sent=new_total, next_send_at=next_send)
                logger.info(f"[CADENCE] Sent step {next_step_order} to {lead['phone']}")

        except Exception as e:
            logger.error(f"[CADENCE] Failed to send to {lead['phone']}: {e}", exc_info=True)

        await asyncio.sleep(random.randint(2, 5))


async def process_reengagements(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    enrollments = get_reengagement_enrollments(now)

    for enrollment in enrollments:
        lead = enrollment["leads"]
        cadence = enrollment["cadences"]

        if cadence["status"] != "active":
            continue
        if lead.get("human_control"):
            continue

        responded_at = enrollment["responded_at"]
        if isinstance(responded_at, str):
            from dateutil.parser import parse
            responded_at = parse(responded_at)

        cooldown_deadline = responded_at + timedelta(hours=cadence["cooldown_hours"])
        if now < cooldown_deadline:
            continue

        last_msg_at = lead.get("last_msg_at")
        if last_msg_at:
            if isinstance(last_msg_at, str):
                from dateutil.parser import parse
                last_msg_at = parse(last_msg_at)
            if last_msg_at > responded_at:
                continue

        next_send = calculate_next_send_at(now, 0, 7, 18)
        resume_enrollment(enrollment["id"], next_send_at=next_send)
        logger.info(f"[CADENCE] Lead {lead['phone']} re-engaged — resuming cadence")


async def process_stagnation_triggers(now: datetime | None = None):
    """Check for leads/deals stuck in stages and auto-enroll in cadences."""
    now = now or datetime.now(timezone.utc)
    cadences = get_stagnation_cadences()
    sb = get_supabase()

    for cadence in cadences:
        target_type = cadence["target_type"]
        target_stage = cadence["target_stage"]
        stagnation_days = cadence["stagnation_days"]

        if not target_stage or not stagnation_days:
            continue

        cutoff = (now - timedelta(days=stagnation_days)).isoformat()

        if target_type == "lead_stage":
            leads = (
                sb.table("leads")
                .select("id, phone")
                .eq("stage", target_stage)
                .eq("human_control", False)
                .lte("entered_stage_at", cutoff)
                .limit(20)
                .execute()
                .data
            )
            for lead in leads:
                if not is_enrolled(cadence["id"], lead["id"]):
                    try:
                        next_send = calculate_next_send_at(now, 0, cadence["send_start_hour"], cadence["send_end_hour"])
                        create_enrollment(cadence["id"], lead["id"], next_send_at=next_send)
                        logger.info(f"[STAGNATION] Enrolled lead {lead['phone']} in cadence '{cadence['name']}'")
                    except Exception as e:
                        logger.warning(f"[STAGNATION] Failed to enroll lead {lead['id']}: {e}")

        elif target_type == "deal_stage":
            deals = (
                sb.table("deals")
                .select("id, lead_id, leads!inner(id, phone, human_control)")
                .eq("stage", target_stage)
                .lte("updated_at", cutoff)
                .limit(20)
                .execute()
                .data
            )
            for deal in deals:
                lead = deal["leads"]
                if lead.get("human_control"):
                    continue
                if not is_enrolled(cadence["id"], lead["id"]):
                    try:
                        next_send = calculate_next_send_at(now, 0, cadence["send_start_hour"], cadence["send_end_hour"])
                        create_enrollment(cadence["id"], lead["id"], deal_id=deal["id"], next_send_at=next_send)
                        logger.info(f"[STAGNATION] Enrolled deal {deal['id']} in cadence '{cadence['name']}'")
                    except Exception as e:
                        logger.warning(f"[STAGNATION] Failed to enroll deal {deal['id']}: {e}")

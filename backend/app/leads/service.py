import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"[^\d]+")


def normalize_phone(phone: str | None) -> str:
    """Normalize to E.164 without '+'. Injects the Brazilian 9th digit when missing."""
    if not phone:
        return ""
    if phone.startswith("whatsapp:"):
        phone = phone[len("whatsapp:"):]
    digits = _PHONE_RE.sub("", phone)
    # Brazilian mobiles stored without 9th digit: 55 + 2-digit DDD + 8 digits = 12 total
    if len(digits) == 12 and digits.startswith("55"):
        digits = digits[:4] + "9" + digits[4:]
    return digits


def get_or_create_lead(
    phone: str,
    name: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    normalized = normalize_phone(phone)

    # Digits-only form without 9th digit injection — matches legacy DB rows stored before normalization
    digits_only = _PHONE_RE.sub("", phone[len("whatsapp:"):] if phone.startswith("whatsapp:") else phone)

    # Look up by normalized phone first. Fallback to digits-only to catch legacy rows.
    result = sb.table("leads").select("*").eq("phone", normalized).execute()
    if result.data:
        lead = result.data[0]
        # Backfill name from WhatsApp push_name if the lead has none yet.
        if name and not lead.get("name"):
            try:
                sb.table("leads").update({"name": name}).eq("id", lead["id"]).execute()
                lead = {**lead, "name": name}
            except Exception as exc:
                logger.warning("leads.service: failed to backfill name for lead %s: %s", lead["id"], exc)
        return lead

    if digits_only != normalized:
        legacy = sb.table("leads").select("*").eq("phone", digits_only).execute()
        if legacy.data:
            # Backfill: rewrite legacy row to the normalized phone so future lookups match.
            row = dict(legacy.data[0])
            try:
                update_fields: dict[str, Any] = {"phone": normalized}
                if name and not row.get("name"):
                    update_fields["name"] = name
                sb.table("leads").update(update_fields).eq("id", row["id"]).execute()
                row["phone"] = normalized
                if "name" in update_fields:
                    row["name"] = name
            except Exception as exc:
                logger.warning(
                    "leads.service: failed to backfill phone normalization for lead %s: %s",
                    row.get("id"), exc,
                )
            return row

    # Reverse 9th-digit lookup: incoming phone is 13 digits (with 9), but DB has
    # the old 12-digit format (without the 9th digit).  This happens when leads are
    # imported directly with legacy numbers and then reply after a broadcast — Meta
    # always returns the full 13-digit number in the from_number field.
    if len(normalized) == 13 and normalized.startswith("55") and normalized[4] == "9":
        twelve_digit = normalized[:4] + normalized[5:]
        legacy12 = sb.table("leads").select("*").eq("phone", twelve_digit).execute()
        if legacy12.data:
            row = dict(legacy12.data[0])
            try:
                update_fields = {"phone": normalized}
                if name and not row.get("name"):
                    update_fields["name"] = name
                sb.table("leads").update(update_fields).eq("id", row["id"]).execute()
                row["phone"] = normalized
                if "name" in update_fields:
                    row["name"] = name
                logger.info(
                    "leads.service: backfilled phone (12→13 digit) for lead %s: %s → %s",
                    row.get("id"), twelve_digit, normalized,
                )
            except Exception as exc:
                logger.warning(
                    "leads.service: failed to backfill phone (12→13 digit) for lead %s: %s",
                    row.get("id"), exc,
                )
            return row

    # No-country-code lookup (11 digits): lead was imported as DDD + 9 + 8 digits without "55".
    # Meta always returns the full 13-digit E.164 number, so this bridges the gap.
    if len(normalized) == 13 and normalized.startswith("55"):
        eleven_digit = normalized[2:]  # strip "55" prefix
        legacy11 = sb.table("leads").select("*").eq("phone", eleven_digit).execute()
        if legacy11.data:
            row = dict(legacy11.data[0])
            try:
                update_fields: dict[str, Any] = {"phone": normalized}
                if name and not row.get("name"):
                    update_fields["name"] = name
                sb.table("leads").update(update_fields).eq("id", row["id"]).execute()
                row["phone"] = normalized
                if "name" in update_fields:
                    row["name"] = name
                logger.info(
                    "leads.service: backfilled phone (11→13 digit) for lead %s: %s → %s",
                    row.get("id"), eleven_digit, normalized,
                )
            except Exception as exc:
                logger.warning(
                    "leads.service: failed to backfill phone (11→13 digit) for lead %s: %s",
                    row.get("id"), exc,
                )
            return row

    # No-country-code + no-9th-digit lookup (10 digits): lead stored as DDD + 8 digits only.
    if len(normalized) == 13 and normalized.startswith("55") and normalized[4] == "9":
        ten_digit = normalized[2:4] + normalized[5:]  # DDD + 8 digits, no country code, no 9
        legacy10 = sb.table("leads").select("*").eq("phone", ten_digit).execute()
        if legacy10.data:
            row = dict(legacy10.data[0])
            try:
                update_fields = {"phone": normalized}
                if name and not row.get("name"):
                    update_fields["name"] = name
                sb.table("leads").update(update_fields).eq("id", row["id"]).execute()
                row["phone"] = normalized
                if "name" in update_fields:
                    row["name"] = name
                logger.info(
                    "leads.service: backfilled phone (10→13 digit) for lead %s: %s → %s",
                    row.get("id"), ten_digit, normalized,
                )
            except Exception as exc:
                logger.warning(
                    "leads.service: failed to backfill phone (10→13 digit) for lead %s: %s",
                    row.get("id"), exc,
                )
            return row

    new_lead: dict[str, Any] = {"phone": normalized, "stage": "pending", "status": "imported"}
    if name:
        new_lead["name"] = name
    if channel:
        new_lead["channel"] = channel
    result = sb.table("leads").insert(new_lead).execute()
    return result.data[0]


def update_lead(lead_id: str, **fields) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").update(fields).eq("id", lead_id).execute()
    return result.data[0]


def reset_lead(lead_id: str) -> None:
    """Reset lead: delete message history and reset stage to secretaria on both lead and conversations."""
    sb = get_supabase()
    sb.table("messages").delete().eq("lead_id", lead_id).execute()
    sb.table("leads").update({
        "stage": "secretaria",
        "status": "active",
    }).eq("id", lead_id).execute()
    sb.table("conversations").update({
        "stage": "secretaria",
        "status": "active",
    }).eq("lead_id", lead_id).execute()


_DEV_PURGE_WHITELIST = {"553496652412", "5534996652412"}


def purge_dev_lead(phone: str) -> dict:
    """Hard purge: deletes ALL CRM data for a dev phone number in correct FK order.

    Only allowed for phones in _DEV_PURGE_WHITELIST. Raises ValueError for any other number.
    meta_webhook_logs is intentionally preserved for audit history.
    """
    normalized = normalize_phone(phone)
    if normalized not in _DEV_PURGE_WHITELIST:
        raise ValueError(f"purge_dev_lead: phone {normalized!r} not in dev whitelist")

    sb = get_supabase()
    lead_res = sb.table("leads").select("id").eq("phone", normalized).execute()
    if not lead_res.data:
        return {"purged": False, "reason": "lead not found"}

    lead_id = lead_res.data[0]["id"]

    sb.table("follow_up_jobs").delete().eq("lead_id", lead_id).execute()
    sb.table("cadence_enrollments").delete().eq("lead_id", lead_id).execute()
    sb.table("broadcast_leads").delete().eq("lead_id", lead_id).execute()
    sb.table("deals").delete().eq("lead_id", lead_id).execute()
    sb.table("lead_tags").delete().eq("lead_id", lead_id).execute()
    sb.table("messages").delete().eq("lead_id", lead_id).execute()
    sb.table("conversations").delete().eq("lead_id", lead_id).execute()
    sb.table("leads").delete().eq("id", lead_id).execute()

    return {"purged": True, "lead_id": lead_id, "phone": normalized}


def save_message(lead_id: str, role: str, content: str, stage: str | None = None, sent_by: str = "agent", conversation_id: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    msg = {
        "lead_id": lead_id,
        "role": role,
        "content": content,
        "stage": stage,
        "sent_by": sent_by,
    }
    if conversation_id:
        msg["conversation_id"] = conversation_id
    result = sb.table("messages").insert(msg).execute()
    return result.data[0]


CATEGORY_PIPELINE_NAMES: dict[str, str] = {
    "atacado": "Atacado",
    "private_label": "Private Label",
    "exportacao": "Exportação",
    "consumo": "Consumo",
}


def get_lead(lead_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).limit(1).execute()
    return result.data[0] if result.data else None


def create_deal(lead_id: str, title: str, category: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    pipeline_id: str | None = None
    stage_id: str | None = None

    pipeline_name = CATEGORY_PIPELINE_NAMES.get(category or "")
    if pipeline_name:
        p = sb.table("pipelines").select("id").eq("name", pipeline_name).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]

    if not pipeline_id:
        p = sb.table("pipelines").select("id").order("order_index", desc=False).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]

    if pipeline_id:
        s = (
            sb.table("pipeline_stages")
            .select("id")
            .eq("pipeline_id", pipeline_id)
            .eq("is_protected", False)
            .order("order_index", desc=False)
            .limit(1)
            .execute()
        )
        if s.data:
            stage_id = s.data[0]["id"]

    deal = {
        "lead_id": lead_id,
        "title": title,
        "stage": "novo",
        "category": category,
        "pipeline_id": pipeline_id,
        "stage_id": stage_id,
    }
    result = sb.table("deals").insert(deal).execute()
    return result.data[0]


def get_history(lead_id: str, limit: int = 30) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("role, content, stage, created_at")
        .eq("lead_id", lead_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data

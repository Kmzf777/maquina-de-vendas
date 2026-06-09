"""Landing-page webhook service.

Handles leads arriving from landing pages:
  1. Normalizes phone and upserts lead in Supabase.
  2. Optionally creates a conversation if channel_id is configured.
  3. Optionally schedules a follow-up job (job_type='lp_welcome') via follow_up_jobs.

Config is persisted in Redis under REDIS_CONFIG_KEY so it can be changed at runtime
without a deploy.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.config import get_settings
from app.db.supabase import get_supabase
from app.leads.service import normalize_phone, get_or_create_lead
from app.conversations.service import get_or_create_conversation
from app.lp_webhook.phone import normalize_lp_phone

logger = logging.getLogger(__name__)

REDIS_CONFIG_KEY = "lp_webhook:config"

_DEFAULT_CONFIG: dict[str, Any] = {
    "channel_id": "",
    "template_name": "",
    "language_code": "pt_BR",
    "delay_minutes": 15,
}

# Use same pattern as follow_up/service.py
_ENV_TAG = "dev" if get_settings().is_dev_env else "production"


async def get_lp_config(redis) -> dict:
    """Read config from Redis. Returns defaults merged with stored values when set."""
    raw = await redis.get(REDIS_CONFIG_KEY)
    if not raw:
        return dict(_DEFAULT_CONFIG)
    try:
        stored = json.loads(raw)
    except Exception:
        logger.warning("lp_webhook.service: invalid JSON in Redis config, using defaults")
        return dict(_DEFAULT_CONFIG)
    return {**_DEFAULT_CONFIG, **stored}


async def save_lp_config(redis, config: dict) -> None:
    """Persist config to Redis as JSON string."""
    await redis.set(REDIS_CONFIG_KEY, json.dumps(config))


async def process_landing_page_lead(payload: dict, redis) -> dict:
    """
    Main handler for landing-page lead submissions.

    Steps:
    1. normalize_phone(payload["whatsapp"]) — if empty/invalid return error
    2. get_or_create_lead(phone, name=payload["nome"])
    3. Update leads.email if payload["email"] non-empty
    4. Update leads.metadata merging {"origem": payload["origem"]} if origem non-empty
    5. get_lp_config(redis)
    6. get_or_create_conversation(lead_id, config["channel_id"]) — only if channel_id non-empty
    7. _schedule_lp_welcome(...) — only if channel_id AND template_name AND conversation_id all non-empty
    8. Return {"ok": True, "lead_id": "...", "conversation_id": "..." or None}

    All errors are caught, logged, and returned as {"ok": False, "error": "..."}.
    """
    try:
        # Step 1 — normalize phone
        raw_phone = payload.get("whatsapp", "")
        phone, phone_confidence = normalize_lp_phone(raw_phone)
        if not phone:
            return {"ok": False, "error": "Telefone inválido ou ausente"}

        # Step 2 — upsert lead
        nome = payload.get("nome") or None
        lead = get_or_create_lead(phone, name=nome)
        lead_id: str = lead["id"]

        sb = get_supabase()

        # Step 3 — update email if provided
        email = (payload.get("email") or "").strip()
        if email:
            try:
                sb.table("leads").update({"email": email}).eq("id", lead_id).execute()
            except Exception as exc:
                logger.warning("lp_webhook: failed to update email for lead %s: %s", lead_id, exc)

        # Step 3b — preserve raw phone in metadata if normalization was imprecise
        if raw_phone.strip() and phone_confidence != "ok":
            try:
                existing_meta_raw: dict = lead.get("metadata") or {}
                new_meta_raw = {**existing_meta_raw, "phone_raw": raw_phone.strip()}
                sb.table("leads").update({"metadata": new_meta_raw}).eq("id", lead_id).execute()
            except Exception as exc:
                logger.warning("lp_webhook: failed to save phone_raw for lead %s: %s", lead_id, exc)

        # Step 4 — merge origem into metadata
        origem = (payload.get("origem") or "").strip()
        if origem:
            try:
                existing_meta: dict = lead.get("metadata") or {}
                new_meta = {**existing_meta, "origem": origem}
                sb.table("leads").update({"metadata": new_meta}).eq("id", lead_id).execute()
            except Exception as exc:
                logger.warning("lp_webhook: failed to update metadata for lead %s: %s", lead_id, exc)

        # Step 4b — tag lead as "número incerto" if phone was not recognized
        if phone_confidence == "uncertain":
            try:
                _tag_lead_phone_uncertain(lead_id)
            except Exception as exc:
                logger.warning("lp_webhook: failed to tag uncertain phone for lead %s: %s", lead_id, exc)

        # Step 5 — load config
        config = await get_lp_config(redis)
        channel_id: str = config.get("channel_id", "")
        template_name: str = config.get("template_name", "")
        language_code: str = config.get("language_code", "pt_BR")
        delay_minutes: int = int(config.get("delay_minutes", 15))

        logger.info(
            "[LP_WELCOME] Config carregada: channel_id=%r template_name=%r delay_minutes=%d lead=%s",
            channel_id, template_name, delay_minutes, lead_id,
        )

        conversation_id: str | None = None

        # Step 6 — create conversation if channel configured
        if not channel_id:
            logger.warning("[LP_WELCOME] channel_id vazio — job NÃO será agendado. Configure em /config > Landing Pages.")
        else:
            try:
                conv = get_or_create_conversation(lead_id, channel_id)
                conversation_id = conv["id"]
                logger.info("[LP_WELCOME] Conversa obtida: conversation_id=%s lead=%s", conversation_id, lead_id)
            except Exception as exc:
                logger.error(
                    "[LP_WELCOME] Falha ao obter/criar conversa lead=%s channel=%s: %s",
                    lead_id, channel_id, exc,
                )

        if not template_name:
            logger.warning("[LP_WELCOME] template_name vazio — job NÃO será agendado. Configure em /config > Landing Pages.")

        # Step 7 — schedule welcome job if everything is available
        if channel_id and template_name and conversation_id:
            try:
                _schedule_lp_welcome(
                    conversation_id=conversation_id,
                    lead_id=lead_id,
                    channel_id=channel_id,
                    lead_phone=phone,
                    lead_name=lead.get("name") or "",
                    template_name=template_name,
                    language_code=language_code,
                    delay_minutes=delay_minutes,
                )
            except Exception as exc:
                logger.error(
                    "[LP_WELCOME] Falha ao agendar job lp_welcome lead=%s conversation=%s: %s",
                    lead_id, conversation_id, exc,
                )
        elif not (channel_id and template_name and conversation_id):
            logger.warning(
                "[LP_WELCOME] Job NÃO agendado — channel_id=%r template_name=%r conversation_id=%r lead=%s",
                bool(channel_id), bool(template_name), bool(conversation_id), lead_id,
            )

        logger.info(
            "[LP_WEBHOOK] Lead processado: lead_id=%s phone=%s confidence=%s",
            lead_id, phone, phone_confidence,
        )
        return {"ok": True, "lead_id": lead_id, "conversation_id": conversation_id}

    except Exception as exc:
        logger.exception("lp_webhook: unexpected error processing lead: %s", exc)
        return {"ok": False, "error": str(exc)}


def _tag_lead_phone_uncertain(lead_id: str) -> None:
    """Ensure the lead has the 'número incerto' tag applied."""
    sb = get_supabase()
    TAG_NAME = "número incerto"
    tag_result = sb.table("tags").select("id").eq("name", TAG_NAME).limit(1).execute()
    if tag_result.data:
        tag_id = tag_result.data[0]["id"]
    else:
        created = sb.table("tags").insert({"name": TAG_NAME}).execute()
        tag_id = created.data[0]["id"]
    try:
        sb.table("lead_tags").insert({"lead_id": lead_id, "tag_id": tag_id}).execute()
    except Exception:
        pass  # already tagged — ignore duplicate key error


def _schedule_lp_welcome(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    lead_phone: str,
    template_name: str,
    language_code: str,
    delay_minutes: int,
    lead_name: str = "",
) -> None:
    """Insert a follow_up_jobs row with job_type='lp_welcome'.

    Raises RuntimeError if the insert returns empty data.
    """
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    fire_at = (now + timedelta(minutes=delay_minutes)).isoformat()

    job = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "channel_id": channel_id,
        "sequence": 1,
        "fire_at": fire_at,
        "status": "pending",
        "env_tag": _ENV_TAG,
        "job_type": "lp_welcome",
        "metadata": {
            "lead_phone": lead_phone,
            "lead_name": lead_name,
            "template_name": template_name,
            "language_code": language_code,
        },
    }

    # Cancel any existing pending lp_welcome jobs for this conversation (idempotency)
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": "rescheduled",
    }).eq("conversation_id", conversation_id).eq("status", "pending").eq("job_type", "lp_welcome").execute()

    try:
        result = sb.table("follow_up_jobs").insert(job).execute()
    except Exception as exc:
        logger.error(
            "[LP_WELCOME] Erro ao inserir job para lead %s: %s", lead_id, exc
        )
        raise RuntimeError(
            f"Falha ao agendar job lp_welcome para lead {lead_id}"
        ) from exc

    if not result.data:
        raise RuntimeError(
            f"lp_welcome insert returned empty data for lead {lead_id}"
        )

    logger.info(
        "[LP_WELCOME] Agendado em %dmin lead=%s conversation=%s",
        delay_minutes, lead_id, conversation_id,
    )

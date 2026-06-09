import logging
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_BILLING_ERROR_CODE = 131042


def create_system_alert(
    type: str,
    title: str,
    message: str,
    severity: str = "error",
    metadata: dict | None = None,
) -> None:
    try:
        sb = get_supabase()
        sb.table("system_alerts").insert({
            "type": type,
            "severity": severity,
            "title": title,
            "message": message,
            "metadata": metadata or {},
        }).execute()
    except Exception as exc:
        logger.error("[ALERT] Failed to persist system alert type=%s: %s", type, exc)


async def fire_billing_alert(errors: list) -> None:
    """Create billing alert and notify via WhatsApp — deduplicated to once per hour."""
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    try:
        existing = (
            sb.table("system_alerts")
            .select("id")
            .eq("type", "billing_payment_issue")
            .eq("resolved", False)
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
        )
        if existing.data:
            return
    except Exception as exc:
        logger.error("[ALERT] Failed to check existing billing alert: %s", exc)

    title = "Pagamento pendente na conta WhatsApp"
    message = (
        "Mensagens estão falhando com erro 131042 (Business eligibility payment issue). "
        "Acesse o Business Manager da Meta e quite o débito para retomar os envios."
    )
    logger.critical("[ALERT][BILLING] %s", message)
    create_system_alert(
        "billing_payment_issue", title, message,
        severity="critical",
        metadata={"meta_errors": errors},
    )
    await _send_whatsapp_alert(title, message)


async def _send_whatsapp_alert(title: str, message: str) -> None:
    from app.config import get_settings
    from app.channels.service import get_channel_by_provider_config
    from app.whatsapp.meta import MetaCloudClient

    settings = get_settings()
    alert_phone = getattr(settings, "alert_phone", None) or ""
    if not alert_phone:
        logger.warning("[ALERT] ALERT_PHONE not configured — WhatsApp alert skipped")
        return

    try:
        joao_channel = get_channel_by_provider_config("phone_number_id", "1049315514934778", "meta_cloud")
        if not joao_channel:
            logger.error("[ALERT] João channel not found — cannot send WhatsApp alert")
            return
        provider = MetaCloudClient(joao_channel["provider_config"])
        text = f"⚠️ *ALERTA CRM*\n\n*{title}*\n\n{message}"
        await provider.send_text(alert_phone, text)
        logger.info("[ALERT] WhatsApp alert sent to %s", alert_phone)
    except Exception as exc:
        logger.error("[ALERT] Failed to send WhatsApp alert: %s", exc)

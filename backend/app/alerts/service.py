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
    """Cria alerta de billing no banco (dedup: 1 por hora). Aparece como popup no CRM."""
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

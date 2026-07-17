import logging
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def log_execution(
    *,
    enrollment_id: str | None,
    campaign_id: str | None,
    lead_id: str | None = None,
    node_id: str | None = None,
    node_type: str | None = None,
    status: str,
    log: str | None = None,
) -> None:
    """Fail-soft append to campaign_execution_log. Never raises."""
    try:
        get_supabase().table("campaign_execution_log").insert({
            "enrollment_id": enrollment_id,
            "campaign_id": campaign_id,
            "lead_id": lead_id,
            "node_id": node_id,
            "node_type": node_type,
            "status": status,
            "log": log,
        }).execute()
    except Exception as exc:
        logger.warning("[EXEC_LOG] falha ao registrar execução: %s", exc)


def list_execution_log(campaign_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return the latest execution-log rows for a campaign, ordered newest first."""
    try:
        sb = get_supabase()
        return (
            sb.table("campaign_execution_log")
            .select("*")
            .eq("campaign_id", campaign_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )
    except Exception as exc:
        logger.warning("[EXEC_LOG] falha ao listar log de execução: %s", exc)
        return []

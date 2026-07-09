"""Orquestra o disparo de UMA conversão de etapa: dedup → Meta (CAPI, automático) → auditoria.

O lado Google é MANUAL: os eventos ficam gravados em conversion_events e são baixados como CSV
(importação de conversões offline do Google Ads) sob demanda — ver google_export.py. A dedup por
(deal_id, event) garante que mover o card ida-e-volta — ou o purchase por dois caminhos — não
redispara. Fail-soft: nenhuma etapa levanta.
"""
import logging
import threading
from typing import Any

from app.campaigns.capi_dispatcher import dispatch_conversion
from app.campaigns.conversion_log import already_fired, record_conversion_event
from app.db.supabase import get_supabase
from app.leads.service import get_lead

logger = logging.getLogger(__name__)


def fire_stage_conversion(lead: dict[str, Any], deal_id: str, event: str,
                          value: float | None = None, currency: str = "BRL") -> dict[str, Any]:
    """Dispara a conversão canônica p/ um (deal, event). Idempotente e fail-soft.

    Meta é enviado na hora (CAPI); Google fica registrado p/ exportação manual em CSV.
    """
    if not lead or not deal_id or not event:
        return {"skipped": "missing_args"}
    if already_fired(deal_id, event):
        logger.info("[CONV] (%s,%s) já disparado — skip", deal_id, event)
        return {"skipped": "already_fired"}

    meta_sent = False
    try:
        result = dispatch_conversion(lead, event, value, currency)
        meta_sent = bool(result.get("meta", {}).get("sent"))
    except Exception as exc:  # pragma: no cover - defensivo
        logger.error("[CONV] dispatch_conversion(%s,%s) falhou: %s", deal_id, event, exc)

    record_conversion_event(
        lead_id=lead.get("id"), deal_id=deal_id, event=event, value=value, currency=currency,
        gclid=lead.get("gclid"), ctwa_clid=lead.get("ctwa_clid"), sent_meta=meta_sent,
    )
    return {"sent_meta": meta_sent}


def fire_stage_conversion_background(lead: dict[str, Any], deal_id: str, event: str,
                                     value: float | None = None, currency: str = "BRL") -> None:
    """Versão não-bloqueante (daemon thread) p/ chamadores síncronos (worker de automação)."""
    def _run() -> None:
        try:
            fire_stage_conversion(lead, deal_id, event, value, currency)
        except Exception as exc:  # pragma: no cover - defensivo
            logger.error("[CONV] erro no disparo em background (%s,%s): %s", deal_id, event, exc)
    threading.Thread(target=_run, name="conv-dispatch", daemon=True).start()


def fire_conversion_for_deal_stage(lead_id: str, deal_id: str) -> None:
    """Shared helper: resolve the deal's current stage conversion_event/value and fire.

    Used by both campaigns/triggers._maybe_fire_stage_conversion (deal_stage_enter event)
    and engine._execute_action (move_deal_stage / mark_deal_won actions). Fail-soft — never
    raises; logs warnings on any error so the caller (tick) is never interrupted.
    """
    try:
        sb = get_supabase()
        rows = sb.table("deals").select("id, lead_id, stage_id, value").eq("id", deal_id).limit(1).execute().data
        if not rows:
            return
        deal = rows[0]
        stage_data = (
            sb.table("pipeline_stages")
            .select("conversion_event, conversion_value")
            .eq("id", deal.get("stage_id"))
            .single()
            .execute()
            .data
        )
        event = (stage_data or {}).get("conversion_event")
        if not event:
            return
        if event == "purchase":
            value = deal.get("value") if deal.get("value") is not None else (stage_data or {}).get("conversion_value")
        else:
            value = (stage_data or {}).get("conversion_value")
        lead = get_lead(lead_id) or {"id": lead_id}
        fire_stage_conversion_background(lead, deal_id, event, value=value)
    except Exception as exc:
        logger.warning("[CONV] fire_conversion_for_deal_stage(lead=%s, deal=%s) falhou: %s", lead_id, deal_id, exc)

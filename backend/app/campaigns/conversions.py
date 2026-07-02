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

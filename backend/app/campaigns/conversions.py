"""Orquestra o disparo de UMA conversão de etapa: dedup → Meta (direto) → Planilha → auditoria.

Fail-soft: nenhuma etapa levanta. Usado tanto pelo gancho de mudança de etapa do Kanban
(deal_stage_enter) quanto pelo caminho de venda (purchase). A dedup por (deal_id, event)
garante que mover o card ida-e-volta — ou o purchase chegar por dois caminhos — não redispara.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.campaigns.capi_dispatcher import dispatch_conversion
from app.campaigns.conversion_log import already_fired, record_conversion_event
from app.campaigns.sheets_export import append_conversion_row, build_sheet_row

logger = logging.getLogger(__name__)


def fire_stage_conversion(lead: dict[str, Any], deal_id: str, event: str,
                          value: float | None = None, currency: str = "BRL") -> dict[str, Any]:
    """Dispara a conversão canônica p/ um (deal, event). Idempotente e fail-soft."""
    if not lead or not deal_id or not event:
        return {"skipped": "missing_args"}
    if already_fired(deal_id, event):
        logger.info("[CONV] (%s,%s) já disparado — skip", deal_id, event)
        return {"skipped": "already_fired"}

    meta_sent = False
    sheet_synced = False
    try:
        result = dispatch_conversion(lead, event, value, currency)
        meta_sent = bool(result.get("meta", {}).get("sent"))
    except Exception as exc:  # pragma: no cover - defensivo
        logger.error("[CONV] dispatch_conversion(%s,%s) falhou: %s", deal_id, event, exc)

    try:
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        row = build_sheet_row(lead, event, value, currency, when)
        sheet_synced = bool(append_conversion_row(row).get("synced"))
    except Exception as exc:  # pragma: no cover - defensivo
        logger.error("[CONV] append_conversion_row(%s,%s) falhou: %s", deal_id, event, exc)

    record_conversion_event(
        lead_id=lead.get("id"), deal_id=deal_id, event=event, value=value, currency=currency,
        gclid=lead.get("gclid"), ctwa_clid=lead.get("ctwa_clid"),
        sent_meta=meta_sent, sheet_synced=sheet_synced,
    )
    return {"sent_meta": meta_sent, "sheet_synced": sheet_synced}


def fire_stage_conversion_background(lead: dict[str, Any], deal_id: str, event: str,
                                     value: float | None = None, currency: str = "BRL") -> None:
    """Versão não-bloqueante (daemon thread) p/ chamadores síncronos (worker de automação)."""
    def _run() -> None:
        try:
            fire_stage_conversion(lead, deal_id, event, value, currency)
        except Exception as exc:  # pragma: no cover - defensivo
            logger.error("[CONV] erro no disparo em background (%s,%s): %s", deal_id, event, exc)
    threading.Thread(target=_run, name="conv-dispatch", daemon=True).start()

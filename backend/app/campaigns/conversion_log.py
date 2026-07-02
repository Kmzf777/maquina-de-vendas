"""Dedup + auditoria dos eventos de conversão de anúncio (tabela conversion_events).

UNIQUE(deal_id, event) na base garante idempotência; aqui checamos antes p/ evitar disparo
duplicado à Meta/Planilha quando o card é movido de volta e de novo. Fail-soft: erros de I/O
nunca propagam (o disparo é acessório ao fluxo de venda).
"""
import logging
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def already_fired(deal_id: str, event: str) -> bool:
    """True se já existe um evento (deal_id, event) registrado."""
    try:
        sb = get_supabase()
        res = (
            sb.table("conversion_events").select("id")
            .eq("deal_id", deal_id).eq("event", event).limit(1).execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.error("conversion_log.already_fired(%s,%s) falhou: %s", deal_id, event, exc)
        return False  # fail-open: melhor tentar disparar do que engolir a conversão


def record_conversion_event(*, lead_id: str, deal_id: str, event: str, value: float | None,
                            currency: str, gclid: str | None, ctwa_clid: str | None,
                            sent_meta: bool, sheet_synced: bool) -> None:
    """Grava a linha de auditoria. Fail-soft."""
    row: dict[str, Any] = {
        "lead_id": lead_id, "deal_id": deal_id, "event": event, "value": value,
        "currency": currency, "gclid": gclid, "ctwa_clid": ctwa_clid,
        "sent_meta": sent_meta, "sheet_synced": sheet_synced,
    }
    try:
        get_supabase().table("conversion_events").insert(row).execute()
    except Exception as exc:
        logger.error("conversion_log.record_conversion_event(%s,%s) falhou: %s", deal_id, event, exc)

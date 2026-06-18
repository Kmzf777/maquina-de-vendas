"""Serviço de 'Venda Realizada' (deal Ganho).

Move o(s) deal(s) do lead para o stage 'Ganho' no CRM e devolve o lead resgatado, para
que o chamador dispare a conversão outbound (Meta CAPI / Google) de forma NÃO-bloqueante
(FastAPI BackgroundTasks no endpoint; daemon thread no worker de automação).

A atualização do CRM é síncrona/rápida; o disparo de conversão (sujeito à latência da
Meta) é responsabilidade do chamador, fora do caminho crítico.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase
from app.leads.service import get_lead

logger = logging.getLogger(__name__)


def _ganho_stage_id(sb, pipeline_id: str | None) -> str | None:
    """Resolve o stage_id de 'Ganho' dentro de um pipeline (key in ganho/fechado_ganho)."""
    if not pipeline_id:
        return None
    res = (
        sb.table("pipeline_stages")
        .select("id, key")
        .eq("pipeline_id", pipeline_id)
        .in_("key", ["ganho", "fechado_ganho"])
        .order("order_index", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0]["id"] if res.data else None


def mark_deal_won(
    lead_id: str,
    value: float | None = None,
    currency: str = "BRL",
    deal_id: str | None = None,
) -> dict[str, Any]:
    """Marca a venda como Ganha no CRM (atualização síncrona) e devolve o lead resgatado.

    - `deal_id` explícito → atualiza só aquele deal; senão, o deal mais recente do lead.
    - Grava stage='ganho', closed_at e (se informado) value no(s) deal(s).
    - NÃO dispara conversão: o chamador faz isso em background com o `lead` retornado.

    Retorna {"lead": <dict>, "deals_updated": <int>, "value": ..., "currency": ...}.
    """
    sb = get_supabase()
    now_iso = datetime.now(timezone.utc).isoformat()
    deals_updated = 0

    try:
        if deal_id:
            deals = sb.table("deals").select("id, pipeline_id").eq("id", deal_id).limit(1).execute().data
        else:
            deals = (
                sb.table("deals")
                .select("id, pipeline_id")
                .eq("lead_id", lead_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
                .data
            )
        for deal in (deals or []):
            update: dict[str, Any] = {"stage": "ganho", "closed_at": now_iso, "updated_at": now_iso}
            stage_id = _ganho_stage_id(sb, deal.get("pipeline_id"))
            if stage_id:
                update["stage_id"] = stage_id
            if value is not None:
                update["value"] = float(value)
            sb.table("deals").update(update).eq("id", deal["id"]).execute()
            deals_updated += 1
        logger.info("mark_deal_won: %d deal(s) marcados como Ganho para lead %s", deals_updated, lead_id)
    except Exception as exc:
        logger.error("mark_deal_won: falha ao marcar deal como Ganho para lead %s: %s", lead_id, exc, exc_info=True)

    lead = get_lead(lead_id) or {}
    return {"lead": lead, "deals_updated": deals_updated, "value": value, "currency": currency}

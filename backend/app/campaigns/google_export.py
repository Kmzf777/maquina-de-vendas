"""Exportação MANUAL das conversões do Google Ads em CSV (importação de conversões offline).

Meta vai automático via CAPI; o Google não tem endpoint simples (exigiria dev token), então o
operador baixa este CSV e sobe no Google Ads (Conversões → Importar → De um arquivo). Fonte: a
tabela conversion_events (eventos com gclid). Marca exported_at ao baixar p/ não duplicar.
"""
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_TZ_NAME = "America/Sao_Paulo"
_TZ = ZoneInfo(_TZ_NAME)

_CONVERSION_NAMES = {
    "lead": "Lead_Captado",
    "qualified": "Lead_Qualificado",
    "opportunity": "Oportunidade_Criada",
    "purchase": "Venda_Fechada",
}


def conversion_name_for(event: str) -> str:
    return _CONVERSION_NAMES.get(event, event)


def _fmt_time(created_at: Any) -> str:
    """created_at (ISO/UTC do Supabase) → 'YYYY-MM-DD HH:MM:SS' no fuso de São Paulo."""
    if not created_at:
        return ""
    dt = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_TZ).strftime("%Y-%m-%d %H:%M:%S")


def build_google_csv(rows: list[dict[str, Any]]) -> str:
    """Monta o CSV no template de conversões offline (por clique/gclid) do Google Ads."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([f"Parameters:TimeZone={_TZ_NAME}"])
    writer.writerow(["Google Click ID", "Conversion Name", "Conversion Time",
                     "Conversion Value", "Conversion Currency"])
    for r in rows:
        value = r.get("value")
        writer.writerow([
            r.get("gclid") or "",
            conversion_name_for(r.get("event") or ""),
            _fmt_time(r.get("created_at")),
            "" if value is None else value,
            r.get("currency") or "BRL",
        ])
    return buf.getvalue()


def fetch_pending_google_rows(include_all: bool = False) -> list[dict[str, Any]]:
    """Eventos com gclid; por padrão só os não exportados (exported_at IS NULL)."""
    sb = get_supabase()
    q = (
        sb.table("conversion_events")
        .select("id, gclid, event, value, currency, created_at")
        .not_.is_("gclid", "null")
    )
    if not include_all:
        q = q.is_("exported_at", "null")
    return q.order("created_at").execute().data or []


def mark_exported(ids: list[str]) -> None:
    if not ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        get_supabase().table("conversion_events").update({"exported_at": now}).in_("id", ids).execute()
    except Exception as exc:
        logger.error("google_export.mark_exported falhou: %s", exc)


def export_google_csv(include_all: bool = False, mark: bool = True) -> tuple[str, int]:
    """Retorna (csv_text, qtd_linhas). Marca exported_at nas linhas pendentes baixadas."""
    rows = fetch_pending_google_rows(include_all)
    csv_text = build_google_csv(rows)
    if mark and not include_all:
        mark_exported([r["id"] for r in rows if r.get("id")])
    return csv_text, len(rows)


def _has_gclid(row: dict[str, Any]) -> bool:
    val = row.get("gclid")
    return bool(val.strip()) if isinstance(val, str) else bool(val)


def aggregate_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega os eventos de conversão em métricas p/ o Dashboard (função pura, testável).

    - total: total de eventos registrados
    - meta_sent: quantos foram enviados à Meta (CAPI)
    - google_pending / google_exported: eventos com gclid ainda-não / já baixados no CSV
    - by_event: contagem por etapa canônica
    - purchase_value: soma do valor das vendas (event='purchase')
    """
    stats: dict[str, Any] = {
        "total": len(rows),
        "meta_sent": 0,
        "google_pending": 0,
        "google_exported": 0,
        "by_event": {"lead": 0, "qualified": 0, "opportunity": 0, "purchase": 0},
        "purchase_value": 0.0,
    }
    for r in rows:
        if r.get("sent_meta"):
            stats["meta_sent"] += 1
        if _has_gclid(r):
            if r.get("exported_at"):
                stats["google_exported"] += 1
            else:
                stats["google_pending"] += 1
        event = r.get("event")
        if event in stats["by_event"]:
            stats["by_event"][event] += 1
        if event == "purchase" and r.get("value") is not None:
            try:
                stats["purchase_value"] += float(r.get("value"))
            except (TypeError, ValueError):
                pass
    return stats


def conversion_stats() -> dict[str, Any]:
    """Lê os eventos de conversão e devolve as métricas agregadas. Fail-soft (zeros em erro)."""
    try:
        sb = get_supabase()
        rows = (
            sb.table("conversion_events")
            .select("event, sent_meta, exported_at, gclid, value")
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.error("conversion_stats falhou: %s", exc)
        rows = []
    return aggregate_stats(rows)

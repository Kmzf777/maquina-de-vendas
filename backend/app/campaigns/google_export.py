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

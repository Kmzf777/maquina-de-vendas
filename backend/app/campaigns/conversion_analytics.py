"""Analytics agregados das conversões p/ a seção do Dashboard (organic vs paid, série, ROI).

Funções puras (build_timeseries, aggregate_value_by_traffic) isoladas do I/O p/ teste. As
funções que tocam o banco (traffic_split, conversion_dashboard) são fail-soft (zeros em erro).
"""
import logging
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.db.supabase import get_supabase
from app.campaigns.google_export import conversion_stats

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("America/Sao_Paulo")
_TS_EVENTS = ("qualified", "opportunity", "purchase")


def _local_date(created_at: Any) -> date | None:
    if not created_at:
        return None
    try:
        dt = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ).date()
    except (ValueError, TypeError):
        return None


def build_timeseries(events: list[dict[str, Any]], days: int = 30, today: date | None = None) -> list[dict[str, Any]]:
    """Série dos últimos `days` dias (fuso SP), contando eventos por etapa. Dias sem evento = 0."""
    today = today or datetime.now(_TZ).date()
    buckets: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        key = d.isoformat()
        buckets[key] = {"date": key, "qualified": 0, "opportunity": 0, "purchase": 0}
    for ev in events:
        event = ev.get("event")
        if event not in _TS_EVENTS:
            continue
        d = _local_date(ev.get("created_at"))
        if d is None:
            continue
        key = d.isoformat()
        if key in buckets:
            buckets[key][event] += 1
    return list(buckets.values())


def aggregate_value_by_traffic(purchase_rows: list[dict[str, Any]]) -> dict[str, float]:
    """Soma o `value` das vendas por traffic_type do lead. Sem lead/tipo previsto → unknown."""
    out = {"paid": 0.0, "organic": 0.0, "unknown": 0.0}
    for r in purchase_rows:
        value = r.get("value")
        if value is None:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        leads = r.get("leads") or {}
        tt = leads.get("traffic_type") if isinstance(leads, dict) else None
        bucket = tt if tt in ("paid", "organic") else "unknown"
        out[bucket] += v
    return out


def _count(table: str, **eq) -> int:
    try:
        q = get_supabase().table(table).select("id", count="exact")
        for k, v in eq.items():
            q = q.is_(k, "null") if v is None else q.eq(k, v)
        return q.execute().count or 0
    except Exception as exc:
        logger.error("conversion_analytics._count(%s,%s) falhou: %s", table, eq, exc)
        return 0


def traffic_split() -> dict[str, int]:
    """Contagem de leads por traffic_type: paid / organic / unknown (NULL)."""
    return {
        "paid": _count("leads", traffic_type="paid"),
        "organic": _count("leads", traffic_type="organic"),
        "unknown": _count("leads", traffic_type=None),
    }


def conversion_dashboard() -> dict[str, Any]:
    """Compõe o payload do Dashboard. Fail-soft: qualquer falha vira zeros na parte afetada."""
    stats = conversion_stats()
    kpis = {
        "google_pending": stats.get("google_pending", 0),
        "google_exported": stats.get("google_exported", 0),
        "meta_sent": stats.get("meta_sent", 0),
        "purchase_value": stats.get("purchase_value", 0.0),
    }

    ts_events: list[dict[str, Any]] = []
    purchase_rows: list[dict[str, Any]] = []
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        ts_events = (
            get_supabase().table("conversion_events").select("event, created_at")
            .gte("created_at", cutoff).execute().data or []
        )
    except Exception as exc:
        logger.error("conversion_dashboard: falha no fetch da série: %s", exc)
    try:
        purchase_rows = (
            get_supabase().table("conversion_events").select("value, leads(traffic_type)")
            .eq("event", "purchase").execute().data or []
        )
    except Exception as exc:
        logger.error("conversion_dashboard: falha no fetch de valor por origem: %s", exc)

    return {
        "kpis": kpis,
        "traffic_split": traffic_split(),
        "timeseries": build_timeseries(ts_events, days=30),
        "value_by_traffic": aggregate_value_by_traffic(purchase_rows),
    }

"""Relatório de campanhas (/trafego): agrega leads por canal+campanha cruzando com vendas.

Funções puras (derive_channel, build_campaign_report) isoladas do I/O p/ teste.
As funções que tocam o banco (traffic_report, campaign_leads) são fail-soft.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_NO_CAMPAIGN = "(sem campanha)"
_CLOSER_STAGE_KEY = "qualificado"


def _s(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def derive_channel(lead: dict[str, Any]) -> str:
    """Canal do lead por prioridade de click-id. Retorna Google Ads/Meta Ads/Orgânico/Sem rastreio."""
    if _s(lead.get("gclid")):
        return "Google Ads"
    if _s(lead.get("fbclid")) or _s(lead.get("ctwa_clid")):
        return "Meta Ads"
    if _s(lead.get("traffic_type")).lower() == "organic" or _s(lead.get("utm_source")):
        return "Orgânico"
    return "Sem rastreio"


def build_campaign_report(
    leads: list[dict[str, Any]],
    conversed_ids: set[str],
    closer_ids: set[str],
    sales_by_lead: dict[str, dict[str, Any]],
    mode: str,
    period: str,
    spend_by_campaign: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Agrega os leads em linhas (canal, campanha). Puro — recebe coleções já buscadas.

    - conversed_ids / closer_ids: sets de lead_id que conversaram / chegaram ao closer.
    - sales_by_lead: lead_id -> {"count": int, "value": float} (já filtrado por modo).
    - spend_by_campaign: campaign_name normalizado (trim+lower) -> cost total (Google Ads).
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for lead in leads:
        lead_id = lead.get("id")
        channel = derive_channel(lead)
        campaign = _s(lead.get("utm_campaign")) or _NO_CAMPAIGN
        key = (channel, campaign)
        row = groups.get(key)
        if row is None:
            row = {"channel": channel, "campaign": campaign, "leads": 0, "conversas": 0,
                   "closer": 0, "clientes": 0, "pedidos": 0, "receita": 0.0, "investimento": 0.0}
            groups[key] = row
        row["leads"] += 1
        if lead_id in conversed_ids:
            row["conversas"] += 1
        if lead_id in closer_ids:
            row["closer"] += 1
        sale = sales_by_lead.get(lead_id)
        if sale:
            row["clientes"] += 1  # leads distintos que compraram (base da conversão)
            row["pedidos"] += int(sale.get("count", 0) or 0)  # nº de vendas (recompra: pode ser >1)
            row["receita"] += float(sale.get("value", 0.0) or 0.0)

    # Atribui investimento às linhas Google Ads via join normalizado (trim+lower).
    spend_by_campaign = spend_by_campaign or {}
    for row in groups.values():
        if row["channel"] == "Google Ads":
            row["investimento"] = float(spend_by_campaign.get(row["campaign"].strip().lower(), 0.0))

    rows: list[dict[str, Any]] = []
    total = {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
             "receita": 0.0, "investimento": 0.0}
    google_receita = 0.0
    for row in groups.values():
        pedidos = row["pedidos"]
        row["ticket_medio"] = round(row["receita"] / pedidos, 2) if pedidos else 0.0
        row["conversao"] = round(row["clientes"] / row["leads"], 4) if row["leads"] else 0.0
        inv = row["investimento"]
        row["roas"] = round(row["receita"] / inv, 2) if inv else None
        if row["channel"] == "Google Ads":
            google_receita += row["receita"]
        for k in total:
            total[k] += row[k]
        rows.append(row)

    channel_subtotals: dict[str, dict[str, Any]] = {}
    for row in rows:
        sub = channel_subtotals.get(row["channel"])
        if sub is None:
            sub = {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
                   "receita": 0.0, "investimento": 0.0}
            channel_subtotals[row["channel"]] = sub
        for k in sub:
            sub[k] += row[k]
    for sub in channel_subtotals.values():
        sub["receita"] = round(sub["receita"], 2)
        sub["investimento"] = round(sub["investimento"], 2)
        sub["roas"] = round(sub["receita"] / sub["investimento"], 2) if sub["investimento"] else None

    rows.sort(key=lambda r: (r["channel"], -r["receita"], -r["leads"]))
    total["receita"] = round(total["receita"], 2)
    total["investimento"] = round(total["investimento"], 2)
    total["roas"] = round(google_receita / total["investimento"], 2) if total["investimento"] else None
    return {"mode": mode, "period": period, "rows": rows, "total": total,
            "channel_subtotals": channel_subtotals}


_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}
_LEAD_COLS = ("id, name, phone, created_at, gclid, fbclid, ctwa_clid, "
              "utm_source, utm_medium, utm_campaign, traffic_type")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _resolve_window(period: str, date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    """Resolve a janela (lo, hi) em ISO. `date_from`/`date_to` (YYYY-MM-DD) têm precedência
    sobre `period`. Datas malformadas são ignoradas. Sem sinal → (None, None) = tudo."""
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    lo_explicit = df if _DATE_RE.match(df) else ""
    hi_explicit = dt if _DATE_RE.match(dt) else ""
    if lo_explicit or hi_explicit:
        lo = f"{lo_explicit}T00:00:00+00:00" if lo_explicit else None
        hi = f"{hi_explicit}T23:59:59.999999+00:00" if hi_explicit else None
        return lo, hi
    days = _PERIOD_DAYS.get(period)
    if not days:
        return None, None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(), None


def _chunks(items: list, size: int = 200):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fetch_leads(sb, mode: str, lo: str | None, hi: str | None) -> list[dict[str, Any]]:
    if mode == "sale":
        q = sb.table("sales").select("lead_id")
        if lo:
            q = q.gte("sold_at", lo)
        if hi:
            q = q.lte("sold_at", hi)
        sale_ids = sorted({r["lead_id"] for r in (q.execute().data or []) if r.get("lead_id")})
        leads: list[dict[str, Any]] = []
        for chunk in _chunks(sale_ids):
            data = sb.table("leads").select(_LEAD_COLS).in_("id", chunk).execute().data or []
            leads.extend(data)
        return leads
    q = sb.table("leads").select(_LEAD_COLS)
    if lo:
        q = q.gte("created_at", lo)
    if hi:
        q = q.lte("created_at", hi)
    return q.execute().data or []


def _conversed_ids(sb, lead_ids: list[str]) -> set[str]:
    out: set[str] = set()
    for chunk in _chunks(lead_ids):
        rows = (sb.table("conversations").select("lead_id, last_customer_message_at")
                .in_("lead_id", chunk).execute().data or [])
        for r in rows:
            if r.get("last_customer_message_at") and r.get("lead_id"):
                out.add(r["lead_id"])
    return out


def _closer_ids(sb, lead_ids: list[str]) -> set[str]:
    stages = sb.table("pipeline_stages").select("id, pipeline_id, key, order_index").execute().data or []
    stage_by_id = {s["id"]: s for s in stages}
    qualifica_idx: dict[str, int] = {
        s["pipeline_id"]: s["order_index"]
        for s in stages if s.get("key") == _CLOSER_STAGE_KEY and s.get("order_index") is not None
    }
    out: set[str] = set()
    for chunk in _chunks(lead_ids):
        deals = (sb.table("deals").select("lead_id, stage_id, pipeline_id")
                 .in_("lead_id", chunk).execute().data or [])
        for d in deals:
            stage = stage_by_id.get(d.get("stage_id"))
            if not stage or stage.get("order_index") is None:
                continue
            threshold = qualifica_idx.get(d.get("pipeline_id"))
            if threshold is not None and stage["order_index"] >= threshold:
                out.add(d["lead_id"])
    return out


def _sales_by_lead(sb, lead_ids: list[str], lo: str | None, hi: str | None, mode: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(lead_ids):
        q = sb.table("sales").select("lead_id, value, sold_at").in_("lead_id", chunk)
        if mode == "sale" and lo:
            q = q.gte("sold_at", lo)
        if mode == "sale" and hi:
            q = q.lte("sold_at", hi)
        for r in (q.execute().data or []):
            lid = r.get("lead_id")
            if not lid:
                continue
            agg = out.setdefault(lid, {"count": 0, "value": 0.0, "last_sold_at": None})
            agg["count"] += 1
            try:
                agg["value"] += float(r.get("value") or 0.0)
            except (TypeError, ValueError):
                pass
            # Track latest sale date via ISO string comparison (safe for ISO 8601 timestamps).
            sold_at = r.get("sold_at")
            if isinstance(sold_at, str) and sold_at:
                prev = agg["last_sold_at"]
                if prev is None or sold_at > prev:
                    agg["last_sold_at"] = sold_at
    return out


def _empty_report(mode: str, period: str) -> dict[str, Any]:
    return {"mode": mode, "period": period, "rows": [], "channel_subtotals": {},
            "total": {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
                      "receita": 0.0, "investimento": 0.0, "roas": None}}


def _spend_by_campaign(sb, lo: str | None, hi: str | None, platform: str = "google") -> dict[str, float]:
    """Soma cost de ad_spend por campaign_name normalizado (trim+lower), na janela. Fail-soft → {}."""
    try:
        q = sb.table("ad_spend").select("campaign_name, cost, date").eq("platform", platform)
        if lo:
            q = q.gte("date", lo[:10])
        if hi:
            q = q.lte("date", hi[:10])
        out: dict[str, float] = {}
        for r in (q.execute().data or []):
            name = (r.get("campaign_name") or "").strip().lower()
            if not name:
                continue
            try:
                out[name] = out.get(name, 0.0) + float(r.get("cost") or 0.0)
            except (TypeError, ValueError):
                pass
        return out
    except Exception as exc:
        logger.error("_spend_by_campaign falhou: %s", exc)
        return {}


def traffic_report(period: str = "30d", mode: str = "lead",
                   date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    """Relatório agregado por canal+campanha. Fail-soft: qualquer erro → relatório vazio."""
    try:
        sb = get_supabase()
        lo, hi = _resolve_window(period, date_from, date_to)
        leads = _fetch_leads(sb, mode, lo, hi)
        lead_ids = [l["id"] for l in leads if l.get("id")]
        if not lead_ids:
            return _empty_report(mode, period)
        conversed = _conversed_ids(sb, lead_ids)
        closers = _closer_ids(sb, lead_ids)
        sales = _sales_by_lead(sb, lead_ids, lo, hi, mode)
        spend = _spend_by_campaign(sb, lo, hi)
        return build_campaign_report(leads, conversed, closers, sales, mode, period,
                                     spend_by_campaign=spend)
    except Exception as exc:
        logger.error("traffic_report(%s,%s) falhou: %s", period, mode, exc, exc_info=True)
        return _empty_report(mode, period)


def _stage_info_map(sb) -> dict[str, dict[str, Any]]:
    stages = sb.table("pipeline_stages").select("id, key, order_index").execute().data or []
    return {s["id"]: {"key": s.get("key"), "order_index": s.get("order_index")} for s in stages}


def campaign_leads(channel: str, campaign: str, period: str = "30d", mode: str = "lead",
                   date_from: str | None = None, date_to: str | None = None) -> list[dict[str, Any]]:
    """Leads de uma campanha (canal+utm_campaign) p/ o drill-down. Fail-soft: [] em erro."""
    try:
        sb = get_supabase()
        lo, hi = _resolve_window(period, date_from, date_to)
        leads = _fetch_leads(sb, mode, lo, hi)
        selected = [
            l for l in leads
            if derive_channel(l) == channel and (_s(l.get("utm_campaign")) or _NO_CAMPAIGN) == campaign
        ]
        if not selected:
            return []
        lead_ids = [l["id"] for l in selected if l.get("id")]
        conversed = _conversed_ids(sb, lead_ids)
        sales = _sales_by_lead(sb, lead_ids, lo, hi, mode)
        stage_info = _stage_info_map(sb)
        deals = []
        for chunk in _chunks(lead_ids):
            deals.extend(sb.table("deals").select("lead_id, stage_id, created_at")
                         .in_("lead_id", chunk).execute().data or [])
        # Estágio mais avançado (maior order_index) por lead — consistente com a lógica do closer.
        best_idx: dict[str, int] = {}
        furthest_stage: dict[str, str] = {}
        for d in deals:
            lid = d.get("lead_id")
            if not lid:
                continue
            info = stage_info.get(d.get("stage_id"))
            if not info:
                continue
            oi = info.get("order_index")
            oi_val = oi if isinstance(oi, int) else -1  # None/ausente => menor prioridade
            if lid not in best_idx or oi_val > best_idx[lid]:
                best_idx[lid] = oi_val
                furthest_stage[lid] = info.get("key")
        out: list[dict[str, Any]] = []
        for l in selected:
            lid = l["id"]
            sale = sales.get(lid)
            out.append({
                "lead_id": lid, "name": l.get("name"), "phone": l.get("phone"),
                "created_at": l.get("created_at"), "utm_source": l.get("utm_source"),
                "utm_medium": l.get("utm_medium"), "utm_campaign": l.get("utm_campaign"),
                "traffic_type": l.get("traffic_type"), "conversou": lid in conversed,
                "stage": furthest_stage.get(lid),
                "comprou": bool(sale), "valor": float(sale["value"]) if sale else 0.0,
                "sold_at": sale.get("last_sold_at") if sale else None,
            })
        out.sort(key=lambda r: (not r["comprou"], r.get("created_at") or ""), reverse=False)
        return out
    except Exception as exc:
        logger.error("campaign_leads(%s,%s) falhou: %s", channel, campaign, exc, exc_info=True)
        return []

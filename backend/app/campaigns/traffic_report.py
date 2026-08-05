"""Relatório de campanhas (/trafego): agrega leads por canal+campanha cruzando com vendas.

Funções puras (derive_channel, build_campaign_report) isoladas do I/O p/ teste.
As funções que tocam o banco (traffic_report, campaign_leads) são fail-soft.
"""
import logging
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
) -> dict[str, Any]:
    """Agrega os leads em linhas (canal, campanha). Puro — recebe coleções já buscadas.

    - conversed_ids / closer_ids: sets de lead_id que conversaram / chegaram ao closer.
    - sales_by_lead: lead_id -> {"count": int, "value": float} (já filtrado por modo).
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
                   "closer": 0, "vendas": 0, "receita": 0.0}
            groups[key] = row
        row["leads"] += 1
        if lead_id in conversed_ids:
            row["conversas"] += 1
        if lead_id in closer_ids:
            row["closer"] += 1
        sale = sales_by_lead.get(lead_id)
        if sale:
            # vendas = nº de leads distintos com >=1 venda (1 por lead comprador).
            row["vendas"] += 1
            row["receita"] += float(sale.get("value", 0.0) or 0.0)

    rows: list[dict[str, Any]] = []
    total = {"leads": 0, "conversas": 0, "closer": 0, "vendas": 0, "receita": 0.0}
    for row in groups.values():
        vendas = row["vendas"]
        row["ticket_medio"] = round(row["receita"] / vendas, 2) if vendas else 0.0
        row["conversao"] = round(row["vendas"] / row["leads"], 4) if row["leads"] else 0.0
        for k in total:
            total[k] += row[k]
        rows.append(row)

    channel_subtotals: dict[str, dict[str, Any]] = {}
    for row in rows:
        sub = channel_subtotals.get(row["channel"])
        if sub is None:
            sub = {"leads": 0, "conversas": 0, "closer": 0, "vendas": 0, "receita": 0.0}
            channel_subtotals[row["channel"]] = sub
        for k in sub:
            sub[k] += row[k]
    for sub in channel_subtotals.values():
        sub["receita"] = round(sub["receita"], 2)

    rows.sort(key=lambda r: (r["channel"], -r["receita"], -r["leads"]))
    total["receita"] = round(total["receita"], 2)
    return {"mode": mode, "period": period, "rows": rows, "total": total,
            "channel_subtotals": channel_subtotals}


_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}
_LEAD_COLS = ("id, name, phone, created_at, gclid, fbclid, ctwa_clid, "
              "utm_source, utm_medium, utm_campaign, traffic_type")


def _period_cutoff(period: str) -> str | None:
    days = _PERIOD_DAYS.get(period)
    if not days:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _chunks(items: list, size: int = 200):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fetch_leads(sb, mode: str, cutoff: str | None) -> list[dict[str, Any]]:
    if mode == "sale":
        q = sb.table("sales").select("lead_id")
        if cutoff:
            q = q.gte("sold_at", cutoff)
        sale_ids = sorted({r["lead_id"] for r in (q.execute().data or []) if r.get("lead_id")})
        leads: list[dict[str, Any]] = []
        for chunk in _chunks(sale_ids):
            data = sb.table("leads").select(_LEAD_COLS).in_("id", chunk).execute().data or []
            leads.extend(data)
        return leads
    q = sb.table("leads").select(_LEAD_COLS)
    if cutoff:
        q = q.gte("created_at", cutoff)
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


def _sales_by_lead(sb, lead_ids: list[str], cutoff: str | None, mode: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(lead_ids):
        q = sb.table("sales").select("lead_id, value, sold_at").in_("lead_id", chunk)
        if mode == "sale" and cutoff:
            q = q.gte("sold_at", cutoff)
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
            "total": {"leads": 0, "conversas": 0, "closer": 0, "vendas": 0, "receita": 0.0}}


def traffic_report(period: str = "30d", mode: str = "lead") -> dict[str, Any]:
    """Relatório agregado por canal+campanha. Fail-soft: qualquer erro → relatório vazio."""
    try:
        sb = get_supabase()
        cutoff = _period_cutoff(period)
        leads = _fetch_leads(sb, mode, cutoff)
        lead_ids = [l["id"] for l in leads if l.get("id")]
        if not lead_ids:
            return _empty_report(mode, period)
        conversed = _conversed_ids(sb, lead_ids)
        closers = _closer_ids(sb, lead_ids)
        sales = _sales_by_lead(sb, lead_ids, cutoff, mode)
        return build_campaign_report(leads, conversed, closers, sales, mode, period)
    except Exception as exc:
        logger.error("traffic_report(%s,%s) falhou: %s", period, mode, exc, exc_info=True)
        return _empty_report(mode, period)


def _stage_info_map(sb) -> dict[str, dict[str, Any]]:
    stages = sb.table("pipeline_stages").select("id, key, order_index").execute().data or []
    return {s["id"]: {"key": s.get("key"), "order_index": s.get("order_index")} for s in stages}


def campaign_leads(channel: str, campaign: str, period: str = "30d", mode: str = "lead") -> list[dict[str, Any]]:
    """Leads de uma campanha (canal+utm_campaign) p/ o drill-down. Fail-soft: [] em erro."""
    try:
        sb = get_supabase()
        cutoff = _period_cutoff(period)
        leads = _fetch_leads(sb, mode, cutoff)
        selected = [
            l for l in leads
            if derive_channel(l) == channel and (_s(l.get("utm_campaign")) or _NO_CAMPAIGN) == campaign
        ]
        if not selected:
            return []
        lead_ids = [l["id"] for l in selected if l.get("id")]
        conversed = _conversed_ids(sb, lead_ids)
        sales = _sales_by_lead(sb, lead_ids, cutoff, mode)
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

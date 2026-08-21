"""Endpoints do Relatório Campanhas (/trafego): agregação por canal+campanha e drill-down.

Read-only e fail-soft; a proteção admin fica na proxy route do Next (frontend/api/traffic/*).
"""
from fastapi import APIRouter

from app.campaigns.traffic_report import traffic_report, campaign_leads, campaign_detail
from app.campaigns.ad_spend_sync import sync_all_ad_spend

router = APIRouter(prefix="/api/traffic", tags=["traffic"])


@router.get("/report")
async def traffic_report_endpoint(period: str = "30d", mode: str = "lead",
                                  date_from: str | None = None, date_to: str | None = None):
    """Relatório agregado por canal+campanha (admin-only na UI)."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return traffic_report(period=period, mode=mode, date_from=date_from, date_to=date_to)


@router.get("/leads")
async def traffic_leads_endpoint(channel: str, campaign: str, period: str = "30d", mode: str = "lead",
                                 date_from: str | None = None, date_to: str | None = None):
    """Leads de uma campanha específica (drill-down)."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return {"leads": campaign_leads(channel=channel, campaign=campaign, period=period, mode=mode,
                                    date_from=date_from, date_to=date_to)}


@router.get("/campaign")
async def traffic_campaign_endpoint(channel: str, campaign: str, period: str = "30d",
                                    mode: str = "lead", date_from: str | None = None,
                                    date_to: str | None = None):
    """Detalhe completo de uma campanha (KPIs + leads + série). Admin-only na UI."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return campaign_detail(channel=channel, campaign=campaign, period=period, mode=mode,
                           date_from=date_from, date_to=date_to)


@router.post("/sync-ads")
async def sync_ads_endpoint():
    """Dispara o sync de investimento (Google + Meta) sob demanda (admin-only na UI).

    `errors` sobe junto: a UI precisa separar "dia sem gasto" de "API caiu" — foi essa
    confusão que deixou o Google Ads dez dias sem sincronizar sem ninguém perceber."""
    res = await sync_all_ad_spend(days=30)
    return {**res, "synced": int(res.get("google", 0) or 0) + int(res.get("meta", 0) or 0)}

"""Endpoints do Relatório Campanhas (/trafego): agregação por canal+campanha e drill-down.

Read-only e fail-soft; a proteção admin fica na proxy route do Next (frontend/api/traffic/*).
"""
from fastapi import APIRouter

from app.campaigns.traffic_report import traffic_report, campaign_leads

router = APIRouter(prefix="/api/traffic", tags=["traffic"])


@router.get("/report")
async def traffic_report_endpoint(period: str = "30d", mode: str = "lead"):
    """Relatório agregado por canal+campanha (admin-only na UI)."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return traffic_report(period=period, mode=mode)


@router.get("/leads")
async def traffic_leads_endpoint(channel: str, campaign: str, period: str = "30d", mode: str = "lead"):
    """Leads de uma campanha específica (drill-down)."""
    mode = mode if mode in ("lead", "sale") else "lead"
    return {"leads": campaign_leads(channel=channel, campaign=campaign, period=period, mode=mode)}

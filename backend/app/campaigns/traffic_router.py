"""Endpoints do Relatório Campanhas (/trafego): agregação por canal+campanha e drill-down.

As leituras são fail-soft e a proteção admin delas fica na proxy route do Next
(frontend/api/traffic/*). As rotas de atribuição manual (/campanhas e
/leads/{id}/campanha) exigem também o JWT de admin aqui (`exigir_admin`).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.auth.jwt import validate_token
from app.campaigns.traffic_attribution import (
    AtribuicaoInvalida, LeadNaoEncontrado, atribuir_campanha, campanhas_com_gasto,
)
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


_bearer = HTTPBearer(auto_error=False)


def exigir_admin(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """E-mail do admin logado, do JWT do Supabase que a proxy do Next repassa.

    As rotas de leitura antigas deste router seguem sem guarda (a proteção é a proxy). As de
    atribuição gravam em `leads`, e o backend é alcançável em api.canastrainteligencia.com —
    sem esta guarda qualquer requisição externa reescreveria a origem de um lead. Função de
    módulo (não `require_role(...)` inline) para o teste poder sobrepor a dependência."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Não autenticado")
    payload = validate_token(f"Bearer {credentials.credentials}")
    if (payload.get("app_metadata") or {}).get("role") != "admin":
        raise HTTPException(status_code=403, detail="Permissão insuficiente")
    return str(payload.get("email") or payload.get("sub") or "admin")


class CampanhaManualBody(BaseModel):
    canal: str | None = None
    campanha_id: str | None = None
    campanha_nome: str | None = None
    remover: bool = False


@router.get("/campanhas")
def traffic_campanhas_endpoint(_admin: str = Depends(exigir_admin)):
    """Campanhas com gasto nos últimos 120 dias (select da atribuição manual)."""
    return {"campanhas": campanhas_com_gasto()}


@router.patch("/leads/{lead_id}/campanha")
def traffic_lead_campanha_endpoint(lead_id: str, body: CampanhaManualBody,
                                   por: str = Depends(exigir_admin)):
    """Atribui (ou remove, com `remover: true`) a campanha de origem de um lead."""
    try:
        uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="lead_id inválido")
    try:
        return atribuir_campanha(lead_id, canal=body.canal, campanha_id=body.campanha_id,
                                 campanha_nome=body.campanha_nome, remover=body.remover, por=por)
    except AtribuicaoInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LeadNaoEncontrado:
        raise HTTPException(status_code=404, detail="lead não encontrado")

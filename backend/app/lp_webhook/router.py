import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.lp_webhook.service import process_landing_page_lead, get_lp_config, save_lp_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["lp_webhook"])


class LandingPagePayload(BaseModel):
    nome: str = ""
    whatsapp: str = ""
    email: str = ""
    timestamp: str = ""
    origem: str = ""
    # Rastreio de tráfego pago (preenchidos pelo JS da landing page a partir da URL).
    fbclid: str = ""
    gclid: str = ""
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""


class LpWebhookSettings(BaseModel):
    channel_id: str = ""
    template_name: str = ""
    language_code: str = "pt_BR"
    delay_minutes: int = 15


@router.post("/webhook/landing-page")
async def landing_page_webhook(payload: LandingPagePayload, request: Request):
    """Recebe lead de landing page. Sem auth — sempre retorna HTTP 200."""
    redis = request.app.state.redis
    data = {
        "nome": payload.nome,
        "whatsapp": payload.whatsapp,
        "email": payload.email,
        "timestamp": payload.timestamp,
        "origem": payload.origem,
        "fbclid": payload.fbclid,
        "gclid": payload.gclid,
        "utm_source": payload.utm_source,
        "utm_medium": payload.utm_medium,
        "utm_campaign": payload.utm_campaign,
    }
    return await process_landing_page_lead(data, redis)


@router.get("/api/lp-webhook/settings")
async def get_settings(request: Request):
    redis = request.app.state.redis
    return await get_lp_config(redis)


@router.put("/api/lp-webhook/settings")
async def update_settings(body: LpWebhookSettings, request: Request):
    redis = request.app.state.redis
    config = {
        "channel_id": body.channel_id,
        "template_name": body.template_name,
        "language_code": body.language_code,
        "delay_minutes": body.delay_minutes,
    }
    await save_lp_config(redis, config)
    return await get_lp_config(redis)

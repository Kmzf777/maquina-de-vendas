import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.outbound.dispatcher import dispatch_to_lead

logger = logging.getLogger(__name__)

router = APIRouter()


class DispatchRequest(BaseModel):
    phone: str
    lead_context: dict = {}


class DispatchResponse(BaseModel):
    status: str
    phone: str
    lead_id: str


@router.post("/api/outbound/dispatch", response_model=DispatchResponse)
async def dispatch_endpoint(body: DispatchRequest):
    """
    Dispara o template de re-engajamento para um lead via Meta Cloud API.
    Chamado manualmente pelo vendedor (futuramente via CRM).
    """
    if not body.phone.startswith("+"):
        raise HTTPException(status_code=400, detail="phone deve estar no formato +5511999999999")

    try:
        result = await dispatch_to_lead(body.phone, body.lead_context)
        return result
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Dispatch failed for {body.phone}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Falha ao enviar mensagem: {e}")

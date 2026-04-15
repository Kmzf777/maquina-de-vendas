from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from app.db.supabase import get_supabase
from app.agent.token_tracker import refresh_pricing

router = APIRouter(prefix="/api/model-pricing", tags=["pricing"])


class PricingUpdate(BaseModel):
    price_per_input_token: float
    price_per_output_token: float


@router.get("")
async def list_pricing():
    sb = get_supabase()
    result = sb.table("model_pricing").select("*").order("model").execute()
    return {"data": result.data}


@router.put("/{model}")
async def update_pricing(model: str, body: PricingUpdate):
    sb = get_supabase()
    result = (
        sb.table("model_pricing")
        .update({
            "price_per_input_token": body.price_per_input_token,
            "price_per_output_token": body.price_per_output_token,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("model", model)
        .execute()
    )
    refresh_pricing()
    return {"data": result.data}

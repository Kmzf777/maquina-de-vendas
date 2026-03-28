from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/campaigns/{campaign_id}/cadence", tags=["cadence"])


class CadenceStepCreate(BaseModel):
    stage: str
    step_order: int
    message_text: str


class CadenceStepUpdate(BaseModel):
    message_text: str


@router.get("")
async def list_cadence_steps(campaign_id: str):
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .select("*")
        .eq("campaign_id", campaign_id)
        .order("stage")
        .order("step_order")
        .execute()
    )
    return {"data": result.data}


@router.post("")
async def create_cadence_step(campaign_id: str, step: CadenceStepCreate):
    sb = get_supabase()
    data = step.model_dump()
    data["campaign_id"] = campaign_id
    result = sb.table("cadence_steps").insert(data).execute()
    return result.data[0]


@router.put("/{step_id}")
async def update_cadence_step(campaign_id: str, step_id: str, step: CadenceStepUpdate):
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .update({"message_text": step.message_text})
        .eq("id", step_id)
        .eq("campaign_id", campaign_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Step nao encontrado")
    return result.data[0]


@router.delete("/{step_id}")
async def delete_cadence_step(campaign_id: str, step_id: str):
    sb = get_supabase()
    sb.table("cadence_steps").delete().eq("id", step_id).eq("campaign_id", campaign_id).execute()
    return {"deleted": True}


@router.get("/status")
async def cadence_status(campaign_id: str):
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("status, leads(stage)")
        .eq("campaign_id", campaign_id)
        .execute()
    )

    # Group by stage and status
    summary: dict[str, dict[str, int]] = {}
    for row in result.data:
        stage = row.get("leads", {}).get("stage", "unknown")
        status = row["status"]
        if stage not in summary:
            summary[stage] = {"active": 0, "responded": 0, "exhausted": 0, "cooled": 0}
        if status in summary[stage]:
            summary[stage][status] += 1

    return {"data": summary}


# Lead-level cadence state (mounted separately)
lead_router = APIRouter(prefix="/api/leads/{lead_id}/cadence", tags=["cadence"])


@lead_router.get("")
async def get_lead_cadence(lead_id: str):
    sb = get_supabase()
    result = (
        sb.table("cadence_state")
        .select("*, cadence_steps(stage, step_order, message_text)")
        .eq("lead_id", lead_id)
        .execute()
    )
    return {"data": result.data[0] if result.data else None}

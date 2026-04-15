from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/cadences", tags=["cadences"])


class CadenceCreate(BaseModel):
    name: str
    description: str | None = None
    target_type: str = "manual"
    target_stage: str | None = None
    stagnation_days: int | None = None
    send_start_hour: int = 7
    send_end_hour: int = 18
    cooldown_hours: int = 48
    max_messages: int = 5


class StepCreate(BaseModel):
    step_order: int
    message_text: str
    delay_days: int = 0


class EnrollRequest(BaseModel):
    lead_id: str
    deal_id: str | None = None


@router.get("")
async def list_cadences():
    sb = get_supabase()
    result = sb.table("cadences").select("*").order("created_at", desc=True).execute()
    return {"data": result.data}


@router.post("")
async def create_cadence(cadence: CadenceCreate):
    sb = get_supabase()
    result = sb.table("cadences").insert(cadence.model_dump(exclude_none=True)).execute()
    return result.data[0]


@router.get("/{cadence_id}")
async def get_cadence(cadence_id: str):
    sb = get_supabase()
    result = sb.table("cadences").select("*").eq("id", cadence_id).single().execute()
    return result.data


@router.patch("/{cadence_id}")
async def update_cadence(cadence_id: str, body: dict):
    sb = get_supabase()
    from datetime import datetime, timezone
    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = sb.table("cadences").update(body).eq("id", cadence_id).select().single().execute()
    return result.data


@router.delete("/{cadence_id}")
async def delete_cadence(cadence_id: str):
    sb = get_supabase()
    active = (
        sb.table("cadence_enrollments")
        .select("id", count="exact")
        .eq("cadence_id", cadence_id)
        .eq("status", "active")
        .execute()
        .count
    )
    if active:
        raise HTTPException(400, f"Cadencia tem {active} leads ativos — pause ou remova antes de excluir")
    sb.table("cadences").delete().eq("id", cadence_id).execute()
    return {"ok": True}


# --- Steps ---

@router.get("/{cadence_id}/steps")
async def list_steps(cadence_id: str):
    sb = get_supabase()
    result = (
        sb.table("cadence_steps")
        .select("*")
        .eq("cadence_id", cadence_id)
        .order("step_order")
        .execute()
    )
    return {"data": result.data}


@router.post("/{cadence_id}/steps")
async def create_step(cadence_id: str, step: StepCreate):
    sb = get_supabase()
    result = sb.table("cadence_steps").insert({
        "cadence_id": cadence_id,
        **step.model_dump(),
    }).execute()
    return result.data[0]


@router.put("/{cadence_id}/steps/{step_id}")
async def update_step(cadence_id: str, step_id: str, body: dict):
    sb = get_supabase()
    result = sb.table("cadence_steps").update(body).eq("id", step_id).select().single().execute()
    return result.data


@router.delete("/{cadence_id}/steps/{step_id}")
async def delete_step(cadence_id: str, step_id: str):
    sb = get_supabase()
    sb.table("cadence_steps").delete().eq("id", step_id).execute()
    return {"ok": True}


# --- Enrollments ---

@router.get("/{cadence_id}/enrollments")
async def list_enrollments(cadence_id: str, status: str | None = None):
    sb = get_supabase()
    query = (
        sb.table("cadence_enrollments")
        .select("*, leads!inner(id, name, phone, company, stage)")
        .eq("cadence_id", cadence_id)
        .order("enrolled_at", desc=True)
    )
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return {"data": result.data}


@router.post("/{cadence_id}/enrollments")
async def enroll_lead(cadence_id: str, req: EnrollRequest):
    from app.cadence.service import create_enrollment, is_enrolled
    from app.cadence.scheduler import calculate_next_send_at
    from datetime import datetime, timezone

    if is_enrolled(cadence_id, req.lead_id):
        raise HTTPException(400, "Lead ja esta nesta cadencia")

    sb = get_supabase()
    cadence = sb.table("cadences").select("*").eq("id", cadence_id).single().execute().data

    first_step = (
        sb.table("cadence_steps")
        .select("delay_days")
        .eq("cadence_id", cadence_id)
        .eq("step_order", 1)
        .execute()
        .data
    )
    delay = first_step[0]["delay_days"] if first_step else 0

    now = datetime.now(timezone.utc)
    next_send = calculate_next_send_at(now, delay, cadence["send_start_hour"], cadence["send_end_hour"])

    enrollment = create_enrollment(
        cadence_id=cadence_id,
        lead_id=req.lead_id,
        deal_id=req.deal_id,
        next_send_at=next_send,
    )
    return enrollment


@router.patch("/{cadence_id}/enrollments/{enroll_id}")
async def update_enrollment(cadence_id: str, enroll_id: str, body: dict):
    from app.cadence.service import pause_enrollment, resume_enrollment
    from app.cadence.scheduler import calculate_next_send_at
    from datetime import datetime, timezone

    action = body.get("action")
    if action == "pause":
        return pause_enrollment(enroll_id)
    elif action == "resume":
        now = datetime.now(timezone.utc)
        next_send = calculate_next_send_at(now, 0, 7, 18)
        return resume_enrollment(enroll_id, next_send_at=next_send)

    sb = get_supabase()
    result = sb.table("cadence_enrollments").update(body).eq("id", enroll_id).select().single().execute()
    return result.data


@router.delete("/{cadence_id}/enrollments/{enroll_id}")
async def remove_enrollment(cadence_id: str, enroll_id: str):
    sb = get_supabase()
    sb.table("cadence_enrollments").delete().eq("id", enroll_id).execute()
    return {"ok": True}

from fastapi import APIRouter, Query
from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.get("")
async def list_leads(
    status: str | None = None,
    stage: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    sb = get_supabase()
    query = sb.table("leads").select("*")

    if status:
        query = query.eq("status", status)
    if stage:
        query = query.eq("stage", stage)

    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"data": result.data, "count": len(result.data)}


@router.get("/{lead_id}")
async def get_lead(lead_id: str):
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).single().execute()
    return result.data


@router.get("/{lead_id}/messages")
async def get_lead_messages(lead_id: str, limit: int = Query(50, le=200)):
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return {"data": result.data}

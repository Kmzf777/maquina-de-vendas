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


@router.delete("/{lead_id}")
async def delete_lead(lead_id: str):
    """Remove lead e todos os dados associados (mensagens, conversas, deals, tags)."""
    sb = get_supabase()
    lead = sb.table("leads").select("id").eq("id", lead_id).limit(1).execute()
    if not lead.data:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Lead not found")
    sb.table("follow_up_jobs").delete().eq("lead_id", lead_id).execute()
    sb.table("campaign_enrollments").delete().eq("lead_id", lead_id).execute()
    sb.table("broadcast_leads").delete().eq("lead_id", lead_id).execute()
    sb.table("deals").delete().eq("lead_id", lead_id).execute()
    sb.table("lead_tags").delete().eq("lead_id", lead_id).execute()
    sb.table("token_usage").delete().eq("lead_id", lead_id).execute()
    sb.table("messages").delete().eq("lead_id", lead_id).execute()
    sb.table("conversations").delete().eq("lead_id", lead_id).execute()
    sb.table("leads").delete().eq("id", lead_id).execute()
    return {"deleted": True, "lead_id": lead_id}

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.campaign.importer import parse_csv

router = APIRouter(prefix="/api/broadcasts", tags=["broadcasts"])


class BroadcastCreate(BaseModel):
    name: str
    channel_id: str | None = None
    template_name: str
    template_preset_id: str | None = None
    template_variables: dict | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8
    cadence_id: str | None = None
    scheduled_at: str | None = None


class AssignLeadsRequest(BaseModel):
    lead_ids: list[str]


@router.get("")
async def list_broadcasts():
    sb = get_supabase()
    result = (
        sb.table("broadcasts")
        .select("*, cadences(id, name)")
        .order("created_at", desc=True)
        .execute()
    )
    return {"data": result.data}


@router.post("")
async def create_broadcast(broadcast: BroadcastCreate):
    sb = get_supabase()
    data = broadcast.model_dump(exclude_none=True)
    if "template_variables" not in data:
        data["template_variables"] = {}
    status = "scheduled" if data.get("scheduled_at") else "draft"
    data["status"] = status
    result = sb.table("broadcasts").insert(data).execute()
    return result.data[0]


@router.get("/{broadcast_id}")
async def get_broadcast(broadcast_id: str):
    sb = get_supabase()
    result = (
        sb.table("broadcasts")
        .select("*, cadences(id, name)")
        .eq("id", broadcast_id)
        .single()
        .execute()
    )
    return result.data


@router.patch("/{broadcast_id}")
async def update_broadcast(broadcast_id: str, body: dict):
    sb = get_supabase()
    from datetime import datetime, timezone
    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = sb.table("broadcasts").update(body).eq("id", broadcast_id).select().single().execute()
    return result.data


@router.delete("/{broadcast_id}")
async def delete_broadcast(broadcast_id: str):
    sb = get_supabase()
    broadcast = sb.table("broadcasts").select("status").eq("id", broadcast_id).single().execute().data
    if broadcast["status"] not in ("draft", "completed"):
        raise HTTPException(400, "Apenas disparos em rascunho ou completos podem ser excluidos")
    sb.table("broadcasts").delete().eq("id", broadcast_id).execute()
    return {"ok": True}


@router.post("/{broadcast_id}/leads")
async def assign_leads(broadcast_id: str, req: AssignLeadsRequest):
    sb = get_supabase()
    assigned = 0
    for lead_id in req.lead_ids:
        try:
            sb.table("broadcast_leads").insert({
                "broadcast_id": broadcast_id,
                "lead_id": lead_id,
            }).execute()
            assigned += 1
        except Exception:
            pass  # Duplicate, skip

    total = sb.table("broadcast_leads").select("id", count="exact").eq("broadcast_id", broadcast_id).execute().count
    sb.table("broadcasts").update({"total_leads": total or 0}).eq("id", broadcast_id).execute()
    return {"assigned": assigned}


@router.post("/{broadcast_id}/import")
async def import_leads(broadcast_id: str, file: UploadFile = File(...)):
    content = await file.read()
    result = parse_csv(content)

    if not result.valid:
        raise HTTPException(400, "Nenhum numero valido encontrado no CSV")

    sb = get_supabase()
    created = 0

    for phone in result.valid:
        try:
            lead_result = sb.table("leads").select("id").eq("phone", phone).execute()
            if lead_result.data:
                lead_id = lead_result.data[0]["id"]
            else:
                insert_result = sb.table("leads").insert({
                    "phone": phone,
                    "status": "imported",
                    "stage": "pending",
                }).execute()
                lead_id = insert_result.data[0]["id"]

            sb.table("broadcast_leads").insert({
                "broadcast_id": broadcast_id,
                "lead_id": lead_id,
            }).execute()
            created += 1
        except Exception:
            pass

    total = sb.table("broadcast_leads").select("id", count="exact").eq("broadcast_id", broadcast_id).execute().count
    sb.table("broadcasts").update({"total_leads": total or 0}).eq("id", broadcast_id).execute()

    return {"imported": created, "invalid": len(result.invalid), "invalid_numbers": result.invalid[:20]}


@router.post("/{broadcast_id}/start")
async def start_broadcast(broadcast_id: str):
    sb = get_supabase()
    broadcast = sb.table("broadcasts").select("*").eq("id", broadcast_id).single().execute().data
    if broadcast["status"] == "running":
        raise HTTPException(400, "Disparo ja esta rodando")

    pending = sb.table("broadcast_leads").select("id", count="exact").eq("broadcast_id", broadcast_id).eq("status", "pending").execute().count
    if not pending:
        raise HTTPException(400, "Nenhum lead pendente para envio")

    sb.table("broadcasts").update({"status": "running"}).eq("id", broadcast_id).execute()
    return {"status": "started", "leads_queued": pending}


@router.post("/{broadcast_id}/pause")
async def pause_broadcast(broadcast_id: str):
    sb = get_supabase()
    sb.table("broadcasts").update({"status": "paused"}).eq("id", broadcast_id).execute()
    return {"status": "paused"}

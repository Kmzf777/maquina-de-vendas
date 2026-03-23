from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.campaign.importer import parse_csv

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    template_name: str
    template_params: dict | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8


@router.get("")
async def list_campaigns():
    sb = get_supabase()
    result = sb.table("campaigns").select("*").order("created_at", desc=True).execute()
    return {"data": result.data}


@router.post("")
async def create_campaign(campaign: CampaignCreate):
    sb = get_supabase()
    result = sb.table("campaigns").insert(campaign.model_dump()).execute()
    return result.data[0]


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str):
    sb = get_supabase()
    result = sb.table("campaigns").select("*").eq("id", campaign_id).single().execute()
    return result.data


@router.post("/{campaign_id}/import")
async def import_leads(campaign_id: str, file: UploadFile = File(...)):
    content = await file.read()
    result = parse_csv(content)

    if not result.valid:
        raise HTTPException(400, "Nenhum numero valido encontrado no CSV")

    sb = get_supabase()

    # Create leads (ignore duplicates)
    created = 0
    for phone in result.valid:
        try:
            sb.table("leads").insert({
                "phone": phone,
                "campaign_id": campaign_id,
                "status": "imported",
                "stage": "pending",
            }).execute()
            created += 1
        except Exception:
            # Duplicate phone, skip
            pass

    # Update campaign total
    sb.table("campaigns").update({"total_leads": created}).eq("id", campaign_id).execute()

    return {
        "imported": created,
        "invalid": len(result.invalid),
        "invalid_numbers": result.invalid[:20],
    }


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: str):
    sb = get_supabase()

    # Get campaign
    campaign = sb.table("campaigns").select("*").eq("id", campaign_id).single().execute().data

    if campaign["status"] == "running":
        raise HTTPException(400, "Campanha ja esta rodando")

    # Get leads for this campaign that haven't been sent
    leads = (
        sb.table("leads")
        .select("id, phone")
        .eq("campaign_id", campaign_id)
        .eq("status", "imported")
        .execute()
        .data
    )

    if not leads:
        raise HTTPException(400, "Nenhum lead pendente para envio")

    # Update campaign status — worker picks up from there
    sb.table("campaigns").update({"status": "running"}).eq("id", campaign_id).execute()

    return {"status": "started", "leads_queued": len(leads)}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: str):
    sb = get_supabase()
    sb.table("campaigns").update({"status": "paused"}).eq("id", campaign_id).execute()
    return {"status": "paused"}

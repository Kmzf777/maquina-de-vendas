import logging

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)
from app.campaign.importer import parse_csv
from app.channels.service import get_channel

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    channel_id: str
    template_name: str
    template_params: dict | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8


@router.get("")
async def list_campaigns():
    sb = get_supabase()
    result = (
        sb.table("campaigns")
        .select("*, channels(id, name, phone)")
        .order("created_at", desc=True)
        .execute()
    )
    return {"data": result.data}


@router.post("")
async def create_campaign(campaign: CampaignCreate):
    # Validate channel is meta_cloud
    channel = get_channel(campaign.channel_id)
    if channel["provider"] != "meta_cloud":
        raise HTTPException(400, "Campanhas so podem ser criadas em channels Meta Cloud API")

    sb = get_supabase()
    result = sb.table("campaigns").insert(campaign.model_dump()).execute()
    return result.data[0]


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str):
    sb = get_supabase()
    result = (
        sb.table("campaigns")
        .select("*, channels(id, name, phone)")
        .eq("id", campaign_id)
        .single()
        .execute()
    )
    return result.data


@router.post("/{campaign_id}/import")
async def import_leads(campaign_id: str, file: UploadFile = File(...)):
    content = await file.read()
    result = parse_csv(content)

    if not result.valid:
        raise HTTPException(400, "Nenhum numero valido encontrado no CSV")

    sb = get_supabase()

    # Get campaign to know the channel_id
    campaign = sb.table("campaigns").select("channel_id").eq("id", campaign_id).single().execute().data
    channel_id = campaign["channel_id"]

    created = 0
    for phone in result.valid:
        try:
            # Create global lead
            lead_result = sb.table("leads").select("id").eq("phone", phone).execute()
            if lead_result.data:
                lead_id = lead_result.data[0]["id"]
            else:
                lead_result = sb.table("leads").insert({"phone": phone}).execute()
                lead_id = lead_result.data[0]["id"]

            # Create conversation for this lead+channel
            sb.table("conversations").insert({
                "lead_id": lead_id,
                "channel_id": channel_id,
                "campaign_id": campaign_id,
                "status": "imported",
                "stage": "pending",
            }).execute()
            created += 1

        except Exception as e:
            logger.warning(f"Failed to import phone {phone}: {e}")

    sb.table("campaigns").update({"total_leads": created}).eq("id", campaign_id).execute()

    return {
        "imported": created,
        "invalid": len(result.invalid),
        "invalid_numbers": result.invalid[:20],
    }


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: str):
    sb = get_supabase()

    campaign = sb.table("campaigns").select("*").eq("id", campaign_id).single().execute().data

    if campaign["status"] == "running":
        raise HTTPException(400, "Campanha ja esta rodando")

    convs = (
        sb.table("conversations")
        .select("id")
        .eq("campaign_id", campaign_id)
        .eq("status", "imported")
        .execute()
        .data
    )

    if not convs:
        raise HTTPException(400, "Nenhum lead pendente para envio")

    sb.table("campaigns").update({"status": "running"}).eq("id", campaign_id).execute()

    return {"status": "started", "leads_queued": len(convs)}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: str):
    sb = get_supabase()
    sb.table("campaigns").update({"status": "paused"}).eq("id", campaign_id).execute()
    return {"status": "paused"}

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta

from app.config import get_settings
from app.db.supabase import get_supabase
from app.campaign.importer import parse_csv
from app.leads.service import (
    get_or_create_lead as _get_or_create_lead,
    lead_has_active_relationship as _lead_has_active_relationship,
)

router = APIRouter(prefix="/api/broadcasts", tags=["broadcasts"])


class BroadcastCreate(BaseModel):
    name: str
    channel_id: str | None = None
    template_name: str
    template_language_code: str = "pt_BR"
    template_preset_id: str | None = None
    template_variables: dict | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8
    cadence_id: str | None = None
    agent_profile_id: str | None = None
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
    settings = get_settings()
    data["env_tag"] = "dev" if settings.is_dev_env else "production"
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

    if "scheduled_at" in body:
        current = (
            sb.table("broadcasts")
            .select("status")
            .eq("id", broadcast_id)
            .single()
            .execute()
            .data
        )
        current_status = current["status"]
        if body["scheduled_at"] is None:
            if current_status == "scheduled":
                body["status"] = "draft"
        else:
            if current_status not in ("draft", "scheduled"):
                raise HTTPException(
                    400,
                    "Apenas disparos em rascunho ou agendados podem ser agendados"
                )
            body["status"] = "scheduled"

    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = sb.table("broadcasts").update(body).eq("id", broadcast_id).execute()
    return result.data[0]


@router.delete("/{broadcast_id}")
async def delete_broadcast(broadcast_id: str):
    sb = get_supabase()
    broadcast = sb.table("broadcasts").select("status").eq("id", broadcast_id).single().execute().data
    if broadcast["status"] not in ("draft", "scheduled", "completed"):
        raise HTTPException(400, "Apenas disparos em rascunho, agendados ou completos podem ser excluidos")
    sb.table("broadcasts").delete().eq("id", broadcast_id).execute()
    return {"ok": True}


@router.post("/{broadcast_id}/leads")
async def assign_leads(broadcast_id: str, req: AssignLeadsRequest):
    sb = get_supabase()
    assigned = 0
    skipped_active = 0
    for lead_id in req.lead_ids:
        # Não enviar disparo frio de prospecção a quem já é cliente / está em tratativa.
        if _lead_has_active_relationship(lead_id):
            skipped_active += 1
            continue
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
    return {"assigned": assigned, "skipped_active": skipped_active}


@router.post("/{broadcast_id}/import")
async def import_leads(broadcast_id: str, file: UploadFile = File(...)):
    content = await file.read()
    result = parse_csv(content)

    if not result.valid:
        raise HTTPException(400, "Nenhum numero valido encontrado no CSV")

    sb = get_supabase()
    created = 0
    skipped_active = 0

    for phone in result.valid:
        try:
            # get_or_create_lead handles 12→13-digit legacy backfill, preventing
            # duplicate leads that would cause the same person to receive two templates.
            lead = _get_or_create_lead(phone)
            # Não enviar disparo frio de prospecção a quem já é cliente / está em tratativa.
            if _lead_has_active_relationship(lead["id"]):
                skipped_active += 1
                continue
            sb.table("broadcast_leads").insert({
                "broadcast_id": broadcast_id,
                "lead_id": lead["id"],
            }).execute()
            created += 1
        except Exception:
            pass

    total = sb.table("broadcast_leads").select("id", count="exact").eq("broadcast_id", broadcast_id).execute().count
    sb.table("broadcasts").update({"total_leads": total or 0}).eq("id", broadcast_id).execute()

    return {
        "imported": created,
        "invalid": len(result.invalid),
        "invalid_numbers": result.invalid[:20],
        "skipped_active": skipped_active,
    }


@router.post("/{broadcast_id}/start")
async def start_broadcast(broadcast_id: str):
    sb = get_supabase()

    billing_alert = (
        sb.table("system_alerts")
        .select("title")
        .eq("type", "billing_payment_issue")
        .eq("resolved", False)
        .limit(1)
        .execute()
    )
    if billing_alert.data:
        title = billing_alert.data[0].get("title", "Pagamento pendente na conta WhatsApp")
        raise HTTPException(400, f"Disparo bloqueado: {title}. Resolva o pagamento no Business Manager da Meta antes de retomar.")

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

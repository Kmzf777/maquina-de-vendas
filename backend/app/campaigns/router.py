from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone

from app.campaigns.service import (
    list_campaigns, get_campaign, create_campaign, update_campaign, delete_campaign,
    list_nodes, create_node, update_node, delete_node,
    list_enrollments, create_enrollment, update_enrollment, cancel_enrollment, pause_enrollment,
    is_already_enrolled,
)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    description: str | None = None


class NodeCreate(BaseModel):
    type: str
    config: dict = {}
    position_x: int = 0
    position_y: int = 0


class EnrollRequest(BaseModel):
    lead_id: str
    deal_id: str | None = None


# ─── Campaign CRUD ────────────────────────────────────────────────────────────

@router.get("")
async def api_list_campaigns():
    return {"data": list_campaigns()}


@router.post("")
async def api_create_campaign(body: CampaignCreate):
    return create_campaign(body.name, body.description)


@router.get("/{campaign_id}")
async def api_get_campaign(campaign_id: str):
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign não encontrada")
    nodes = list_nodes(campaign_id)
    return {**camp, "nodes": nodes}


@router.patch("/{campaign_id}")
async def api_update_campaign(campaign_id: str, body: dict):
    return update_campaign(campaign_id, **body)


@router.delete("/{campaign_id}")
async def api_delete_campaign(campaign_id: str):
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign não encontrada")
    if camp["status"] not in ("draft", "archived"):
        raise HTTPException(400, "Apenas campaigns em rascunho ou arquivadas podem ser excluídas")
    delete_campaign(campaign_id)
    return {"ok": True}


@router.post("/{campaign_id}/activate")
async def api_activate_campaign(campaign_id: str):
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign não encontrada")
    nodes = list_nodes(campaign_id)
    trigger = next((n for n in nodes if n["type"] == "trigger"), None)
    if not trigger:
        raise HTTPException(400, "Campaign precisa de pelo menos um nó de gatilho")
    if not trigger.get("next_node_id"):
        raise HTTPException(400, "Nó de gatilho precisa estar conectado a um próximo nó")
    update_campaign(campaign_id, status="active")
    return {"status": "active"}


@router.post("/{campaign_id}/pause")
async def api_pause_campaign(campaign_id: str):
    update_campaign(campaign_id, status="paused")
    return {"status": "paused"}


# ─── Nodes ────────────────────────────────────────────────────────────────────

@router.post("/{campaign_id}/nodes")
async def api_create_node(campaign_id: str, body: NodeCreate):
    return create_node(campaign_id, body.type, body.config, body.position_x, body.position_y)


@router.patch("/{campaign_id}/nodes/{node_id}")
async def api_update_node(campaign_id: str, node_id: str, body: dict):
    return update_node(node_id, **body)


@router.delete("/{campaign_id}/nodes/{node_id}")
async def api_delete_node(campaign_id: str, node_id: str):
    delete_node(node_id)
    return {"ok": True}


# ─── Enrollments ──────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/enrollments")
async def api_list_enrollments(campaign_id: str, status: str | None = None):
    return {"data": list_enrollments(campaign_id, status)}


@router.post("/{campaign_id}/enrollments")
async def api_enroll_lead(campaign_id: str, body: EnrollRequest):
    if is_already_enrolled(campaign_id, body.lead_id):
        raise HTTPException(400, "Lead já está nesta campanha")
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign não encontrada")
    nodes = list_nodes(campaign_id)
    trigger = next((n for n in nodes if n["type"] == "trigger"), None)
    if not trigger or not trigger.get("next_node_id"):
        raise HTTPException(400, "Campaign sem fluxo configurado")
    enrollment = create_enrollment(
        campaign_id=campaign_id,
        lead_id=body.lead_id,
        deal_id=body.deal_id,
        current_node_id=trigger["next_node_id"],
        next_execute_at=datetime.now(timezone.utc),
    )
    return enrollment


@router.patch("/{campaign_id}/enrollments/{enrollment_id}")
async def api_update_enrollment(campaign_id: str, enrollment_id: str, body: dict):
    action = body.get("action")
    if action == "pause":
        pause_enrollment(enrollment_id)
        return {"status": "paused"}
    if action == "cancel":
        cancel_enrollment(enrollment_id)
        return {"status": "cancelled"}
    return update_enrollment(enrollment_id, **{k: v for k, v in body.items() if k != "action"})

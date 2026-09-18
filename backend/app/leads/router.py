import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads", tags=["leads"])


class WonSalePayload(BaseModel):
    value: float | None = None
    currency: str = "BRL"
    deal_id: str | None = None


class BlockPayload(BaseModel):
    """Corpo OPCIONAL de /block, /unblock e /optout — quem bloqueou e por quê.

    Tudo opcional de propósito: o proxy Next (`api/leads/[id]/optout/route.ts`) faz o POST
    sem corpo nenhum, e uma auditoria incompleta não pode impedir o bloqueio de acontecer.
    """

    by: str | None = None
    reason: str | None = None


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


@router.get("/{lead_id}/followups")
async def get_lead_followups(lead_id: str):
    """Read-only: cadence/follow-up jobs of a lead for the visibility timeline.

    Flattens metadata.objetivo and omits the heavy objective_prompt. Ordered by fire_at asc.
    """
    sb = get_supabase()
    result = (
        sb.table("follow_up_jobs")
        .select("sequence, job_type, status, fire_at, sent_at, cancel_reason, metadata")
        .eq("lead_id", lead_id)
        .order("fire_at", desc=False)
        .execute()
    )
    rows = []
    for j in (result.data or []):
        md = j.get("metadata") or {}
        rows.append({
            "sequence": j.get("sequence"),
            "job_type": j.get("job_type"),
            "status": j.get("status"),
            "fire_at": j.get("fire_at"),
            "sent_at": j.get("sent_at"),
            "cancel_reason": j.get("cancel_reason"),
            "objetivo": md.get("objetivo"),
        })
    return {"data": rows}


@router.post("/{lead_id}/block")
async def block_lead_endpoint(lead_id: str, body: BlockPayload | None = None):
    """Bloqueia o lead: hard opt-out, cards na Blacklist, conversa fora de /conversas.

    Toda a regra vive em `leads.service.block_lead` — a rota só traduz o `ValueError`
    de lead inexistente em 404 e devolve os contadores que a UI usa na confirmação.
    """
    from app.leads.service import block_lead

    try:
        result = block_lead(lead_id, by=(body.by if body else None),
                            reason=(body.reason if body else None))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", **result}


@router.post("/{lead_id}/unblock")
async def unblock_lead_endpoint(lead_id: str, body: BlockPayload | None = None):
    """Desbloqueia o lead. `deals_pendentes > 0` = cards que a UI precisa mandar mover.

    A prova do bloqueio (`opt_out_at`/`opt_out_channel`/evidência) NÃO é apagada — ver
    `leads.service.unblock_lead`.
    """
    from app.leads.service import unblock_lead

    try:
        result = unblock_lead(lead_id, by=(body.by if body else None))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", **result}


@router.get("/{lead_id}/blocked")
async def is_lead_blocked(lead_id: str):
    """Estado de bloqueio pelo critério canônico (`opt_out` OU deal na Blacklist)."""
    from app.leads.service import is_lead_blacklisted

    return {"blocked": is_lead_blacklisted(lead_id)}


@router.post("/{lead_id}/optout")
async def optout_lead(lead_id: str, body: BlockPayload | None = None):
    """Alias histórico de /block. Mantido porque o frontend e scripts ainda chamam esta URL.

    Até 18/09/2026 esta rota fazia `ai_enabled=False` + side effects e NUNCA gravava
    `opt_out=True`: o "parar mensagens" do operador ficava apoiado só no braço "tem deal
    na Blacklist" de `is_lead_blacklisted` e evaporava assim que alguém arrastasse o card
    no Kanban. Delegar para `block_lead` é o conserto — a rota continua respondendo
    `{"status": "ok"}` (contrato que chat-view.tsx já consome) com os contadores novos por
    cima.
    """
    from app.leads.service import block_lead

    try:
        result = block_lead(lead_id, by=(body.by if body else None),
                            reason=(body.reason if body else None) or "optout_manual")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", **result}


@router.post("/{lead_id}/won")
async def mark_lead_won(lead_id: str, body: WonSalePayload, background_tasks: BackgroundTasks):
    """Marca a venda como Ganha (Kanban → coluna 'Ganho') e dispara a conversão outbound.

    Atualiza o CRM de forma síncrona e agenda o disparo Meta CAPI / Google em BackgroundTask
    — assim a latência das APIs de anúncio não bloqueia a resposta ao frontend.
    """
    from app.leads.service import get_lead
    from app.campaigns.sales import mark_deal_won
    from app.campaigns.conversions import fire_stage_conversion

    if not get_lead(lead_id):
        raise HTTPException(status_code=404, detail="Lead not found")

    result = mark_deal_won(lead_id, value=body.value, currency=body.currency, deal_id=body.deal_id)

    # Ciclo de reposição: deal ganho → garante nova oportunidade aberta (fail-soft).
    # deal_id vem do próprio resultado de mark_deal_won: o destino do card de
    # reposição depende do funil de ORIGEM deste deal (não do lead em geral).
    if result.get("deals_updated"):
        from app.leads.reposicao import ensure_reposicao_deal
        ensure_reposicao_deal(lead_id, deal_id=result.get("deal_id"))

    # Disparo da conversão fora do caminho crítico (latência da Meta/Google).
    if result.get("deal_id"):
        background_tasks.add_task(
            fire_stage_conversion, result["lead"], result["deal_id"], "purchase",
            body.value, body.currency,
        )

    logger.info("mark_lead_won: lead %s marcado como Ganho (%d deal(s))", lead_id, result["deals_updated"])
    return {"status": "ok", "deals_updated": result["deals_updated"]}


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

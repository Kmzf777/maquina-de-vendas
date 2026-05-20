# Cadências Flow Builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **FRONTEND AGENTS:** You MUST invoke the `frontend-design` skill before writing any UI component, page, or style. No exceptions.

**Goal:** Substituir o sistema de Cadências inativo por um flow builder visual de campanhas com gatilhos automáticos baseados em dados do CRM.

**Architecture:** Novas tabelas Supabase (`campaigns`, `campaign_nodes`, `campaign_enrollments`) completamente separadas das tabelas antigas de cadência. Backend FastAPI com módulo `campaigns/` contendo routers e worker. Frontend com flow builder canvas em `/campanhas/cadencias/[id]`, seguindo exatamente o mesmo padrão visual aprovado no brainstorming (canvas `#f5f2ed`, nós brancos com stripe colorida, fonte `Outfit` + `JetBrains Mono`). Next.js API routes acessam Supabase diretamente (mesmo padrão dos broadcasts).

**Tech Stack:** Python/FastAPI (backend), Next.js App Router + Tailwind (frontend), Supabase (banco), `getServiceSupabase()` nas API routes do Next.js.

**Spec:** `docs/superpowers/specs/2026-05-20-cadencias-flow-builder-design.md`

---

## Mapa de Arquivos

### Criar
| Arquivo | Responsabilidade |
|---|---|
| `backend/app/campaigns/__init__.py` | módulo campaigns |
| `backend/app/campaigns/service.py` | queries Supabase para campaigns/nodes/enrollments |
| `backend/app/campaigns/router.py` | FastAPI routes CRUD |
| `backend/app/campaigns/worker.py` | trigger checker + enrollment executor |
| `frontend/src/app/api/campaigns/route.ts` | GET list / POST create |
| `frontend/src/app/api/campaigns/[id]/route.ts` | GET / PATCH / DELETE |
| `frontend/src/app/api/campaigns/[id]/activate/route.ts` | POST ativar |
| `frontend/src/app/api/campaigns/[id]/pause/route.ts` | POST pausar |
| `frontend/src/app/api/campaigns/[id]/nodes/route.ts` | POST add node |
| `frontend/src/app/api/campaigns/[id]/nodes/[nodeId]/route.ts` | PATCH / DELETE node |
| `frontend/src/app/api/campaigns/[id]/enrollments/route.ts` | GET / POST enrollments |
| `frontend/src/app/(authenticated)/campanhas/cadencias/[id]/page.tsx` | flow builder page |
| `frontend/src/components/campaigns/cadence-flow-builder.tsx` | canvas + paleta + inspector (componente único) |
| `frontend/src/components/campaigns/create-campaign-modal.tsx` | modal de criação |
| `frontend/src/hooks/use-realtime-campaigns.ts` | hook realtime para lista |

### Modificar
| Arquivo | O que muda |
|---|---|
| `backend/app/main.py` | importar e registrar campaigns router + adicionar workers ao loop |
| `backend/app/broadcast/worker.py` | ao completar envio, enrolar em `campaign_id` se configurado |
| `backend/app/webhook/router.py` | ao receber mensagem, pausar/cancelar enrollment se `on_reply != continue` |
| `frontend/src/lib/types.ts` | adicionar `Campaign`, `CampaignNode`, `CampaignEnrollment` |
| `frontend/src/app/(authenticated)/campanhas/page.tsx` | botão "+ Cadencia" abre `create-campaign-modal`, lista usa nova hook |
| `frontend/src/components/campaigns/cadence-list.tsx` | usar Campaign ao invés de Cadence, link para `/campanhas/cadencias/[id]` |
| `frontend/src/components/campaigns/cadence-card.tsx` | usar campos de Campaign |
| `frontend/src/components/campaigns/campaigns-dashboard.tsx` | stats de campaigns |
| `frontend/src/components/conversas/tabs/crm-campanhas-tab.tsx` | mostrar campaign_enrollments |

---

## FASE 0 — Migração Supabase (pré-requisito manual)

**Rodar no Supabase Dashboard → SQL Editor antes de qualquer outra task.**

- [ ] **Executar a seguinte migration SQL no Supabase Dashboard:**

```sql
-- campaigns
CREATE TABLE IF NOT EXISTS campaigns (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  description text,
  status      text NOT NULL DEFAULT 'draft',
  env_tag     text NOT NULL,
  start_date  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- campaign_nodes
CREATE TABLE IF NOT EXISTS campaign_nodes (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id     uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  type            text NOT NULL,
  config          jsonb NOT NULL DEFAULT '{}',
  position_x      int NOT NULL DEFAULT 0,
  position_y      int NOT NULL DEFAULT 0,
  next_node_id    uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL,
  yes_node_id     uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL,
  no_node_id      uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- campaign_enrollments
CREATE TABLE IF NOT EXISTS campaign_enrollments (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id       uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  lead_id           uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  deal_id           uuid REFERENCES deals(id) ON DELETE SET NULL,
  status            text NOT NULL DEFAULT 'active',
  current_node_id   uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL,
  next_execute_at   timestamptz,
  enrolled_at       timestamptz NOT NULL DEFAULT now(),
  completed_at      timestamptz,
  paused_at         timestamptz,
  env_tag           text NOT NULL,
  UNIQUE (campaign_id, lead_id)
);

-- Índices de performance
CREATE INDEX IF NOT EXISTS idx_campaign_nodes_campaign ON campaign_nodes(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_enrollments_active ON campaign_enrollments(status, next_execute_at) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_campaign_enrollments_lead ON campaign_enrollments(lead_id);
```

- [ ] **Verificar no Supabase Table Editor que as 3 tabelas existem com as colunas corretas.**

---

## FASE 1 — Backend

### Task 1: Módulo campaigns — service.py

**Arquivos:**
- Criar: `backend/app/campaigns/__init__.py`
- Criar: `backend/app/campaigns/service.py`

- [ ] **Criar `backend/app/campaigns/__init__.py` vazio:**

```python
```

- [ ] **Criar `backend/app/campaigns/service.py` com todas as queries:**

```python
from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase
from app.config import get_settings

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"


# ─── Campaigns ────────────────────────────────────────────────────────────────

def list_campaigns() -> list[dict[str, Any]]:
    sb = get_supabase()
    return sb.table("campaigns").select("*").eq("env_tag", _ENV_TAG).order("created_at", desc=True).execute().data


def get_campaign(campaign_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("campaigns").select("*").eq("id", campaign_id).single().execute()
    return result.data


def create_campaign(name: str, description: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaigns").insert({
        "name": name,
        "description": description,
        "status": "draft",
        "env_tag": _ENV_TAG,
    }).execute().data[0]


def update_campaign(campaign_id: str, **kwargs) -> dict[str, Any]:
    sb = get_supabase()
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    return sb.table("campaigns").update(kwargs).eq("id", campaign_id).execute().data[0]


def delete_campaign(campaign_id: str) -> None:
    sb = get_supabase()
    sb.table("campaigns").delete().eq("id", campaign_id).execute()


# ─── Nodes ────────────────────────────────────────────────────────────────────

def list_nodes(campaign_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    return sb.table("campaign_nodes").select("*").eq("campaign_id", campaign_id).execute().data


def create_node(campaign_id: str, type: str, config: dict, position_x: int = 0, position_y: int = 0) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaign_nodes").insert({
        "campaign_id": campaign_id,
        "type": type,
        "config": config,
        "position_x": position_x,
        "position_y": position_y,
    }).execute().data[0]


def update_node(node_id: str, **kwargs) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaign_nodes").update(kwargs).eq("id", node_id).execute().data[0]


def delete_node(node_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_nodes").delete().eq("id", node_id).execute()


# ─── Enrollments ──────────────────────────────────────────────────────────────

def list_enrollments(campaign_id: str, status: str | None = None) -> list[dict[str, Any]]:
    sb = get_supabase()
    q = sb.table("campaign_enrollments").select("*, leads!inner(id, name, phone, stage)").eq("campaign_id", campaign_id)
    if status:
        q = q.eq("status", status)
    return q.order("enrolled_at", desc=True).execute().data


def create_enrollment(campaign_id: str, lead_id: str, current_node_id: str, next_execute_at: datetime, deal_id: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaign_enrollments").insert({
        "campaign_id": campaign_id,
        "lead_id": lead_id,
        "deal_id": deal_id,
        "current_node_id": current_node_id,
        "next_execute_at": next_execute_at.isoformat(),
        "env_tag": _ENV_TAG,
    }).execute().data[0]


def get_due_enrollments(now: datetime, limit: int = 20) -> list[dict[str, Any]]:
    sb = get_supabase()
    return (
        sb.table("campaign_enrollments")
        .select("*, leads!inner(id, phone, name, company, stage, ai_enabled), campaign_nodes!campaign_enrollments_current_node_id_fkey(*)")
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .lte("next_execute_at", now.isoformat())
        .limit(limit)
        .execute()
        .data
    )


def update_enrollment(enrollment_id: str, **kwargs) -> dict[str, Any]:
    sb = get_supabase()
    return sb.table("campaign_enrollments").update(kwargs).eq("id", enrollment_id).execute().data[0]


def complete_enrollment(enrollment_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update({
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", enrollment_id).execute()


def cancel_enrollment(enrollment_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update({"status": "cancelled"}).eq("id", enrollment_id).execute()


def pause_enrollment(enrollment_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update({
        "status": "paused",
        "paused_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", enrollment_id).execute()


def get_active_enrollment_for_lead(lead_id: str) -> dict[str, Any] | None:
    """Used by webhook to check if incoming reply should affect a campaign."""
    sb = get_supabase()
    result = (
        sb.table("campaign_enrollments")
        .select("*, campaign_nodes!campaign_enrollments_current_node_id_fkey(type, config)")
        .eq("lead_id", lead_id)
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_campaigns_with_trigger_type(trigger_type: str) -> list[dict[str, Any]]:
    """Returns active campaigns that have a trigger node of the given type."""
    sb = get_supabase()
    campaigns = sb.table("campaigns").select("id").eq("status", "active").eq("env_tag", _ENV_TAG).execute().data
    if not campaigns:
        return []
    campaign_ids = [c["id"] for c in campaigns]
    nodes = (
        sb.table("campaign_nodes")
        .select("*, campaigns!inner(id, status)")
        .eq("type", "trigger")
        .in_("campaign_id", campaign_ids)
        .execute()
        .data
    )
    return [n for n in nodes if n["config"].get("trigger_type") == trigger_type]


def is_already_enrolled(campaign_id: str, lead_id: str) -> bool:
    sb = get_supabase()
    result = (
        sb.table("campaign_enrollments")
        .select("id")
        .eq("campaign_id", campaign_id)
        .eq("lead_id", lead_id)
        .in_("status", ["active", "paused"])
        .limit(1)
        .execute()
    )
    return len(result.data) > 0
```

- [ ] **Commit:**
```bash
git add backend/app/campaigns/
git commit -m "feat(campaigns): service.py com queries Supabase"
```

---

### Task 2: Módulo campaigns — router.py

**Arquivos:**
- Criar: `backend/app/campaigns/router.py`

- [ ] **Criar `backend/app/campaigns/router.py`:**

```python
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
```

- [ ] **Commit:**
```bash
git add backend/app/campaigns/router.py
git commit -m "feat(campaigns): router FastAPI CRUD"
```

---

### Task 3: Campaign Worker

**Arquivos:**
- Criar: `backend/app/campaigns/worker.py`

- [ ] **Criar `backend/app/campaigns/worker.py`:**

```python
import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta

from app.campaigns.service import (
    get_campaigns_with_trigger_type,
    is_already_enrolled,
    create_enrollment,
    get_due_enrollments,
    update_enrollment,
    complete_enrollment,
    cancel_enrollment,
)
from app.db.supabase import get_supabase
from app.config import get_settings

logger = logging.getLogger(__name__)
_ENV_TAG = "dev" if get_settings().is_dev_env else "production"

BRT_OFFSET = timedelta(hours=-3)


def _is_within_window(now_utc: datetime, start_hour: int = 7, end_hour: int = 18) -> bool:
    brt = now_utc + BRT_OFFSET
    return start_hour <= brt.hour < end_hour


def _next_window_start(now_utc: datetime, start_hour: int = 7) -> datetime:
    brt = now_utc + BRT_OFFSET
    if brt.hour < start_hour:
        target = brt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    else:
        target = (brt + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return target - BRT_OFFSET


async def check_campaign_triggers(now: datetime | None = None) -> None:
    """Detect leads that satisfy trigger conditions and auto-enroll them."""
    now = now or datetime.now(timezone.utc)
    sb = get_supabase()

    # ── no_message triggers ────────────────────────────────────────────────────
    for trigger_node in get_campaigns_with_trigger_type("no_message"):
        cfg = trigger_node["config"]
        days = cfg.get("days", 30)
        stage_filter = cfg.get("stage_filter")
        cutoff = (now - timedelta(days=days)).isoformat()

        query = sb.table("leads").select("id, phone").eq("env_tag", _ENV_TAG).lte("last_msg_at", cutoff)
        if stage_filter:
            query = query.eq("stage", stage_filter)
        leads = query.limit(20).execute().data

        for lead in leads:
            campaign_id = trigger_node["campaign_id"]
            if is_already_enrolled(campaign_id, lead["id"]):
                continue
            if not trigger_node.get("next_node_id"):
                continue
            try:
                create_enrollment(
                    campaign_id=campaign_id,
                    lead_id=lead["id"],
                    current_node_id=trigger_node["next_node_id"],
                    next_execute_at=now,
                )
                logger.info("[CAMPAIGNS] Enrolled lead %s via no_message trigger", lead["phone"])
            except Exception as e:
                logger.warning("[CAMPAIGNS] Failed to enroll %s: %s", lead["id"], e)

    # ── stage_stagnation triggers ──────────────────────────────────────────────
    for trigger_node in get_campaigns_with_trigger_type("stage_stagnation"):
        cfg = trigger_node["config"]
        days = cfg.get("days", 7)
        stage = cfg.get("stage_filter")
        if not stage:
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        leads = sb.table("leads").select("id, phone").eq("stage", stage).lte("entered_stage_at", cutoff).limit(20).execute().data
        for lead in leads:
            campaign_id = trigger_node["campaign_id"]
            if is_already_enrolled(campaign_id, lead["id"]) or not trigger_node.get("next_node_id"):
                continue
            try:
                create_enrollment(campaign_id=campaign_id, lead_id=lead["id"], current_node_id=trigger_node["next_node_id"], next_execute_at=now)
                logger.info("[CAMPAIGNS] Enrolled lead %s via stage_stagnation trigger", lead["phone"])
            except Exception as e:
                logger.warning("[CAMPAIGNS] Failed to enroll %s: %s", lead["id"], e)

    # ── stage_enter triggers ───────────────────────────────────────────────────
    for trigger_node in get_campaigns_with_trigger_type("stage_enter"):
        cfg = trigger_node["config"]
        stage = cfg.get("stage_filter")
        if not stage:
            continue
        leads = sb.table("leads").select("id, phone").eq("stage", stage).limit(20).execute().data
        for lead in leads:
            campaign_id = trigger_node["campaign_id"]
            if is_already_enrolled(campaign_id, lead["id"]) or not trigger_node.get("next_node_id"):
                continue
            try:
                create_enrollment(campaign_id=campaign_id, lead_id=lead["id"], current_node_id=trigger_node["next_node_id"], next_execute_at=now)
            except Exception as e:
                logger.warning("[CAMPAIGNS] Failed to enroll %s: %s", lead["id"], e)


async def process_campaign_enrollments(now: datetime | None = None) -> None:
    """Execute the current node for each due enrollment."""
    now = now or datetime.now(timezone.utc)
    enrollments = get_due_enrollments(now, limit=20)

    for enrollment in enrollments:
        node = enrollment.get("campaign_nodes")
        lead = enrollment["leads"]
        if not node:
            complete_enrollment(enrollment["id"])
            continue

        node_type = node["type"]
        cfg = node.get("config", {})

        try:
            if node_type == "send":
                await _execute_send_node(enrollment, node, lead, now)

            elif node_type == "wait":
                days = cfg.get("days", 1)
                start_hour = cfg.get("send_start_hour", 7)
                target = now + timedelta(days=days)
                if not _is_within_window(target, start_hour, cfg.get("send_end_hour", 18)):
                    target = _next_window_start(target, start_hour)
                update_enrollment(enrollment["id"], next_execute_at=target.isoformat())
                logger.info("[CAMPAIGNS] Enrollment %s waiting %d days", enrollment["id"], days)
                continue

            elif node_type == "condition":
                _execute_condition_node(enrollment, node, lead, now)
                continue

            elif node_type == "action":
                _execute_action_node(enrollment, node, lead)

            elif node_type == "end":
                _execute_end_node(enrollment, node, lead)
                continue

            # Advance to next_node_id
            next_id = node.get("next_node_id")
            if next_id:
                update_enrollment(enrollment["id"], current_node_id=next_id, next_execute_at=now.isoformat())
            else:
                complete_enrollment(enrollment["id"])

        except Exception as e:
            logger.error("[CAMPAIGNS] Error processing enrollment %s node %s: %s", enrollment["id"], node.get("id"), e, exc_info=True)

        await asyncio.sleep(random.randint(2, 5))


async def _execute_send_node(enrollment: dict, node: dict, lead: dict, now: datetime) -> None:
    from app.whatsapp.registry import get_provider
    from app.channels.service import get_channel_for_lead
    from app.broadcast.worker import (
        _build_template_components, _render_template_body, _broadcast_ai_enabled,
    )
    from app.conversations.service import get_or_create_conversation, update_conversation, save_message
    from app.leads.service import update_lead

    cfg = node["config"]
    template_name = cfg["template_name"]
    template_variables = cfg.get("template_variables", {})
    channel_id = cfg.get("channel_id")

    channel = None
    if channel_id:
        from app.channels.service import get_channel_by_id
        channel = get_channel_by_id(channel_id)
    if not channel:
        channel = get_channel_for_lead(enrollment["lead_id"])
    if not channel:
        logger.warning("[CAMPAIGNS] No channel for lead %s, skipping send", lead["phone"])
        return

    provider = get_provider(channel)
    components = _build_template_components(template_variables, lead)
    send_resp = await provider.send_template(
        to=lead["phone"],
        template_name=template_name,
        components=components,
        language_code=cfg.get("template_language", "pt_BR"),
    )

    wamid = None
    try:
        wamid = (send_resp.get("messages") or [{}])[0].get("id")
    except Exception:
        pass

    # Persist conversation + message
    try:
        conv = get_or_create_conversation(enrollment["lead_id"], channel["id"])
        update_conversation(conv["id"], status="template_sent")
        rendered = await _render_template_body(template_name, template_variables, lead, channel)
        save_message(conv["id"], enrollment["lead_id"], "assistant", rendered, sent_by="campaign", wamid=wamid)
    except Exception as e:
        logger.warning("[CAMPAIGNS] Could not persist conversation for %s: %s", lead["phone"], e)

    # Update ai_enabled
    try:
        agent_profile_id = cfg.get("agent_profile_id")
        fake_broadcast = {"agent_profile_id": agent_profile_id}
        ai_enabled = _broadcast_ai_enabled(fake_broadcast, channel)
        update_lead(enrollment["lead_id"], ai_enabled=ai_enabled)
    except Exception as e:
        logger.warning("[CAMPAIGNS] Could not update ai_enabled for %s: %s", lead["phone"], e)

    logger.info("[CAMPAIGNS] Sent template '%s' to %s", template_name, lead["phone"])


def _execute_condition_node(enrollment: dict, node: dict, lead: dict, now: datetime) -> None:
    from app.db.supabase import get_supabase
    cfg = node["config"]
    cond = cfg.get("condition_type", "replied_recently")
    result = False

    if cond == "replied_recently":
        days = cfg.get("days", 5)
        cutoff = (now - timedelta(days=days)).isoformat()
        sb = get_supabase()
        msgs = sb.table("messages").select("id").eq("lead_id", enrollment["lead_id"]).eq("role", "user").gte("created_at", cutoff).limit(1).execute()
        result = len(msgs.data) > 0

    elif cond == "in_stage":
        result = lead.get("stage") == cfg.get("stage")

    elif cond == "has_deal":
        sb = get_supabase()
        deals = sb.table("deals").select("id").eq("lead_id", enrollment["lead_id"]).limit(1).execute()
        result = len(deals.data) > 0

    next_node_id = node["yes_node_id"] if result else node["no_node_id"]
    if next_node_id:
        update_enrollment(enrollment["id"], current_node_id=next_node_id, next_execute_at=now.isoformat())
    else:
        complete_enrollment(enrollment["id"])

    logger.info("[CAMPAIGNS] Condition '%s' for %s → %s", cond, lead["phone"], "YES" if result else "NO")


def _execute_action_node(enrollment: dict, node: dict, lead: dict) -> None:
    from app.db.supabase import get_supabase
    cfg = node["config"]
    action_type = cfg.get("action_type")
    sb = get_supabase()

    if action_type == "move_stage":
        stage_id = cfg.get("stage_id")
        if stage_id:
            stage_row = sb.table("pipeline_stages").select("pipeline_id, label").eq("id", stage_id).limit(1).execute().data
            if stage_row:
                sb.table("deals").update({"stage_id": stage_id}).eq("lead_id", enrollment["lead_id"]).execute()

    elif action_type == "activate_agent":
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], ai_enabled=True, human_control=False)

    elif action_type == "deactivate_agent":
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], ai_enabled=False)

    logger.info("[CAMPAIGNS] Action '%s' executed for lead %s", action_type, lead["phone"])


def _execute_end_node(enrollment: dict, node: dict, lead: dict) -> None:
    cfg = node.get("config", {})
    for action in cfg.get("final_actions", []):
        fake_node = {"config": action, "type": "action"}
        _execute_action_node(enrollment, fake_node, lead)
    complete_enrollment(enrollment["id"])
    logger.info("[CAMPAIGNS] Enrollment %s completed (end node)", enrollment["id"])


def handle_campaign_reply(lead_id: str) -> None:
    """Called by webhook when a lead sends a message. Pauses/cancels enrollment per config."""
    from app.campaigns.service import get_active_enrollment_for_lead
    enrollment = get_active_enrollment_for_lead(lead_id)
    if not enrollment:
        return
    node = enrollment.get("campaign_nodes")
    if not node or node.get("type") != "send":
        return
    on_reply = node.get("config", {}).get("on_reply", "pause")
    if on_reply == "pause":
        pause_enrollment(enrollment["id"])
        logger.info("[CAMPAIGNS] Paused enrollment %s — lead replied", enrollment["id"])
    elif on_reply == "cancel":
        cancel_enrollment(enrollment["id"])
        logger.info("[CAMPAIGNS] Cancelled enrollment %s — lead replied", enrollment["id"])
```

- [ ] **Commit:**
```bash
git add backend/app/campaigns/worker.py
git commit -m "feat(campaigns): worker com trigger checker e enrollment executor"
```

---

### Task 4: Registrar campaigns no main.py + integrar broadcast + webhook

**Arquivos:**
- Modificar: `backend/app/main.py`
- Modificar: `backend/app/broadcast/worker.py`
- Modificar: `backend/app/webhook/router.py` (ou `parser.py` — onde mensagens recebidas são processadas)

- [ ] **Em `backend/app/main.py`, adicionar import e include_router:**

Localizar o bloco de imports dos routers (linha ~53) e adicionar após `follow_up_router`:
```python
from app.campaigns.router import router as campaigns_router
```

Localizar `app.include_router(follow_up_router)` e adicionar logo após:
```python
app.include_router(campaigns_router)
```

- [ ] **Em `backend/app/broadcast/worker.py`, na função `run_worker()`, adicionar chamadas ao campaigns worker:**

Localizar a função `run_worker()` (linha ~267) e modificar o loop:
```python
async def run_worker():
    """Main worker loop: processes broadcasts, cadences, and campaigns."""
    logger.info("Broadcast + Cadence + Campaign worker started")
    from app.campaigns.worker import check_campaign_triggers, process_campaign_enrollments

    while True:
        try:
            await process_broadcasts()
            await process_due_cadences()
            await process_reengagements()
            await process_stagnation_triggers()
            await process_due_followups()
            await check_campaign_triggers()
            await process_campaign_enrollments()
            reconcile_broadcast_replies()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)
```

- [ ] **Em `backend/app/broadcast/worker.py`, na função `process_single_broadcast()`, após o bloco de `cadence_id` (linha ~526), adicionar suporte a `campaign_id`:**

```python
# Enroll in new campaign if configured
if broadcast.get("campaign_id"):
    try:
        from app.campaigns.service import (
            get_campaign, list_nodes, create_enrollment as create_campaign_enrollment,
            is_already_enrolled,
        )
        campaign = get_campaign(broadcast["campaign_id"])
        if campaign and campaign["status"] == "active":
            nodes = list_nodes(campaign["id"])
            trigger = next((n for n in nodes if n["type"] == "trigger"), None)
            if trigger and trigger.get("next_node_id") and not is_already_enrolled(campaign["id"], lead["id"]):
                create_campaign_enrollment(
                    campaign_id=campaign["id"],
                    lead_id=lead["id"],
                    current_node_id=trigger["next_node_id"],
                    next_execute_at=datetime.now(timezone.utc),
                )
    except Exception as ce:
        logger.warning("[CAMPAIGNS] Could not enroll lead %s from broadcast: %s", lead["phone"], ce)
```

- [ ] **Localizar onde mensagens recebidas são processadas no backend (provavelmente `backend/app/webhook/router.py` ou `parser.py`). Encontre onde `lead_id` é extraído de uma mensagem de entrada e adicione após o processamento da mensagem:**

Abra `backend/app/webhook/router.py` e localize o handler de mensagens recebidas. Após processar a mensagem mas antes do retorno, adicione:
```python
# Notify campaign worker of reply
try:
    from app.campaigns.worker import handle_campaign_reply
    handle_campaign_reply(lead_id)  # usa o lead_id já extraído
except Exception as ce:
    logger.debug("[CAMPAIGNS] handle_campaign_reply error: %s", ce)
```

- [ ] **Verificar que o backend sobe sem erros:**
```bash
cd backend
python -m uvicorn app.main:app --reload --port 8001
```
Esperado: nenhum ImportError. O endpoint `GET /api/campaigns` retorna `{"data": []}`.

- [ ] **Commit:**
```bash
git add backend/app/main.py backend/app/broadcast/worker.py backend/app/webhook/
git commit -m "feat(campaigns): integrar router, worker e webhook reply handler"
```

---

## FASE 2 — Frontend

> **OBRIGATÓRIO:** Invocar o skill `frontend-design` antes de escrever qualquer componente de UI.

### Task 5: TypeScript types + Next.js API routes

**Arquivos:**
- Modificar: `frontend/src/lib/types.ts`
- Criar: `frontend/src/app/api/campaigns/route.ts`
- Criar: `frontend/src/app/api/campaigns/[id]/route.ts`
- Criar: `frontend/src/app/api/campaigns/[id]/activate/route.ts`
- Criar: `frontend/src/app/api/campaigns/[id]/pause/route.ts`
- Criar: `frontend/src/app/api/campaigns/[id]/nodes/route.ts`
- Criar: `frontend/src/app/api/campaigns/[id]/nodes/[nodeId]/route.ts`
- Criar: `frontend/src/app/api/campaigns/[id]/enrollments/route.ts`

- [ ] **Em `frontend/src/lib/types.ts`, adicionar ao final do arquivo:**

```typescript
// ─── Campaigns ────────────────────────────────────────────────────────────────

export type CampaignNodeType = "trigger" | "send" | "wait" | "condition" | "action" | "end";

export interface CampaignNode {
  id: string;
  campaign_id: string;
  type: CampaignNodeType;
  config: Record<string, unknown>;
  position_x: number;
  position_y: number;
  next_node_id: string | null;
  yes_node_id: string | null;
  no_node_id: string | null;
  created_at: string;
}

export interface Campaign {
  id: string;
  name: string;
  description: string | null;
  status: "draft" | "active" | "paused" | "archived";
  env_tag: string;
  start_date: string | null;
  created_at: string;
  updated_at: string;
  nodes?: CampaignNode[];
}

export interface CampaignEnrollment {
  id: string;
  campaign_id: string;
  lead_id: string;
  deal_id: string | null;
  status: "active" | "paused" | "completed" | "cancelled";
  current_node_id: string | null;
  next_execute_at: string | null;
  enrolled_at: string;
  completed_at: string | null;
  paused_at: string | null;
  env_tag: string;
  leads?: { id: string; name: string | null; phone: string; stage: string };
}
```

- [ ] **Criar `frontend/src/app/api/campaigns/route.ts`:**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaigns")
    .select("*")
    .eq("env_tag", APP_ENV)
    .order("created_at", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data });
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaigns")
    .insert({ name: body.name, description: body.description ?? null, status: "draft", env_tag: APP_ENV })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Criar `frontend/src/app/api/campaigns/[id]/route.ts`:**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

type Params = { params: Promise<{ id: string }> };

export async function GET(_req: NextRequest, { params }: Params) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data: campaign, error } = await supabase.from("campaigns").select("*").eq("id", id).single();
  if (error) return NextResponse.json({ error: error.message }, { status: 404 });
  const { data: nodes } = await supabase.from("campaign_nodes").select("*").eq("campaign_id", id);
  return NextResponse.json({ ...campaign, nodes: nodes ?? [] });
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaigns")
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(_req: NextRequest, { params }: Params) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data: camp } = await supabase.from("campaigns").select("status").eq("id", id).single();
  if (camp && !["draft", "archived"].includes(camp.status)) {
    return NextResponse.json({ error: "Apenas drafts e arquivadas podem ser excluídas" }, { status: 400 });
  }
  await supabase.from("campaigns").delete().eq("id", id);
  return NextResponse.json({ ok: true });
}
```

- [ ] **Criar `frontend/src/app/api/campaigns/[id]/activate/route.ts`:**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data: nodes } = await supabase.from("campaign_nodes").select("*").eq("campaign_id", id);
  const trigger = nodes?.find((n) => n.type === "trigger");
  if (!trigger?.next_node_id) {
    return NextResponse.json({ error: "Configure o fluxo antes de ativar" }, { status: 400 });
  }
  await supabase.from("campaigns").update({ status: "active", updated_at: new Date().toISOString() }).eq("id", id);
  return NextResponse.json({ status: "active" });
}
```

- [ ] **Criar `frontend/src/app/api/campaigns/[id]/pause/route.ts`:**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  await supabase.from("campaigns").update({ status: "paused", updated_at: new Date().toISOString() }).eq("id", id);
  return NextResponse.json({ status: "paused" });
}
```

- [ ] **Criar `frontend/src/app/api/campaigns/[id]/nodes/route.ts`:**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaign_nodes")
    .insert({ campaign_id: id, type: body.type, config: body.config ?? {}, position_x: body.position_x ?? 0, position_y: body.position_y ?? 0 })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Criar `frontend/src/app/api/campaigns/[id]/nodes/[nodeId]/route.ts`:**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

type Params = { params: Promise<{ id: string; nodeId: string }> };

export async function PATCH(request: NextRequest, { params }: Params) {
  const { nodeId } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase.from("campaign_nodes").update(body).eq("id", nodeId).select().single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(_req: NextRequest, { params }: Params) {
  const { nodeId } = await params;
  const supabase = await getServiceSupabase();
  await supabase.from("campaign_nodes").delete().eq("id", nodeId);
  return NextResponse.json({ ok: true });
}
```

- [ ] **Criar `frontend/src/app/api/campaigns/[id]/enrollments/route.ts`:**

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const status = new URL(request.url).searchParams.get("status");
  const supabase = await getServiceSupabase();
  let q = supabase.from("campaign_enrollments").select("*, leads!inner(id, name, phone, stage)").eq("campaign_id", id);
  if (status) q = q.eq("status", status);
  const { data, error } = await q.order("enrolled_at", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data: nodes } = await supabase.from("campaign_nodes").select("*").eq("campaign_id", id);
  const trigger = nodes?.find((n: { type: string }) => n.type === "trigger");
  if (!trigger?.next_node_id) return NextResponse.json({ error: "Campaign sem fluxo" }, { status: 400 });
  const { data, error } = await supabase
    .from("campaign_enrollments")
    .insert({ campaign_id: id, lead_id: body.lead_id, deal_id: body.deal_id ?? null, current_node_id: trigger.next_node_id, next_execute_at: new Date().toISOString(), env_tag: APP_ENV })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Commit:**
```bash
git add frontend/src/lib/types.ts frontend/src/app/api/campaigns/
git commit -m "feat(campaigns): types TS + Next.js API routes"
```

---

### Task 6: Hook realtime + Campaign List UI

> **OBRIGATÓRIO:** Invocar `frontend-design` skill antes de escrever os componentes.

**Arquivos:**
- Criar: `frontend/src/hooks/use-realtime-campaigns.ts`
- Modificar: `frontend/src/components/campaigns/cadence-list.tsx`
- Modificar: `frontend/src/components/campaigns/cadence-card.tsx`
- Modificar: `frontend/src/app/(authenticated)/campanhas/page.tsx`

- [ ] **Criar `frontend/src/hooks/use-realtime-campaigns.ts`:**

```typescript
"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Campaign } from "@/lib/types";

export function useRealtimeCampaigns() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    const res = await fetch("/api/campaigns");
    if (res.ok) {
      const json = await res.json();
      setCampaigns(json.data ?? []);
    }
    setLoading(false);
  };

  useEffect(() => {
    load();
    const supabase = createClient();
    const channel = supabase
      .channel("campaigns-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "campaigns" }, load)
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, []);

  return { campaigns, loading, refresh: load };
}
```

- [ ] **Reescrever `frontend/src/components/campaigns/cadence-list.tsx`** para usar Campaign em vez de Cadence (mantendo exatamente o mesmo visual e padrão do BroadcastList — filtros, grid 2 colunas, busca):

```typescript
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Campaign } from "@/lib/types";
import { CadenceCard } from "./cadence-card";

interface CadenceListProps {
  campaigns: Campaign[];
  onRefresh: () => void;
}

const FILTERS = [
  { key: "all", label: "Todas" },
  { key: "active", label: "Ativas" },
  { key: "draft", label: "Rascunho" },
  { key: "paused", label: "Pausadas" },
  { key: "archived", label: "Arquivadas" },
];

export function CadenceList({ campaigns, onRefresh }: CadenceListProps) {
  const router = useRouter();
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const filtered = campaigns.filter((c) => {
    if (filter !== "all" && c.status !== filter) return false;
    if (search && !c.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="bg-[#faf9f6]">
      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Buscar cadência..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-64"
        />
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={filter === f.key
                ? "bg-[#111111] text-white rounded-[4px] px-3 py-1.5 text-[13px]"
                : "border border-[#dedbd6] text-[#313130] rounded-[4px] px-3 py-1.5 text-[13px] hover:border-[#111111]"}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="text-[#7b7b78] text-center py-8">Nenhuma cadência encontrada</p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {filtered.map((c) => (
            <CadenceCard
              key={c.id}
              campaign={c}
              onClick={() => router.push(`/campanhas/cadencias/${c.id}`)}
              onRefresh={onRefresh}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Reescrever `frontend/src/components/campaigns/cadence-card.tsx`** para usar Campaign. Manter o mesmo padrão visual dos BroadcastCards (border, rounded-[8px], p-5, status badge). Mostrar: nome, status badge, contagem de nós, botão "Abrir":

```typescript
"use client";

import type { Campaign } from "@/lib/types";

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  draft:    { bg: "bg-[#f0ede8]",       text: "text-[#7b7b78]",   label: "Rascunho" },
  active:   { bg: "bg-[#0bdf50]/10",    text: "text-[#0bdf50]",   label: "Ativa" },
  paused:   { bg: "bg-[#fe4c02]/10",    text: "text-[#fe4c02]",   label: "Pausada" },
  archived: { bg: "bg-[#f0ede8]",       text: "text-[#7b7b78]",   label: "Arquivada" },
};

interface CadenceCardProps {
  campaign: Campaign;
  onClick: () => void;
  onRefresh: () => void;
}

export function CadenceCard({ campaign, onClick }: CadenceCardProps) {
  const st = STATUS_STYLES[campaign.status] ?? STATUS_STYLES.draft;
  const nodeCount = campaign.nodes?.length ?? 0;

  return (
    <div
      onClick={onClick}
      className="bg-white border border-[#dedbd6] rounded-[8px] p-5 cursor-pointer hover:border-[#111111] transition-colors"
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-[15px] font-medium text-[#111111] leading-tight">{campaign.name}</p>
          {campaign.description && (
            <p className="text-[12px] text-[#7b7b78] mt-0.5">{campaign.description}</p>
          )}
        </div>
        <span className={`text-[10px] font-semibold uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] flex-shrink-0 ml-2 ${st.bg} ${st.text}`}>
          {st.label}
        </span>
      </div>
      <div className="flex items-center gap-4 text-[12px] text-[#7b7b78]">
        <span>{nodeCount} nós</span>
        <span>·</span>
        <span>Criada {new Date(campaign.created_at).toLocaleDateString("pt-BR")}</span>
      </div>
    </div>
  );
}
```

- [ ] **Em `frontend/src/app/(authenticated)/campanhas/page.tsx`:**

Localizar `const { cadences, loading: cLoading } = useRealtimeCadences();` e substituir por:
```typescript
const { campaigns, loading: cLoading, refresh: refreshCampaigns } = useRealtimeCampaigns();
```

Adicionar import no topo:
```typescript
import { useRealtimeCampaigns } from "@/hooks/use-realtime-campaigns";
```

Remover o import de `useRealtimeCadences` se não for mais usado.

Localizar onde `<CadenceList cadences={cadences} />` é renderizado e substituir por:
```typescript
<CadenceList campaigns={campaigns} onRefresh={refreshCampaigns} />
```

Localizar `handleCreateCadence` e substituir por:
```typescript
const handleCreateCadence = async () => {
  if (!cadenceName.trim()) return;
  setCreatingSaving(true);
  try {
    const res = await fetch("/api/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: cadenceName.trim() }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(`Erro ao criar cadência: ${err.error || res.statusText}`);
      return;
    }
    const camp = await res.json();
    setCadenceName("");
    setShowCadenceModal(false);
    // Navigate to flow builder
    router.push(`/campanhas/cadencias/${camp.id}`);
  } catch (e) {
    alert(`Erro de rede: ${e}`);
  } finally {
    setCreatingSaving(false);
  }
};
```

- [ ] **Commit:**
```bash
git add frontend/src/hooks/use-realtime-campaigns.ts frontend/src/components/campaigns/cadence-list.tsx frontend/src/components/campaigns/cadence-card.tsx frontend/src/app/(authenticated)/campanhas/page.tsx
git commit -m "feat(campaigns): lista de cadências conectada às novas tabelas"
```

---

### Task 7: Flow Builder Page + Canvas

> **OBRIGATÓRIO:** Invocar `frontend-design` skill antes de escrever este componente.

**Arquivos:**
- Criar: `frontend/src/app/(authenticated)/campanhas/cadencias/[id]/page.tsx`
- Criar: `frontend/src/components/campaigns/cadence-flow-builder.tsx`

**Design de referência aprovado:** canvas `#f5f2ed` + dot grid, nós brancos com `3px stripe` no topo, fonte `Outfit` + `JetBrains Mono`, sombras `0 1px 3px rgba(0,0,0,.07), 0 4px 14px rgba(0,0,0,.08)`, selected state `0 0 0 2px #fff, 0 0 0 4px #E85D26`. Ver mockup aprovado no brainstorming.

**Cores por tipo de nó:**
- `trigger`: `#1a1a1a`
- `send`: `#E85D26`
- `wait`: `#3B7DD8`
- `condition`: `#C4920C`
- `action`: `#7C4DB8`
- `end`: `#1A9B6C`

- [ ] **Criar `frontend/src/app/(authenticated)/campanhas/cadencias/[id]/page.tsx`:**

```typescript
import { CadenceFlowBuilder } from "@/components/campaigns/cadence-flow-builder";

export default async function CadenceFlowPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CadenceFlowBuilder campaignId={id} />;
}
```

- [ ] **Criar `frontend/src/components/campaigns/cadence-flow-builder.tsx`.**

Este é o componente principal do flow builder. Deve ser implementado com o skill `frontend-design` ativo, seguindo exatamente o design aprovado no mockup `flow-builder-v3.html` (localizado em `.superpowers/brainstorm/*/content/flow-builder-v3.html`).

O componente deve incluir:

**Estado:**
```typescript
const [campaign, setCampaign] = useState<Campaign | null>(null);
const [nodes, setNodes] = useState<CampaignNode[]>([]);
const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
const [saving, setSaving] = useState(false);
```

**Lógica de carregamento:**
```typescript
useEffect(() => {
  fetch(`/api/campaigns/${campaignId}`)
    .then(r => r.json())
    .then(data => {
      setCampaign(data);
      setNodes(data.nodes ?? []);
    });
}, [campaignId]);
```

**Função de adicionar nó** (chamada pelo botão `+` nos port-outs):
```typescript
const addNode = async (afterNodeId: string, type: CampaignNodeType, position_x: number, position_y: number) => {
  const res = await fetch(`/api/campaigns/${campaignId}/nodes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, config: getDefaultConfig(type), position_x, position_y }),
  });
  const newNode = await res.json();
  // Link afterNode.next_node_id = newNode.id
  await fetch(`/api/campaigns/${campaignId}/nodes/${afterNodeId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ next_node_id: newNode.id }),
  });
  setNodes(prev => prev.map(n => n.id === afterNodeId ? { ...n, next_node_id: newNode.id } : n).concat(newNode));
};
```

**Função de salvar nó** (chamada pelo inspector):
```typescript
const saveNode = async (nodeId: string, config: Record<string, unknown>) => {
  setSaving(true);
  await fetch(`/api/campaigns/${campaignId}/nodes/${nodeId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  setNodes(prev => prev.map(n => n.id === nodeId ? { ...n, config } : n));
  setSaving(false);
};
```

**Função de ativar/pausar campanha:**
```typescript
const toggleActivation = async () => {
  const endpoint = campaign?.status === "active" ? "pause" : "activate";
  const res = await fetch(`/api/campaigns/${campaignId}/${endpoint}`, { method: "POST" });
  const data = await res.json();
  if (data.error) { alert(data.error); return; }
  setCampaign(prev => prev ? { ...prev, status: data.status } : prev);
};
```

**`getDefaultConfig`** — configs padrão por tipo de nó:
```typescript
function getDefaultConfig(type: CampaignNodeType): Record<string, unknown> {
  switch (type) {
    case "trigger":   return { trigger_type: "no_message", days: 30 };
    case "send":      return { template_name: "", template_language: "pt_BR", template_variables: {}, on_reply: "pause" };
    case "wait":      return { days: 3, send_start_hour: 7, send_end_hour: 18 };
    case "condition": return { condition_type: "replied_recently", days: 5 };
    case "action":    return { action_type: "move_stage", stage_id: "" };
    case "end":       return { label: "Concluído", final_actions: [] };
    default:          return {};
  }
}
```

**Conectores SVG** — calcular automaticamente a partir das relações `next_node_id`, `yes_node_id`, `no_node_id`:
```typescript
function buildEdges(nodes: CampaignNode[]) {
  const edges: { from: CampaignNode; to: CampaignNode; branch?: "yes" | "no" }[] = [];
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  for (const n of nodes) {
    if (n.next_node_id && byId[n.next_node_id]) edges.push({ from: n, to: byId[n.next_node_id] });
    if (n.yes_node_id && byId[n.yes_node_id]) edges.push({ from: n, to: byId[n.yes_node_id], branch: "yes" });
    if (n.no_node_id && byId[n.no_node_id]) edges.push({ from: n, to: byId[n.no_node_id], branch: "no" });
  }
  return edges;
}
```

**Bezier path SVG** (nó tem `position_x`, `position_y`, largura fixa 210px, altura estimada 88px):
```typescript
function bezierPath(from: CampaignNode, to: CampaignNode, branch?: "yes" | "no") {
  const NODE_W = 210, NODE_H = 88;
  let x1 = from.position_x + NODE_W / 2;
  if (branch === "yes") x1 = from.position_x + NODE_W * 0.27;
  if (branch === "no")  x1 = from.position_x + NODE_W * 0.73;
  const y1 = from.position_y + NODE_H;
  const x2 = to.position_x + NODE_W / 2;
  const y2 = to.position_y;
  const cy = (y1 + y2) / 2;
  return `M ${x1} ${y1} C ${x1} ${cy} ${x2} ${cy} ${x2} ${y2}`;
}
```

**Layout do componente:**
```tsx
return (
  <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
    {/* Topbar */}
    <Topbar campaign={campaign} onToggle={toggleActivation} onBack={() => router.push("/campanhas?tab=cadencias")} />
    <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
      {/* Palette */}
      <Palette />
      {/* Canvas */}
      <div style={{ flex: 1, overflow: "auto", background: "#f5f2ed",
        backgroundImage: "radial-gradient(circle, rgba(0,0,0,.1) 1px, transparent 1px)",
        backgroundSize: "22px 22px", position: "relative" }}>
        <div style={{ position: "relative", width: 1280, height: 960 }}>
          {/* SVG Edges */}
          <svg style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", pointerEvents: "none", overflow: "visible" }}>
            {buildEdges(nodes).map((edge, i) => (
              <path key={i} d={bezierPath(edge.from, edge.to, edge.branch)}
                stroke={edge.branch === "yes" ? "#1A9B6C" : edge.branch === "no" ? "#ef4444" : "#c8c2bb"}
                strokeWidth={1.5} fill="none" strokeLinecap="round" />
            ))}
          </svg>
          {/* Nodes */}
          {nodes.map(node => (
            <FlowNode key={node.id} node={node} selected={selectedNodeId === node.id}
              onClick={() => setSelectedNodeId(node.id)}
              onAddNext={(type) => addNode(node.id, type, node.position_x, node.position_y + 148)} />
          ))}
        </div>
      </div>
      {/* Inspector */}
      {selectedNodeId && (
        <Inspector node={nodes.find(n => n.id === selectedNodeId)!}
          saving={saving} onSave={saveNode} onClose={() => setSelectedNodeId(null)} />
      )}
    </div>
  </div>
);
```

Os sub-componentes `Topbar`, `Palette`, `FlowNode`, `Inspector` devem ser implementados no mesmo arquivo ou como funções internas, seguindo o design aprovado:
- **Topbar:** bg branco, border-b, título da campanha, badge de status, botão "Ativar" ou "Pausar", botão "←" voltar
- **Palette:** 196px, bg branco, border-r, itens com ícone tintado + nome + desc, grupos "Gatilhos" e "Ações"
- **FlowNode:** white card, 210px wide, 10px radius, 1px border `rgba(0,0,0,.06)`, 3px stripe no topo na cor do tipo, ícone em caixa tintada, kicker + título + detail, port-out no bottom (botão `+` em hover)
- **Inspector:** 256px, bg branco, border-l, header com ícone + título, body com campos de formulário para editar `config` do nó, footer com "Salvar"

- [ ] **Commit:**
```bash
git add frontend/src/app/(authenticated)/campanhas/cadencias/ frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "feat(campaigns): flow builder visual com canvas, nós e inspector"
```

---

### Task 8: CRM Campanhas Tab — mostrar campaign_enrollments

**Arquivos:**
- Modificar: `frontend/src/components/conversas/tabs/crm-campanhas-tab.tsx`

- [ ] **Atualizar `crm-campanhas-tab.tsx`** para buscar `campaign_enrollments` da nova tabela em paralelo com os dados de cadência antiga. Manter a seção "Disparos Recebidos" existente intacta.

Substituir o `useEffect` que busca `cadence_enrollments` por:
```typescript
useEffect(() => {
  import("@/lib/supabase/client").then(({ createClient }) => {
    const supabase = createClient();
    supabase
      .from("campaign_enrollments")
      .select("*, campaigns(id, name, created_at)")
      .eq("lead_id", leadId)
      .order("enrolled_at", { ascending: false })
      .then(({ data }) => {
        if (data) {
          setEnrollments(
            data.map((ce) => {
              const camp = ce.campaigns as { id: string; name: string; created_at: string } | null;
              return {
                campaign_name: camp?.name ?? "Campanha",
                campaign_created_at: camp?.created_at ?? "",
                status: ce.status as string,
                enrolled_at: ce.enrolled_at as string,
                next_execute_at: ce.next_execute_at as string | null,
                completed_at: ce.completed_at as string | null,
              };
            })
          );
        }
        setLoading(false);
      });
  });
}, [leadId]);
```

Atualizar a interface do estado:
```typescript
interface Enrollment {
  campaign_name: string;
  campaign_created_at: string;
  status: string;
  enrolled_at: string;
  next_execute_at: string | null;
  completed_at: string | null;
}
```

Atualizar o JSX para usar os novos campos (manter mesmo visual de cards com status badge e 3 métricas):
- Título: `c.campaign_name`
- Sub: `Iniciada em ${new Date(c.enrolled_at).toLocaleDateString("pt-BR")}`
- Métricas: status, próximo envio (`next_execute_at`), concluído (`completed_at`)

Atualizar o label da seção de `Cadencias` para `Cadências` (com acento).

- [ ] **Commit:**
```bash
git add frontend/src/components/conversas/tabs/crm-campanhas-tab.tsx
git commit -m "feat(campaigns): CRM tab mostra campaign_enrollments da nova tabela"
```

---

## Self-Review do Plano

### Cobertura da Spec
- [x] Tabelas `campaigns`, `campaign_nodes`, `campaign_enrollments` → Fase 0
- [x] API CRUD completa → Tasks 2 + 5
- [x] Trigger checker: `no_message`, `stage_stagnation`, `stage_enter`, `post_broadcast` → Task 3 (`check_campaign_triggers`)
- [x] Enrollment executor: send, wait, condition, action, end → Task 3 (`process_campaign_enrollments`)
- [x] Comportamento ao responder (on_reply) → Task 3 (`handle_campaign_reply`) + Task 4 (webhook)
- [x] Worker integrado no loop → Task 4
- [x] Flow builder UI → Task 7
- [x] Campaign list → Task 6
- [x] CRM tab → Task 8
- [x] `post_broadcast` trigger (broadcast → campaign enrollment) → Task 4

### Gaps identificados e corrigidos
- `post_broadcast` trigger não tinha implementação no `check_campaign_triggers` — este tipo é tratado pelo broadcast worker diretamente (Task 4), não pelo checker periódico. Correto.
- `campaign_nodes` fk self-referential: Supabase suporta, mas a migration usa `ON DELETE SET NULL` para evitar cascade loops. Correto.
- O `get_due_enrollments` usa o nome da FK `campaign_enrollments_current_node_id_fkey` — verificar o nome exato gerado pelo Supabase após a migration e ajustar o select se necessário. O nome gerado automaticamente pode diferir; use `.select("*, campaign_nodes(*)")` com join explícito se der erro.

### Consistência de tipos
- `CampaignNode`, `Campaign`, `CampaignEnrollment` definidos em `types.ts` (Task 5) e usados em Tasks 6, 7, 8. ✓
- `CadenceList` agora recebe `campaigns: Campaign[]` (Task 6) — prop renomeada de `cadences` para `campaigns`. ✓
- `CadenceCard` agora recebe `campaign: Campaign` (Task 6). ✓

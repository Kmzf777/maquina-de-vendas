from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase
from app.config import get_settings
from app.events.bus import emit_event

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


def _is_unique_violation(exc: Exception) -> bool:
    s = str(exc).lower()
    return "23505" in s or "duplicate key" in s or "uq_campaign_enrollments_active" in s


def create_enrollment(campaign_id: str, lead_id: str, current_node_id: str, next_execute_at: datetime, deal_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    sb = get_supabase()
    try:
        row = sb.table("campaign_enrollments").insert({
            "campaign_id": campaign_id,
            "lead_id": lead_id,
            "deal_id": deal_id,
            "current_node_id": current_node_id,
            "next_execute_at": next_execute_at.isoformat(),
            "env_tag": _ENV_TAG,
            "metadata": metadata or {},
        }).execute().data[0]
    except Exception as exc:
        if not _is_unique_violation(exc):
            raise
        # Already enrolled (unique index) — return the live enrollment, no-op (no wake-up).
        rows = (
            sb.table("campaign_enrollments")
            .select("*")
            .eq("campaign_id", campaign_id)
            .eq("lead_id", lead_id)
            .in_("status", ["active", "paused"])
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else {}
    emit_event("automation")  # wake-up do worker (fail-open; fallback tick cobre)
    return row


def get_due_enrollments(now: datetime, limit: int = 20) -> list[dict[str, Any]]:
    sb = get_supabase()
    return (
        sb.table("campaign_enrollments")
        .select("*, leads!inner(id, phone, name, company, stage, ai_enabled), campaign_nodes!campaign_enrollments_current_node_id_fkey(*)")
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .lte("next_execute_at", now.isoformat())
        .order("next_execute_at", desc=False)
        .limit(limit)
        .execute()
        .data
    )


CLAIM_STALE_SECONDS = 300  # 5 min — mirrors follow_up crash-recovery cutoff.


def claim_enrollment(enrollment_id: str, now: datetime) -> bool:
    """Atomic pending→claimed guard. True only if THIS worker won the row.

    Guarded UPDATE: only claims an active enrollment whose claim is free or stale.
    Mirrors follow_up._claim_followup_job. Fail-open→False (skip, retry next tick)."""
    from datetime import timedelta
    try:
        sb = get_supabase()
        stale = (now - timedelta(seconds=CLAIM_STALE_SECONDS)).isoformat()
        res = (
            sb.table("campaign_enrollments")
            .update({"claimed_at": now.isoformat()})
            .eq("id", enrollment_id)
            .eq("status", "active")
            .or_(f"claimed_at.is.null,claimed_at.lt.{stale}")
            .execute()
        )
        return bool(res.data)
    except Exception:
        return False


def release_enrollment_claim(enrollment_id: str) -> None:
    """Clear the claim lock so the next tick can re-claim (used on advance/complete/fail)."""
    try:
        sb = get_supabase()
        sb.table("campaign_enrollments").update({"claimed_at": None}).eq("id", enrollment_id).execute()
    except Exception:
        pass


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


def reset_enrollment(enrollment_id: str, first_node_id: str) -> None:
    """Rebobina a matricula para o primeiro no, mantendo-a ATIVA.

    Terceira politica de `on_reply`, ao lado de `cancel` e `pause`. Existe para a esteira
    "Em conversa" da reuniao de 10/09/2026: 7 toques em 30 dias, e qualquer resposta do
    lead devolve o relogio para D+0.

    MANTER `status='active'` e o ponto do desenho, nao um detalhe. Cancelar e reinscrever
    pareceria equivalente, mas o cooldown de 90 dias da RPC `get_deals_stage_stagnant`
    conta QUALQUER matricula por `enrolled_at`, sem filtrar status — o card ficaria
    inelegivel por tres meses. Como o reset nao passa pelo caminho de reinscricao, o
    cooldown nunca e consultado.

    `last_sent_node_id=None` porque ele e a idempotencia do envio: carregado para o no
    rebobinado, faria o primeiro toque do novo ciclo ser pulado como se ja tivesse saido.
    `paused_at=None` limpa residuo de uma pausa anterior.
    """
    sb = get_supabase()
    sb.table("campaign_enrollments").update({
        "status": "active",
        "current_node_id": first_node_id,
        "next_execute_at": datetime.now(timezone.utc).isoformat(),
        "step_count": 0,
        "last_sent_node_id": None,
        "retry_count": 0,
        "last_error": None,
        "paused_at": None,
        "claimed_at": None,
    }).eq("id", enrollment_id).execute()


def cancel_enrollments_for_lead(lead_id: str) -> int:
    """Cancela TODOS os enrollments vivos do lead. Devolve quantos foram cancelados.

    Chamada por `leads/service.py::apply_optout_side_effects`, o ponto onde os três
    caminhos de opt-out convergem (botão de saída do template, tool `registrar_optout`,
    `POST /api/leads/{id}/optout`). Sem isto o opt-out desarmava só o motor de follow-up
    e deixava o de campanhas armado: o próximo toque da cadência saía para quem tinha
    acabado de pedir para parar.

    Alcança `paused` além de `active` por dois motivos: um enrollment pausado pode ser
    retomado à mão, e `is_already_enrolled` conta os dois estados como "já inscrito" —
    deixá-lo pendurado tornaria o lead INELEGÍVEL PARA SEMPRE para qualquer campanha
    futura, mesmo que ele volte a comprar daqui a um ano.

    Uma consulta só (`UPDATE ... WHERE lead_id AND status IN (...)`), não N leituras
    seguidas de N `cancel_enrollment`. Idempotente pelo próprio filtro: a segunda chamada
    não encontra linha nenhuma.

    Sem filtro de `env_tag` de propósito, ao contrário do resto do módulo: dev e produção
    dividem o mesmo Supabase, e do outro lado há UMA pessoa. Um opt-out que deixasse viva
    a inscrição do outro ambiente ainda mandaria mensagem para ela.
    """
    if not lead_id:
        return 0
    sb = get_supabase()
    result = (
        sb.table("campaign_enrollments")
        .update({"status": "cancelled"})
        .eq("lead_id", lead_id)
        .in_("status", ["active", "paused"])
        .execute()
    )
    return len(result.data or [])


def get_active_enrollment_for_lead(lead_id: str) -> dict[str, Any] | None:
    """UM enrollment ativo do lead — o primeiro que o PostgREST devolver.

    ATENÇÃO: "um" é arbitrário. Sem `ORDER BY`, o `.limit(1)` devolve a linha que o
    planner entregar primeiro. Quem precisa AGIR sobre a resposta do lead deve usar
    `get_active_enrollments_for_lead` (plural): `is_already_enrolled` é por CAMPANHA,
    então o mesmo lead pode estar em várias esteiras ao mesmo tempo e tratar só uma
    deixa as outras armadas.
    """
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


def get_active_enrollments_for_lead(lead_id: str) -> list[dict[str, Any]]:
    """TODOS os enrollments ativos do lead, cada um com o nó em que está parado.

    Existe porque `is_already_enrolled` é por CAMPANHA: nada impede — e no desenho das
    esteiras é o caso NORMAL — que o mesmo lead esteja em duas ao mesmo tempo (card de
    recompra em "Já chamado" na esteira de reposição + card em "Proposta Enviada" na
    esteira de proposta; `ensure_reposicao_deal` cria cards de recompra e a base tem
    leads com vários deals).

    Com o `.limit(1)` da irmã singular, a resposta do lead encerrava a linha sorteada
    pelo banco: ou a esteira de proposta mandava o toque de D+8 para quem já tinha
    respondido, ou a de reposição rodava até o fim e marcava como PERDIDO o card de um
    lead que engajou.

    Sem `limit`: um lead tem unidades de esteira na casa das unidades, e devolver de
    menos aqui é exatamente o bug que esta função corrige.
    """
    sb = get_supabase()
    result = (
        sb.table("campaign_enrollments")
        .select("*, campaign_nodes!campaign_enrollments_current_node_id_fkey(type, config)")
        .eq("lead_id", lead_id)
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .execute()
    )
    return result.data or []


def get_campaigns_with_trigger_type(trigger_type: str) -> list[dict[str, Any]]:
    """Returns active campaigns that have a trigger node of the given type."""
    sb = get_supabase()
    campaigns = sb.table("campaigns").select("id").eq("status", "active").eq("env_tag", _ENV_TAG).execute().data
    if not campaigns:
        return []
    campaign_ids = [c["id"] for c in campaigns]
    nodes = (
        sb.table("campaign_nodes")
        .select("*, campaigns!inner(id, status, channel_id, audience)")
        .eq("type", "trigger")
        .in_("campaign_id", campaign_ids)
        .execute()
        .data
    )
    # Flatten channel_id onto the node so trigger callers can gate enrollment
    # by the lead's conversation followup_enabled in that channel.
    out = []
    for n in nodes:
        if n["config"].get("trigger_type") == trigger_type:
            n["channel_id"] = (n.get("campaigns") or {}).get("channel_id")
            # Público da campanha (ver engine._audience_allows). Ausente → 'ia',
            # o comportamento histórico — nunca o modo mais permissivo.
            n["audience"] = (n.get("campaigns") or {}).get("audience") or "ia"
            out.append(n)
    return out


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


def mark_enrollment_sent(enrollment_id: str, node_id: str, wamid: str | None) -> None:
    """Persist idempotency marker BEFORE advancing to the next node.

    If the worker crashes after send but before advance, recovery skips the
    re-send because last_sent_node_id == current_node_id. Mirrors
    follow_up._save_followup_wamid. Fail-open: DB errors are swallowed."""
    try:
        sb = get_supabase()
        sb.table("campaign_enrollments").update({
            "last_sent_node_id": node_id, "last_sent_wamid": wamid,
        }).eq("id", enrollment_id).execute()
    except Exception:
        pass


def recover_stale_enrollments(now: datetime, stale_seconds: int = CLAIM_STALE_SECONDS) -> int:
    """Clear stale claims (worker died mid-tick) so rows re-enter. Idempotency guard
    (last_sent_node_id) prevents any resend. Mirrors follow_up._recover_stale_followup_jobs.
    Fail-open: returns 0 on any DB error."""
    from datetime import timedelta
    try:
        sb = get_supabase()
        cutoff = (now - timedelta(seconds=stale_seconds)).isoformat()
        res = (
            sb.table("campaign_enrollments")
            .update({"claimed_at": None})
            .eq("status", "active")
            .eq("env_tag", _ENV_TAG)
            .lt("claimed_at", cutoff)
            .execute()
        )
        return len(res.data or [])
    except Exception:
        return 0

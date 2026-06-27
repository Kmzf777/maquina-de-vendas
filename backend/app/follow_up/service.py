import logging
import os
import random
from datetime import datetime, timezone, timedelta, time
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"

_SP_TZ = ZoneInfo("America/Sao_Paulo")
_BUSINESS_START = time(9, 0)
_BUSINESS_END = time(16, 0)

# 1o follow-up NUNCA "cravado em 1h" (robotico, cara de cobranca de vendas). Sorteia um
# intervalo natural entre ~1.5h e ~3.5h; o clamp de janela comercial ainda se aplica.
_SEQ1_MIN_MINUTES = 90
_SEQ1_MAX_MINUTES = 210


def is_within_business_window(target: datetime) -> bool:
    """True se `target` (UTC) cai na janela comercial 09h-16h, seg-sex, America/Sao_Paulo."""
    local = target.astimezone(_SP_TZ)
    return local.weekday() < 5 and _BUSINESS_START <= local.time() < _BUSINESS_END


def _clamp_to_business_window(target: datetime) -> datetime:
    """Garante que `target` (UTC) caia na janela comercial 09h-16h, seg-sex,
    America/Sao_Paulo. Se estiver fora, empurra para o proximo horario valido
    (mesmo dia 09h se for antes da janela; proximo dia util 09h se for depois
    da janela ou fim de semana).
    """
    local = target.astimezone(_SP_TZ)

    if is_within_business_window(target):
        return target

    if local.weekday() < 5 and local.time() < _BUSINESS_START:
        clamped_local = local.replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        return clamped_local.astimezone(timezone.utc)

    # Fora da janela (>= 16h) ou fim de semana: avanca para o proximo dia util as 09h.
    next_day = local + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    clamped_local = next_day.replace(hour=9, minute=0, second=0, microsecond=0)
    return clamped_local.astimezone(timezone.utc)


def schedule_followup(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    warm: bool = True,
) -> None:
    """Cancela jobs pendentes anteriores desta conversa e insere a cadência via build_touch_jobs.

    `warm=True` (default): cadência completa (T1 same-day). `warm=False` (lead frio sem interesse):
    suprime o T1 — cadência começa no T2 (anti-bombardeio).
    """
    sb = get_supabase()
    now = datetime.now(timezone.utc)

    # Verifica se a conversa existe
    try:
        conv_check = (
            sb.table("conversations")
            .select("id")
            .eq("id", conversation_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao verificar existência da conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao verificar conversa {conversation_id} no banco de dados"
        ) from exc

    if not conv_check.data:
        raise ValueError(
            f"conversation_id '{conversation_id}' não existe na tabela conversations"
        )

    # Cancela pending da mesma conversa (idempotência).
    # Preserva lp_welcome — é independente do ciclo de follow-up manual.
    try:
        sb.table("follow_up_jobs").update({
            "status": "cancelled",
            "cancel_reason": "rescheduled",
        }).eq("conversation_id", conversation_id).eq("status", "pending").not_.in_(
            "job_type", ["handoff_rescue", "lp_welcome"]
        ).execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao cancelar jobs anteriores da conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao cancelar follow-up jobs pendentes para conversa {conversation_id}"
        ) from exc

    # Cadência multi-touch (4 toques) — config-as-code em follow_up/cadence.py.
    # fire_at monotônico (espaçado >= MIN_GAP) e clampado à janela comercial.
    from app.follow_up.cadence import build_touch_jobs
    jobs = build_touch_jobs(now, conversation_id, lead_id, channel_id, _ENV_TAG, warm=warm)
    try:
        sb.table("follow_up_jobs").insert(jobs).execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao inserir jobs para conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao criar follow-up jobs para conversa {conversation_id}"
        ) from exc

    logger.info(f"[FOLLOWUP] Agendados {len(jobs)} toques de cadência conversation={conversation_id}")


def cancel_followups(conversation_id: str, reason: str) -> None:
    """Cancela todos os jobs pending de uma conversa."""
    sb = get_supabase()
    try:
        sb.table("follow_up_jobs").update({
            "status": "cancelled",
            "cancel_reason": reason,
        }).eq("conversation_id", conversation_id).eq("status", "pending").neq("job_type", "handoff_rescue").execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao cancelar follow-ups da conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao cancelar follow-up jobs para conversa {conversation_id}"
        ) from exc
    logger.info(f"[FOLLOWUP] Cancelado reason={reason} conversation={conversation_id}")


def cancel_followups_by_phone(phone: str, reason: str) -> None:
    """Cancela follow-ups pending de todas as conversas de um lead pelo phone."""
    sb = get_supabase()

    try:
        lead_result = (
            sb.table("leads")
            .select("id")
            .eq("phone", phone)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error(f"[FOLLOWUP] Erro ao buscar lead pelo phone {phone}: {exc}")
        raise RuntimeError(
            f"Falha ao buscar lead pelo phone {phone}"
        ) from exc

    if not lead_result.data:
        return

    lead_id = lead_result.data[0]["id"]

    try:
        conversations = (
            sb.table("conversations")
            .select("id")
            .eq("lead_id", lead_id)
            .execute()
        )
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao buscar conversas do lead {lead_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao buscar conversas do lead {lead_id}"
        ) from exc

    if not conversations.data:
        return

    conv_ids = [c["id"] for c in conversations.data]
    try:
        sb.table("follow_up_jobs").update({
            "status": "cancelled",
            "cancel_reason": reason,
        }).in_("conversation_id", conv_ids).eq("status", "pending").neq("job_type", "handoff_rescue").execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao cancelar follow-ups pelo phone {phone}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao cancelar follow-up jobs para o phone {phone}"
        ) from exc

    logger.info(f"[FOLLOWUP] Cancelado reason={reason} phone={phone}")


def schedule_handoff_rescue(
    lead_id: str,
    lead_phone: str,
    conversation_id: str,
    channel_id: str,
    delay_minutes: int = 15,
    lead_name: str = "",
) -> datetime | None:
    """Agenda um job de resgate de handoff (job_type='handoff_rescue') para fire em delay_minutes.

    Retorna o `fire_at` (UTC) efetivamente agendado — clampado para a janela comercial —
    ou None quando o agendamento é ignorado (REHEARSAL_MODE). O retorno permite ao chamador
    informar ao lead quando o vendedor entrará em contato.
    """
    if os.environ.get("REHEARSAL_MODE") == "true":
        logger.info("[HANDOFF_RESCUE] REHEARSAL_MODE ativo — rescue ignorado")
        return None
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    fire_at = _clamp_to_business_window(now + timedelta(minutes=delay_minutes))
    job = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "channel_id": channel_id,
        "sequence": 1,
        "fire_at": fire_at.isoformat(),
        "status": "pending",
        "env_tag": _ENV_TAG,
        "job_type": "handoff_rescue",
        "metadata": {
            "lead_phone": lead_phone,
            "lead_name": lead_name,
            "joao_phone_number_id": "1049315514934778",
            "template_name": "automacao_valeria_to_joao",
            # Locale APROVADO na Meta (message_templates): automacao_valeria_to_joao só
            # existe em `en`. pt_BR não existe → 404 #132001. Ver scheduler.JOAO_TEMPLATE_LANG.
            "language_code": "en",
        },
    }
    try:
        sb.table("follow_up_jobs").insert(job).execute()
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Erro ao inserir rescue job para lead {lead_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao agendar job de resgate para lead {lead_id}"
        ) from exc
    logger.info(
        f"[HANDOFF_RESCUE] Agendado em {delay_minutes}min lead={lead_id} conversation={conversation_id} fire_at={fire_at.isoformat()}"
    )
    return fire_at


def schedule_ai_return(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    fire_at: datetime,
    metadata: dict[str, Any] | None = None,
) -> datetime:
    """Agenda um RETORNO AUTÔNOMO da IA (job_type='ai_scheduled_return') no `fire_at` pedido.

    Usado pela tool `agendar_retorno`: quando o lead marca um horário ("falo sexta"), a própria
    Valéria agenda o job, independente do motor genérico de follow-up. O `fire_at` é clampado
    para a janela comercial (09h-16h, seg-sex). Retorna o `fire_at` efetivo (clampado), para a
    tool informar ao lead o horário correto. Levanta RuntimeError em falha de insert.
    """
    clamped = _clamp_to_business_window(fire_at)
    if os.environ.get("REHEARSAL_MODE") == "true":
        logger.info("[AI_SCHEDULED_RETURN] REHEARSAL_MODE ativo — agendamento ignorado")
        return clamped
    sb = get_supabase()
    job = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "channel_id": channel_id,
        "sequence": 1,
        "fire_at": clamped.isoformat(),
        "status": "pending",
        "env_tag": _ENV_TAG,
        "job_type": "ai_scheduled_return",
        "metadata": metadata or {},
    }
    try:
        sb.table("follow_up_jobs").insert(job).execute()
    except Exception as exc:
        logger.error(
            "[AI_SCHEDULED_RETURN] Erro ao inserir job p/ lead %s: %s", lead_id, exc
        )
        raise RuntimeError(f"Falha ao agendar retorno para lead {lead_id}") from exc
    logger.info(
        "[AI_SCHEDULED_RETURN] Agendado lead=%s conv=%s fire_at=%s",
        lead_id, conversation_id, clamped.isoformat(),
    )
    return clamped


# Eixo 3B: TTL do contexto de retomada. Após o disparo de reabertura (continuar_conversa),
# o lead tem 7 dias para responder e a IA retomar o assunto. Passado isso, o contexto é
# considerado obsoleto (anti-contexto-zumbi) e descartado.
REOPEN_TTL_DAYS = 7


def _update_job_status(job_id: str, status: str, sent_at: datetime | None = None) -> None:
    payload: dict[str, Any] = {"status": status}
    if sent_at is not None:
        payload["sent_at"] = sent_at.isoformat()
    try:
        get_supabase().table("follow_up_jobs").update(payload).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("[REOPEN] falha ao atualizar job %s p/ %s: %s", job_id, status, exc)


def consume_reopen_context(conversation_id: str, now: datetime) -> str | None:
    """Retoma um retorno agendado cuja janela havia fechado (Eixo 3B).

    Se há um job `awaiting_reopen` para a conversa e o lead respondeu DENTRO do TTL de 7 dias,
    marca o job `sent` e devolve um bloco <retorno_agendado> com motivo/contexto p/ a IA retomar.
    Fora do TTL: marca `expired` e devolve None (trata como inbound orgânico). Fail-open: None.
    """
    if not conversation_id:
        return None
    try:
        res = (
            get_supabase()
            .table("follow_up_jobs")
            .select("id, sent_at, fire_at, metadata")
            .eq("conversation_id", conversation_id)
            .eq("status", "awaiting_reopen")
            .order("fire_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.warning("[REOPEN] falha ao buscar awaiting_reopen p/ conv %s: %s", conversation_id, exc)
        return None

    job = res.data[0] if res.data else None
    if not job:
        return None

    ref_str = job.get("sent_at") or job.get("fire_at")
    try:
        ref = datetime.fromisoformat(str(ref_str).replace("Z", "+00:00"))
    except Exception:
        ref = now
    if now - ref > timedelta(days=REOPEN_TTL_DAYS):
        _update_job_status(job["id"], "expired")
        logger.info("[REOPEN] contexto expirado (TTL %dd) p/ conv %s — tratando como inbound", REOPEN_TTL_DAYS, conversation_id)
        return None

    _update_job_status(job["id"], "sent", sent_at=now)
    md = job.get("metadata") or {}
    motivo = (md.get("motivo") or "").strip()
    contexto = (md.get("contexto") or "").strip()
    return (
        "<retorno_agendado>\n"
        "Você tinha combinado de retomar este contato e a janela reabriu agora que o lead respondeu. "
        + (f"Motivo combinado: {motivo}. " if motivo else "")
        + (f"Contexto: {contexto}. " if contexto else "")
        + "Retome esse ponto de forma natural e pessoal — NÃO diga que foi um lembrete automático "
        "nem mencione agendamento.\n"
        "</retorno_agendado>"
    )


def find_pending_ai_return(conversation_id: str) -> dict[str, Any] | None:
    """Retorna o job ai_scheduled_return `pending` desta conversa, se houver (Eixo 3A).

    Base da idempotência da tool `agendar_retorno`: se já existe um retorno agendado, a
    IA não deve criar outro. Fail-open: em erro de DB retorna None (a tool agenda normal).
    """
    if not conversation_id:
        return None
    try:
        res = (
            get_supabase()
            .table("follow_up_jobs")
            .select("id, fire_at, metadata")
            .eq("conversation_id", conversation_id)
            .eq("status", "pending")
            .eq("job_type", "ai_scheduled_return")
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as exc:
        logger.warning("[AI_SCHEDULED_RETURN] falha ao buscar pending p/ conv %s: %s", conversation_id, exc)
        return None


def get_due_followups(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    """Retorna jobs pending cujo fire_at já passou."""
    sb = get_supabase()
    try:
        result = (
            sb.table("follow_up_jobs")
            .select(
                "*, "
                "leads!inner(id, phone, name, last_customer_message_at, wa_id), "
                "channels!inner(id, name, provider, provider_config, mode), "
                "conversations!inner(id, stage, followup_enabled, last_customer_message_at)"
            )
            .eq("status", "pending")
            .eq("env_tag", _ENV_TAG)
            .lte("fire_at", now.isoformat())
            .order("fire_at", desc=False)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        logger.error(f"[FOLLOWUP] Erro ao buscar follow-ups devidos: {exc}")
        raise RuntimeError("Falha ao buscar follow-up jobs devidos") from exc

    if not result.data:
        return []

    return result.data

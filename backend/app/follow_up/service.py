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
) -> None:
    """Cancela jobs pendentes anteriores e cria 2 novos (1o com jitter ~1.5-3.5h, 2o em 23h)."""
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

    # Clamp na janela comercial (09h-16h, seg-sex, America/Sao_Paulo): prioridade absoluta
    # é NUNCA disparar de madrugada para lead de prospecção. Aceita-se que o seq=2 (23h) possa,
    # ao ser empurrado para o próximo dia útil, eventualmente estourar a janela Meta de 24h
    # (o guard window_expired em process_due_followups cancela com segurança nesse caso).
    seq1_minutes = random.randint(_SEQ1_MIN_MINUTES, _SEQ1_MAX_MINUTES)
    fire_at_seq1 = _clamp_to_business_window(now + timedelta(minutes=seq1_minutes))
    fire_at_seq2 = _clamp_to_business_window(now + timedelta(hours=23))
    jobs = [
        {
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": 1,
            "fire_at": fire_at_seq1.isoformat(),
            "status": "pending",
            "env_tag": _ENV_TAG,
        },
        {
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": 2,
            "fire_at": fire_at_seq2.isoformat(),
            "status": "pending",
            "env_tag": _ENV_TAG,
        },
    ]
    try:
        sb.table("follow_up_jobs").insert(jobs).execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao inserir jobs para conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao criar follow-up jobs para conversa {conversation_id}"
        ) from exc

    logger.info(f"[FOLLOWUP] Agendado seq=1 e seq=2 conversation={conversation_id}")


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

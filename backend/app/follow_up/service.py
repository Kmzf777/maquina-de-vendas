import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.config import get_settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"


def schedule_followup(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
) -> None:
    """Cancela jobs pendentes anteriores e cria 2 novos (1h e 23h)."""
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

    # Cancela pending da mesma conversa (idempotência)
    try:
        sb.table("follow_up_jobs").update({
            "status": "cancelled",
            "cancel_reason": "rescheduled",
        }).eq("conversation_id", conversation_id).eq("status", "pending").execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao cancelar jobs anteriores da conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao cancelar follow-up jobs pendentes para conversa {conversation_id}"
        ) from exc

    jobs = [
        {
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": 1,
            "fire_at": (now + timedelta(hours=1)).isoformat(),
            "status": "pending",
            "env_tag": _ENV_TAG,
        },
        {
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": 2,
            "fire_at": (now + timedelta(hours=23)).isoformat(),
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
        }).eq("conversation_id", conversation_id).eq("status", "pending").execute()
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
        }).in_("conversation_id", conv_ids).eq("status", "pending").execute()
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
) -> None:
    """Agenda um job de resgate de handoff (job_type='handoff_rescue') para fire em delay_minutes."""
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    job = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "channel_id": channel_id,
        "sequence": 1,
        "fire_at": (now + timedelta(minutes=delay_minutes)).isoformat(),
        "status": "pending",
        "env_tag": _ENV_TAG,
        "job_type": "handoff_rescue",
        "metadata": {
            "lead_phone": lead_phone,
            "joao_phone_number_id": "1049315514934778",
            "template_name": "rabubens",
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
        f"[HANDOFF_RESCUE] Agendado em {delay_minutes}min lead={lead_id} conversation={conversation_id}"
    )


def get_due_followups(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    """Retorna jobs pending cujo fire_at já passou."""
    sb = get_supabase()
    try:
        result = (
            sb.table("follow_up_jobs")
            .select(
                "*, "
                "leads!inner(id, phone, last_customer_message_at), "
                "channels!inner(id, name, provider, provider_config, mode), "
                "conversations!inner(id, stage, followup_enabled)"
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

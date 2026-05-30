# backend/app/follow_up/scheduler.py
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.follow_up.service import get_due_followups
from app.leads.service import save_message
from app.whatsapp.registry import get_provider
from app.db.supabase import get_supabase
from app.channels.service import get_channel_by_provider_config
from app.whatsapp.meta import MetaCloudClient

logger = logging.getLogger(__name__)


_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_FOLLOWUP_MODEL = "gemini-2.5-flash"


async def _generate_followup_message(history: list[dict], sequence: int) -> str:
    """Gera mensagem contextualizada via LLM para o follow-up."""
    client = AsyncOpenAI(
        api_key=settings.gemini_api_key,
        base_url=_GEMINI_BASE_URL,
    )

    sequence_context = (
        "Esta é a primeira tentativa de retomar contato (1 hora após o último envio do vendedor). "
        "Seja leve, curioso e natural. Não pressione. Apenas demonstre interesse genuíno."
        if sequence == 1
        else
        "Esta é a última tentativa antes da janela de atendimento expirar (23 horas após o último envio). "
        "Seja mais direto, crie senso de oportunidade, mas sem ser agressivo."
    )

    messages_text = "\n".join(
        f"{'Cliente' if m['role'] == 'user' else 'Vendedor'}: {m['content']}"
        for m in history
    )

    resp = await client.chat.completions.create(
        model=_FOLLOWUP_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um assistente de vendas do Café Canastra. "
                    "Com base no histórico da conversa, escreva uma mensagem de follow-up para WhatsApp. "
                    f"{sequence_context} "
                    "Use linguagem informal brasileira, sem emojis excessivos. "
                    "Máximo 3 linhas. Não use saudações formais como 'Olá' ou 'Bom dia'. "
                    "Seja contextual — faça referência ao que foi discutido."
                ),
            },
            {
                "role": "user",
                "content": f"Histórico da conversa:\n{messages_text}\n\nEscreva o follow-up:",
            },
        ],
        max_tokens=200,
        temperature=0.8,
    )
    return (resp.choices[0].message.content or "").strip()


async def process_due_followups(now: datetime | None = None) -> None:
    """Processa jobs de follow-up vencidos. Chamado pelo worker a cada tick."""
    now = now or datetime.now(timezone.utc)
    jobs = get_due_followups(now)

    for job in jobs:
        # Rota jobs de resgate de handoff para handler dedicado (antes de qualquer guard padrão)
        if job.get("job_type") == "handoff_rescue":
            await _process_handoff_rescue(job, now)
            continue

        if job.get("job_type") == "lp_welcome":
            await _process_lp_welcome(job, now)
            continue

        conversation_id = job["conversation_id"]
        lead = job["leads"]
        channel = job["channels"]
        conversation = job["conversations"]
        sequence = job["sequence"]

        # Guard: toggle desativado
        if not conversation.get("followup_enabled", True):
            _cancel_job(job["id"], "followup_disabled")
            logger.info(
                f"[FOLLOWUP] followup_enabled=false — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Guard: canal humano nunca executa follow-up
        if channel.get("mode", "ai") == "human":
            _cancel_job(job["id"], "human_channel")
            logger.info(
                f"[FOLLOWUP] mode=human — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Guard: janela de 24h
        last_msg_str = lead.get("last_customer_message_at")
        if not last_msg_str:
            _cancel_job(job["id"], "window_expired")
            logger.info(
                f"[FOLLOWUP] Sem last_customer_message_at — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        last_msg = datetime.fromisoformat(last_msg_str.replace("Z", "+00:00"))
        if last_msg + timedelta(hours=24) <= now:
            _cancel_job(job["id"], "window_expired")
            logger.info(
                f"[FOLLOWUP] Janela expirada — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Busca histórico e gera mensagem via LLM
        try:
            sb = get_supabase()
            history_result = (
                sb.table("messages")
                .select("role, content")
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            history = list(reversed(history_result.data or []))
            history = [m for m in history if m.get("role") and m.get("content")]
            message = await _generate_followup_message(history, sequence)
        except Exception as e:
            logger.error(f"[FOLLOWUP] Erro ao gerar mensagem seq={sequence} conversation={conversation_id}: {e}", exc_info=True)
            continue

        if not message:
            _cancel_job(job["id"], "empty_response")
            logger.warning(
                f"[FOLLOWUP] LLM retornou vazio — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Envia via WhatsApp
        try:
            provider = get_provider(channel)
            await provider.send_text(lead["phone"], message)
        except Exception as e:
            logger.error(
                f"[FOLLOWUP] Falha ao enviar seq={sequence} lead={lead['phone']}: {e}",
                exc_info=True,
            )
            # Intencional per spec: em caso de falha no envio, não atualiza status — job será retentado no próximo tick
            continue

        # Persiste mensagem
        try:
            save_message(
                lead_id=job["lead_id"],
                role="assistant",
                content=message,
                stage=conversation.get("stage"),
                sent_by="followup",
                conversation_id=conversation_id,
            )
        except Exception as e:
            logger.error(f"[FOLLOWUP] Falha ao salvar mensagem seq={sequence}: {e}")

        _mark_sent(job["id"])
        logger.info(f"[FOLLOWUP] Enviado seq={sequence} lead={lead['phone']}")


async def _process_handoff_rescue(job: dict, now: datetime) -> None:
    """Verifica se lead contatou João nos últimos 15 min. Se não, dispara template de resgate."""
    metadata = job.get("metadata") or {}
    lead_phone = metadata.get("lead_phone")
    joao_phone_number_id = metadata.get("joao_phone_number_id", "1049315514934778")
    template_name = metadata.get("template_name", "automacao_valeria_to_joao")
    language_code = metadata.get("language_code", "en_US")

    if not lead_phone:
        _cancel_job(job["id"], "missing_lead_phone")
        logger.error(f"[HANDOFF_RESCUE] Job {job['id']} sem lead_phone no metadata")
        return

    joao_channel = get_channel_by_provider_config("phone_number_id", joao_phone_number_id, "meta_cloud")
    if not joao_channel:
        _cancel_job(job["id"], "joao_channel_not_found")
        logger.error(
            f"[HANDOFF_RESCUE] Canal do João (phone_number_id={joao_phone_number_id}) não encontrado"
        )
        return

    sb = get_supabase()
    cutoff = (now - timedelta(minutes=15)).isoformat()

    try:
        conv_result = (
            sb.table("conversations")
            .select("id")
            .eq("lead_id", job["lead_id"])
            .eq("channel_id", joao_channel["id"])
            .execute()
        )
        if conv_result.data:
            conv_ids = [c["id"] for c in conv_result.data]
            msg_result = (
                sb.table("messages")
                .select("id")
                .in_("conversation_id", conv_ids)
                .eq("role", "user")
                .gte("created_at", cutoff)
                .limit(1)
                .execute()
            )
            if msg_result.data:
                logger.info(
                    f"[HANDOFF_RESCUE] Lead {job['lead_id']} já contatou João — resgate desnecessário"
                )
                _mark_sent(job["id"])
                return
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Erro ao verificar contato do lead {job['lead_id']}: {exc}",
            exc_info=True,
        )
        # Segurança: se falhou a verificação, envia o template (falso negativo > falso positivo)

    try:
        provider = MetaCloudClient(joao_channel["provider_config"])
        await provider.send_template(lead_phone, template_name, language_code=language_code)
        logger.info(f"[HANDOFF_RESCUE] Template '{template_name}' ({language_code}) enviado para {lead_phone}")
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Falha ao enviar template para {lead_phone}: {exc}",
            exc_info=True,
        )
        return  # Não marca sent → job será retentado no próximo tick do worker

    _mark_sent(job["id"])


async def _process_lp_welcome(job: dict, now: datetime) -> None:
    """Dispara template de boas-vindas para lead capturado por landing page."""
    metadata = job.get("metadata") or {}
    lead_phone = metadata.get("lead_phone")
    template_name = metadata.get("template_name")
    language_code = metadata.get("language_code", "pt_BR")
    channel = job["channels"]

    if not lead_phone or not template_name:
        _cancel_job(job["id"], "missing_metadata")
        logger.error(
            "[LP_WELCOME] Job %s sem lead_phone ou template_name no metadata", job["id"]
        )
        return

    try:
        provider = MetaCloudClient(channel["provider_config"])
        await provider.send_template(lead_phone, template_name, language_code=language_code)
        logger.info("[LP_WELCOME] Template '%s' enviado para %s", template_name, lead_phone)
    except Exception as exc:
        logger.error(
            "[LP_WELCOME] Falha ao enviar template para %s: %s", lead_phone, exc, exc_info=True
        )
        return  # Não marca sent → retry automático no próximo tick

    _mark_sent(job["id"])


def _cancel_job(job_id: str, reason: str) -> None:
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": reason,
    }).eq("id", job_id).execute()


def _mark_sent(job_id: str) -> None:
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()

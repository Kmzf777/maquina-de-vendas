# backend/app/follow_up/scheduler.py
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.follow_up.service import get_due_followups
from app.leads.service import save_message
from app.whatsapp.registry import get_provider
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


async def _generate_followup_message(history: list[dict], sequence: int) -> str:
    """Gera mensagem contextualizada via LLM para o follow-up."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)

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
        model="gpt-4.1-mini",
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

"""Reengajamento pontual (ad-hoc) — leads inbound sem resposta no apagão de LLM de 2026-07-01/02.

Quatro conversas cujo cliente enviou a última mensagem e a Valéria NÃO respondeu (falha durante
o erro de billing/cota do LLM). Este script reproduz o caminho INBOUND do processor — resolve a
persona dinamicamente, roda `run_agent` sobre a última mensagem do cliente e envia a resposta via
Meta — reusando exatamente as funções de produção. NÃO reimplementa buffer/lock/typing/mídia.

Escopo fechado: age SOMENTE nos 4 `conversation_id` da allowlist abaixo. Guards estritos por
conversa (qualquer um falha → pula, não envia):
  1. lead.ai_enabled = True         (respeita handoff ao humano feito durante o apagão)
  2. canal em modo IA               (canal humano nunca roda IA)
  3. janela de 24h da Meta aberta   (free-text fora da janela é rejeitado: #131047/#131026)
  4. idempotência: a última mensagem da conversa ainda é do cliente (ninguém respondeu no meio)

`run_agent` roda o loop ReAct real: tools com efeito colateral (mudar_stage, encaminhar_humano)
podem disparar — é o comportamento desejado, idêntico a uma mensagem que chegasse ao vivo.

Uso (a partir de backend/, com o AMBIENTE DE PRODUÇÃO carregado — Supabase prod, GEMINI_API_KEY;
as credenciais Meta vêm do próprio canal no banco):

    python -m scripts.reengage_pending_leads_2026_07_02
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase
from app.leads.service import get_lead, resolve_send_target
from app.channels.service import get_channel_by_id
from app.conversations.service import save_message
from app.whatsapp.registry import get_provider
from app.whatsapp.meta import extract_wamid
from app.humanizer.splitter import split_into_bubbles
from app.agent.orchestrator import run_agent, resolve_prompt_key
from app.buffer.processor import _resolve_agent_profile_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reengage")

# Allowlist fechada — 2ª varredura (2026-07-02): backlog do apagão, inbound elegíveis dentro
# da janela de 24h (ai_enabled=true, canal ai, não opt_out/on_hold, última msg > 10min atrás).
CONVERSATION_IDS = [
    "4c977936-aa9f-4268-8016-6452dbe005da",  # 5521971494391 — "Ok" (resposta ao welcome LP)
    "b50b6eb3-6624-4d58-b0e5-f4e488b3beca",  # 5554999101323 — "Não"
    "705a1c69-7f00-44d4-a805-7025280dbe19",  # 5548996701713 — "Olá, me chamo sall... produtos p/ vender"
    "dc653b6e-6873-4373-a8b4-7e396bf691a0",  # 5528999885316 — "vocês vendem embalagens men..."
    "ca982e9f-828e-4a6c-b97e-ec0b97d093ab",  # 5511964434525 — "Seu site direcionou p/ meu nº comercial"
    "3b4e9595-39da-4d7b-b95e-d7d86c159fce",  # 5511968640413 — "Sou o Davi... como funciona o sistema"
    "67b47325-dfe1-44ba-8aa7-731a54d5bd89",  # 5551997183410 — "Olá, boa tarde"
    "6643eb2f-39e8-454b-a209-536c8eb7c1c7",  # 5541996860023 — "Boa tarde... informações sobre o café"
    "c3f6c00c-eeef-42b1-98a5-8ad33224c407",  # 5562984206558 — "comprar saca de café de 60"
    "f89a75f8-0d06-4809-9859-8811314aa38b",  # 5531995801090 — "Gustavo Medina... Betim MG"
]

_WINDOW = timedelta(hours=24)


async def reengage_one(conversation_id: str) -> None:
    sb = get_supabase()

    conv = (
        sb.table("conversations")
        .select("id, lead_id, channel_id, stage, agent_profile_id, last_customer_message_at")
        .eq("id", conversation_id)
        .single()
        .execute()
    ).data
    if not conv:
        logger.warning("SKIP %s: conversa não encontrada", conversation_id)
        return

    lead = get_lead(conv["lead_id"]) or {}
    phone = lead.get("phone")

    # Guard 1 — IA ligada (não reengaja lead entregue ao humano durante o apagão).
    if not lead.get("ai_enabled", False):
        logger.info("SKIP %s (%s): ai_enabled=false (handoff humano)", conversation_id, phone)
        return

    # Guard 2 — canal em modo IA.
    channel = get_channel_by_id(conv["channel_id"])
    if not channel or channel.get("mode", "ai") == "human":
        logger.info("SKIP %s (%s): canal humano/ausente", conversation_id, phone)
        return

    # Guard 3 — janela de 24h da Meta aberta.
    lcm = conv.get("last_customer_message_at")
    now = datetime.now(timezone.utc)
    if not lcm or datetime.fromisoformat(lcm.replace("Z", "+00:00")) + _WINDOW <= now:
        logger.info("SKIP %s (%s): janela de 24h fechada", conversation_id, phone)
        return

    # Guard 4 — idempotência: a última mensagem ainda é do cliente (não responder duas vezes).
    last = (
        sb.table("messages")
        .select("role, content")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not last or last[0].get("role") != "user":
        logger.info("SKIP %s (%s): já respondida (última msg não é do cliente)", conversation_id, phone)
        return
    orphan_text = (last[0].get("content") or "").strip()
    if not orphan_text:
        logger.info("SKIP %s (%s): última mensagem do cliente vazia", conversation_id, phone)
        return

    # Reproduz o inbound do processor: persona resolvida dinamicamente + run_agent sobre a órfã.
    conversation = dict(conv)
    conversation["leads"] = lead
    agent_profile_id = _resolve_agent_profile_id(conversation, channel)
    agent_persona = resolve_prompt_key(agent_profile_id)

    response = await run_agent(
        conversation,
        orphan_text,
        lead_context=lead.get("metadata") or {},
        agent_profile_id=agent_profile_id,
    )

    if response is None:
        # encaminhar_humano foi chamado pela tool — o handoff já foi enviado por ela.
        logger.info("HANDOFF %s (%s): encaminhar_humano — nada a enviar", conversation_id, phone)
        return
    response = response.strip()
    if not response:
        logger.info("SKIP %s (%s): resposta vazia da IA", conversation_id, phone)
        return

    # Envio Meta — destino entregável (wa_id real quando houver; evita #131026).
    send_to = resolve_send_target(lead, phone)
    provider = get_provider(channel)
    bubbles = split_into_bubbles(response)

    sent_wamids: list[str | None] = []
    for bubble in bubbles:
        result = await provider.send_text(send_to, bubble)
        sent_wamids.append(extract_wamid(result))

    for bubble, wamid in zip(bubbles, sent_wamids):
        save_message(
            conversation_id=conversation_id,
            lead_id=conv["lead_id"],
            role="assistant",
            content=bubble,
            stage=conv.get("stage"),
            sent_by="agent",
            wamid=wamid,
            agent_persona=agent_persona,
        )

    logger.info("SENT %s (%s): %d bolha(s), persona=%s", conversation_id, phone, len(bubbles), agent_persona)


async def main() -> None:
    logger.info("Reengajamento pontual — %d conversa(s)", len(CONVERSATION_IDS))
    for cid in CONVERSATION_IDS:
        try:
            await reengage_one(cid)
        except Exception:
            logger.exception("FALHA ao reengajar %s", cid)
    logger.info("Concluído.")


if __name__ == "__main__":
    asyncio.run(main())

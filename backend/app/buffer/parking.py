"""Estacionamento de turnos durante indisponibilidade do LLM (Onda 2, 09/07/2026).

Auditoria 08/07: o outage de 13min (17:39-17:52) em cima do run de disparo queimou
2/9 respostas com handoff CEGO — o lead mandou "Sim" e recebeu na hora o cartão do
João, sem a Valéria nunca ter conversado. Handoff é ação DEFINITIVA (desliga a IA);
um outage de minutos não deveria custar o funil inteiro do lead.

Contrato:
  - LLM fora → `processor._handle_llm_down` ESTACIONA o turno aqui (park_turn) em vez
    de encaminhar: hash Redis `llm:parked`, no máximo 1 entrada por conversa (a mais
    recente vence — o run_agent do retry relê o histórico completo do banco, então o
    texto estacionado é só o gatilho do turno, não o contexto).
  - O worker drena a cada tick (drain_parked_llm_turns): LLM voltou → responde o
    turno normalmente (bolhas + save + persona); ainda fora e dentro da janela →
    mantém estacionado; janela estourada (LLM_PARK_MAX_MINUTES, default 30) → handoff
    pelo caminho de hoje (`encaminhar_humano`) — NUNCA fantasma silencioso.
  - Kill-switch sem deploy: LLM_PARKING=off restaura o handoff imediato.

Guards do drain (em ordem): lead com IA desligada → descarta (humano assumiu);
atividade assistant/system mais nova que o estacionamento → descarta (turno
superseded — outro worker/humano já respondeu); erro genérico no retry → handoff
visível (falha não-transitória não fica em loop).

Contador de falhas: o sucesso do drain zera `llm:consecutive_failures` (a mesma
chave do processor), fechando o ciclo do alerta llm_down.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import redis.asyncio as _aioredis

from app.config import settings
from app.agent.orchestrator import run_agent, LLMUnavailableError
from app.agent.tools import execute_tool
from app.channels.service import get_channel_by_id
from app.conversations.service import save_message
from app.db.supabase import get_supabase
from app.humanizer.splitter import split_into_bubbles
from app.leads.service import get_lead, resolve_send_target
from app.whatsapp.meta import extract_wamid
from app.whatsapp.registry import get_provider

logger = logging.getLogger(__name__)

PARKED_KEY = "llm:parked"
# Mesma chave do processor (_LLM_FAILURE_KEY) — o sucesso do drain zera o contador.
_LLM_FAILURE_KEY = "llm:consecutive_failures"
_BUBBLE_GAP_SECONDS = 2.0

_parking_redis_client: "_aioredis.Redis | None" = None


def _get_parking_redis() -> "_aioredis.Redis":
    global _parking_redis_client
    if _parking_redis_client is None:
        _parking_redis_client = _aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _parking_redis_client


def parking_enabled() -> bool:
    """LLM_PARKING=off desliga o estacionamento (volta ao handoff imediato)."""
    return os.environ.get("LLM_PARKING", "on").strip().lower() != "off"


def _park_max_minutes() -> int:
    try:
        return int(os.environ.get("LLM_PARK_MAX_MINUTES", "30"))
    except ValueError:
        return 30


async def park_turn(conversation: dict, lead: dict, phone: str, inbound_text: str | None) -> bool:
    """Estaciona o turno desta conversa. 1 entrada por conversa (a mais recente vence).

    Retorna True quando estacionou; False em falha de Redis (o chamador decide o
    fallback — em _handle_llm_down, False degrada para o handoff imediato de hoje).
    """
    entry = {
        "lead_id": lead.get("id"),
        "phone": phone,
        "channel_id": conversation.get("channel_id"),
        "stage": conversation.get("stage"),
        "text": inbound_text or "",
        "parked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await _get_parking_redis().hset(PARKED_KEY, conversation["id"], json.dumps(entry))
        logger.warning(
            "[LLM PARK] turno estacionado p/ conv %s (phone=%s) — drain no worker",
            conversation.get("id"), phone,
        )
        return True
    except Exception as exc:
        logger.error("[LLM PARK] falha ao estacionar conv %s: %s", conversation.get("id"), exc)
        return False


def _fetch_conversation(conversation_id: str) -> dict | None:
    try:
        res = (
            get_supabase().table("conversations")
            .select("*").eq("id", conversation_id).limit(1).execute()
        )
        rows = res.data if isinstance(res.data, list) else []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("[LLM PARK] falha ao ler conversa %s: %s", conversation_id, exc)
        return None


def _has_newer_activity(conversation_id: str, parked_at_iso: str) -> bool:
    """True se a conversa já teve resposta assistant/system DEPOIS do estacionamento
    (outro turno respondeu, vendedor assumiu etc.) — a entrada estacionada está stale.
    Fail-closed=False: na dúvida, reprocessa (run_agent relê o histórico e responde
    holisticamente; pior caso é uma resposta a mais, nunca um fantasma)."""
    try:
        res = (
            get_supabase().table("messages")
            .select("id")
            .eq("conversation_id", conversation_id)
            .in_("role", ["assistant", "system"])
            .gt("created_at", parked_at_iso)
            .limit(1)
            .execute()
        )
        return isinstance(res.data, list) and bool(res.data)
    except Exception as exc:
        logger.warning("[LLM PARK] falha ao checar atividade nova p/ %s: %s", conversation_id, exc)
        return False


async def _handoff_parked(entry: dict, conversation_id: str) -> None:
    """Janela de parking estourada ou falha não-transitória → handoff visível (caminho
    de hoje). Fail-soft."""
    try:
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras",
             "motivo": "IA temporariamente indisponível — atendimento encaminhado ao humano"},
            lead_id=entry.get("lead_id"), phone=entry.get("phone"),
            conversation_id=conversation_id,
        )
    except Exception as exc:
        logger.error(
            "[LLM PARK] handoff pós-parking falhou p/ conv %s: %s",
            conversation_id, exc, exc_info=True,
        )


async def _reply_parked_turn(entry: dict, conversation: dict, lead: dict) -> None:
    """LLM voltou: gera e envia a resposta do turno estacionado (bolhas + persist)."""
    conversation = dict(conversation)
    conversation["leads"] = lead
    response = await run_agent(conversation, entry.get("text") or "")
    if not response:
        # run_agent resolveu o turno internamente (ex.: handoff via tool) — nada a enviar.
        return
    channel = get_channel_by_id(entry.get("channel_id")) or {"id": entry.get("channel_id")}
    provider = get_provider(channel)
    send_to = resolve_send_target(lead, entry.get("phone") or "")
    bubbles = split_into_bubbles(response) or [response]
    agent_persona = conversation.get("agent_persona")
    for i, bubble in enumerate(bubbles):
        send_result = await provider.send_text(send_to, bubble)
        try:
            save_message(
                conversation["id"], lead["id"], "assistant", bubble,
                conversation.get("stage"), sent_by="agent",
                wamid=extract_wamid(send_result), agent_persona=agent_persona,
            )
        except Exception as exc:
            logger.error("[LLM PARK] falha ao salvar bolha p/ conv %s: %s", conversation["id"], exc)
        if i < len(bubbles) - 1:
            await asyncio.sleep(_BUBBLE_GAP_SECONDS)


async def drain_parked_llm_turns(now: datetime | None = None) -> int:
    """Drena o hash de turnos estacionados. Chamado a cada tick do worker.

    Retorna o nº de entradas RESOLVIDAS com resposta enviada. Fail-soft por entrada:
    uma conversa quebrada não impede as demais.
    """
    if os.environ.get("REHEARSAL_MODE") == "true":
        return 0
    now = now or datetime.now(timezone.utc)
    try:
        entries = await _get_parking_redis().hgetall(PARKED_KEY)
    except Exception as exc:
        logger.debug("[LLM PARK] Redis indisponível no drain: %s", exc)
        return 0
    if not entries:
        return 0

    resolved = 0
    max_age = timedelta(minutes=_park_max_minutes())
    for conversation_id, raw in entries.items():
        try:
            entry = json.loads(raw)
        except Exception:
            await _pop(conversation_id)
            continue
        try:
            parked_at = datetime.fromisoformat(str(entry.get("parked_at")).replace("Z", "+00:00"))
        except Exception:
            parked_at = now - max_age  # sem timestamp legível → trata como expirado

        try:
            lead = get_lead(entry.get("lead_id")) or {}
            if not lead.get("ai_enabled", True):
                logger.info("[LLM PARK] conv %s: IA desligada (humano assumiu) — descartando", conversation_id)
                await _pop(conversation_id)
                continue
            if _has_newer_activity(conversation_id, entry.get("parked_at") or now.isoformat()):
                logger.info("[LLM PARK] conv %s: atividade mais nova — turno superseded, descartando", conversation_id)
                await _pop(conversation_id)
                continue
            conversation = _fetch_conversation(conversation_id) or {
                "id": conversation_id, "stage": entry.get("stage"),
                "channel_id": entry.get("channel_id"),
            }
            await _reply_parked_turn(entry, conversation, lead)
        except LLMUnavailableError:
            if now - parked_at > max_age:
                logger.warning(
                    "[LLM PARK] conv %s: janela de %dmin estourada com LLM ainda fora — handoff",
                    conversation_id, _park_max_minutes(),
                )
                await _pop(conversation_id)
                await _handoff_parked(entry, conversation_id)
            # dentro da janela: mantém estacionado p/ o próximo tick
            continue
        except Exception as exc:
            logger.error(
                "[LLM PARK] conv %s: falha não-transitória no retry (%s) — handoff visível",
                conversation_id, exc, exc_info=True,
            )
            await _pop(conversation_id)
            await _handoff_parked(entry, conversation_id)
            continue

        # Sucesso: limpa a entrada e zera o contador de falhas consecutivas do LLM.
        await _pop(conversation_id)
        resolved += 1
        try:
            await _get_parking_redis().delete(_LLM_FAILURE_KEY)
        except Exception:
            pass
    if resolved:
        logger.info("[LLM PARK] drain resolveu %d turno(s) estacionado(s)", resolved)
    return resolved


async def _pop(conversation_id: str) -> None:
    try:
        await _get_parking_redis().hdel(PARKED_KEY, conversation_id)
    except Exception as exc:
        logger.warning("[LLM PARK] falha ao remover entrada %s: %s", conversation_id, exc)

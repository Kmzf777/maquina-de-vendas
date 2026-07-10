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

Wartime 10/07/2026 — modo "cofre vazio": exaustão LONGA (kill-switch de budget interno,
quota diária/billing do Google) ganhou categoria própria. Cada entrada agora carrega
`reason` ("transient"/"budget"/"quota") e `deadline` (ISO) calculado no park:
transient = parked_at+30min (comportamento atual); budget = próxima 00:00 UTC (reset do
budget_guard) + folga; quota = próxima 00:00 America/Los_Angeles (reset das quotas
diárias da Gemini API) + folga — ambos com teto duro de LLM_PARK_EXHAUSTED_MAX_HOURS.
Sem isso, um estouro de budget às 10h estacionava cada lead por 30min e depois queimava
o funil do dia inteiro em handoff cego. O lead recebe UMA mensagem estática de espera
(cooldown Redis por conversa) para nunca ser fantasmado; o drain pula entradas de
budget enquanto `budget_guard.is_exceeded()` (custo zero) e throttla o retry de quota
(LLM_PARK_RETRY_MINUTES) p/ não queimar RPM a cada tick de 30s. Entrada legada (sem
`deadline`) mantém o comportamento antigo.
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


def _env_int(name: str, default: int) -> int:
    """Knob inteiro de env com default seguro (mesmo espírito de _park_max_minutes)."""
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _exhausted_grace_minutes() -> int:
    """Folga pós-reset antes do deadline: o budget_guard tem cache de 30s e o Google não
    reseta a quota no segundo exato da virada — sem folga, o drain faria handoff em cima
    de um LLM que volta minutos depois."""
    return _env_int("LLM_PARK_EXHAUSTED_GRACE_MINUTES", 30)


def _exhausted_max_hours() -> int:
    """Teto DURO do parking exausto: nenhum lead fica estacionado mais que isso, mesmo
    que o cálculo de virada dê errado (ex.: fuso mal resolvido). 26h cobre a pior
    combinação virada+folga com margem."""
    return _env_int("LLM_PARK_EXHAUSTED_MAX_HOURS", 26)


def _retry_minutes() -> int:
    """Throttle do retry do drain p/ reason=quota — o tick do worker é de 30s; sem
    throttle, cada entrada quota queimaria o RPM restante a cada tick."""
    return _env_int("LLM_PARK_RETRY_MINUTES", 5)


def _hold_msg_cooldown_hours() -> int:
    return _env_int("LLM_HOLD_MSG_COOLDOWN_HOURS", 6)


def _la_timezone():
    """Fuso das quotas diárias da Gemini API (reset à meia-noite America/Los_Angeles).

    Fail-soft: sem base IANA (tzdata ausente) cai em UTC-8 fixo (PST) — no pior caso
    (horário de verão) o deadline fica 1h mais tarde, coberto pela folga + teto duro.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")
    except Exception:
        return timezone(timedelta(hours=-8))


def _next_midnight(now: datetime, tz) -> datetime:
    """Próxima meia-noite no fuso dado, devolvida em UTC (comparável ao relógio do drain)."""
    local = now.astimezone(tz)
    nxt = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.astimezone(timezone.utc)


def _compute_deadline(reason: str, parked_at: datetime) -> datetime:
    """Deadline do parking por categoria (wartime 10/07).

    transient → parked_at + LLM_PARK_MAX_MINUTES (30, contrato da Onda 2);
    budget    → próxima 00:00 UTC (reset do budget_guard) + folga;
    quota     → próxima 00:00 America/Los_Angeles (reset das quotas Gemini) + folga.
    Exaustos têm teto duro parked_at + LLM_PARK_EXHAUSTED_MAX_HOURS.
    """
    if reason == "budget":
        deadline = _next_midnight(parked_at, timezone.utc) + timedelta(minutes=_exhausted_grace_minutes())
    elif reason == "quota":
        deadline = _next_midnight(parked_at, _la_timezone()) + timedelta(minutes=_exhausted_grace_minutes())
    else:
        return parked_at + timedelta(minutes=_park_max_minutes())
    return min(deadline, parked_at + timedelta(hours=_exhausted_max_hours()))


# Mensagem estática de espera do modo "cofre vazio" (persona, minúsculas, sem prometer
# prazo). O disparo outbound é pago: cada lead que responde é o ativo mais caro da
# operação — ghosting é inaceitável (classe apagão 01-02/07). A janela de 24h da Meta
# está aberta por construção (o lead acabou de escrever).
_HOLD_MSG = "oi! me desculpa a demora, tô finalizando uns atendimentos aqui 🙈 já te respondo, tá?"


async def _maybe_send_hold_message(conversation: dict, lead: dict, phone: str) -> None:
    """Envia UMA mensagem de espera ao estacionar por exaustão (budget/quota).

    Cooldown por conversa via SETNX `llm:hold_msg:{conversation_id}` (TTL
    LLM_HOLD_MSG_COOLDOWN_HOURS, default 6h) — o lead que escreve 3x durante o estouro
    recebe a espera só 1x. Fail-CLOSED no cooldown (Redis em dúvida → não envia:
    martelar é pior que 1 espera perdida) e fail-soft TOTAL: nenhuma falha aqui pode
    impedir o estacionamento. Suprimida em REHEARSAL_MODE (testes nunca geram tráfego).
    Mesmo padrão de envio do _reply_parked_turn (provider do canal + save_message).
    """
    if os.environ.get("REHEARSAL_MODE") == "true":
        return
    conversation_id = conversation.get("id")
    try:
        acquired = await _get_parking_redis().set(
            f"llm:hold_msg:{conversation_id}", "1",
            nx=True, ex=_hold_msg_cooldown_hours() * 3600,
        )
    except Exception as exc:
        logger.warning(
            "[LLM PARK] Redis indisponível p/ cooldown da msg de espera conv=%s — "
            "fail-closed (não envia): %s", conversation_id, exc,
        )
        return
    if not acquired:
        logger.debug("[LLM PARK] msg de espera em cooldown p/ conv %s", conversation_id)
        return
    try:
        channel = get_channel_by_id(conversation.get("channel_id")) or {"id": conversation.get("channel_id")}
        provider = get_provider(channel)
        send_to = resolve_send_target(lead, phone or "")
        send_result = await provider.send_text(send_to, _HOLD_MSG)
        try:
            save_message(
                conversation_id, lead.get("id"), "assistant", _HOLD_MSG,
                conversation.get("stage"), sent_by="agent",
                wamid=extract_wamid(send_result),
            )
        except Exception as exc:
            logger.error("[LLM PARK] falha ao salvar msg de espera p/ conv %s: %s", conversation_id, exc)
        logger.info("[LLM PARK] msg de espera enviada p/ conv %s (phone=%s)", conversation_id, phone)
    except Exception as exc:
        logger.warning("[LLM PARK] falha ao enviar msg de espera p/ conv %s: %s", conversation_id, exc)


async def park_turn(
    conversation: dict, lead: dict, phone: str, inbound_text: str | None,
    reason: str = "transient",
) -> bool:
    """Estaciona o turno desta conversa. 1 entrada por conversa (a mais recente vence).

    `reason` ∈ {"transient", "budget", "quota"} determina o `deadline` gravado na
    entrada (ver _compute_deadline). Reason exausto (budget/quota) também dispara a
    mensagem estática de espera — fail-soft: falha no envio NÃO impede o park.

    Retorna True quando estacionou; False em falha de Redis (o chamador decide o
    fallback — em _handle_llm_down, False degrada para o handoff imediato de hoje).
    """
    parked_at = datetime.now(timezone.utc)
    entry = {
        "lead_id": lead.get("id"),
        "phone": phone,
        "channel_id": conversation.get("channel_id"),
        "stage": conversation.get("stage"),
        "text": inbound_text or "",
        "parked_at": parked_at.isoformat(),
        "reason": reason,
        "deadline": _compute_deadline(reason, parked_at).isoformat(),
    }
    try:
        await _get_parking_redis().hset(PARKED_KEY, conversation["id"], json.dumps(entry))
        logger.warning(
            "[LLM PARK] turno estacionado p/ conv %s (phone=%s, reason=%s, deadline=%s) — drain no worker",
            conversation.get("id"), phone, reason, entry["deadline"],
        )
    except Exception as exc:
        logger.error("[LLM PARK] falha ao estacionar conv %s: %s", conversation.get("id"), exc)
        return False
    if reason in ("budget", "quota"):
        try:
            await _maybe_send_hold_message(conversation, lead, phone)
        except Exception as exc:  # rede extra: nada da espera pode desfazer o park
            logger.warning("[LLM PARK] msg de espera falhou p/ conv %s (park mantido): %s",
                           conversation.get("id"), exc)
    return True


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
    holisticamente; pior caso é uma resposta a mais, nunca um fantasma).

    A mensagem de espera (_HOLD_MSG) é EXCLUÍDA da checagem: ela é maquinário do
    próprio parking (salva como assistant logo APÓS o park) — sem o .neq, toda entrada
    exausta seria descartada como "superseded" no 1º tick do drain e o lead ficaria
    fantasma até a virada do dia (exatamente o que o modo cofre-vazio existe p/ evitar).
    """
    try:
        res = (
            get_supabase().table("messages")
            .select("id")
            .eq("conversation_id", conversation_id)
            .in_("role", ["assistant", "system"])
            .neq("content", _HOLD_MSG)
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
        reason = entry.get("reason") or "transient"
        # Deadline POR ENTRADA (wartime 10/07). Entrada legada (estacionada por versão
        # anterior, sem o campo) mantém o contrato antigo: parked_at + 30min, transient.
        deadline: datetime | None = None
        if entry.get("deadline"):
            try:
                deadline = datetime.fromisoformat(str(entry["deadline"]).replace("Z", "+00:00"))
            except Exception:
                deadline = None
        if deadline is None:
            deadline = parked_at + max_age

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
            # Drain econômico p/ reason=budget: enquanto o kill-switch interno segue
            # ativo, chamar run_agent só levantaria LLMBudgetExceededError de novo —
            # is_exceeded() é cacheado (custo zero), então pulamos SEM tocar a API.
            # Import tardio: budget_guard→supabase não deve carregar no import do módulo.
            if reason == "budget":
                _still_exceeded = False
                try:
                    from app.agent import budget_guard
                    _still_exceeded = budget_guard.is_exceeded()
                except Exception as exc:  # fail-open: na dúvida, tenta responder
                    logger.debug("[LLM PARK] checagem de budget falhou p/ %s: %s", conversation_id, exc)
                if _still_exceeded:
                    if now > deadline:
                        logger.warning(
                            "[LLM PARK] conv %s: deadline %s vencido com budget ainda estourado — handoff",
                            conversation_id, deadline.isoformat(),
                        )
                        await _pop(conversation_id)
                        await _handoff_parked(entry, conversation_id)
                    # dentro do prazo: mantém estacionado, sem queimar chamada de API
                    continue
            # Throttle p/ reason=quota: o tick do worker é de 30s; retentar toda vez
            # queimaria o RPM restante do dia. Só tenta de novo passados
            # LLM_PARK_RETRY_MINUTES da última tentativa falha (last_attempt_at).
            if reason == "quota":
                _last_attempt = None
                try:
                    if entry.get("last_attempt_at"):
                        _last_attempt = datetime.fromisoformat(
                            str(entry["last_attempt_at"]).replace("Z", "+00:00")
                        )
                except Exception:
                    _last_attempt = None
                if _last_attempt and (now - _last_attempt) < timedelta(minutes=_retry_minutes()):
                    continue  # ainda no throttle — próximo tick reavalia
            conversation = _fetch_conversation(conversation_id) or {
                "id": conversation_id, "stage": entry.get("stage"),
                "channel_id": entry.get("channel_id"),
            }
            await _reply_parked_turn(entry, conversation, lead)
        except LLMUnavailableError:
            if now > deadline:
                logger.warning(
                    "[LLM PARK] conv %s: deadline %s (reason=%s) vencido com LLM ainda fora — handoff",
                    conversation_id, deadline.isoformat(), reason,
                )
                await _pop(conversation_id)
                await _handoff_parked(entry, conversation_id)
                continue
            # dentro da janela: mantém estacionado p/ o próximo tick. Para quota,
            # grava a marca da tentativa falha (hset) — é ela que arma o throttle.
            if reason == "quota":
                try:
                    entry["last_attempt_at"] = now.isoformat()
                    await _get_parking_redis().hset(PARKED_KEY, conversation_id, json.dumps(entry))
                except Exception as exc:
                    logger.debug("[LLM PARK] falha ao gravar last_attempt_at p/ %s: %s", conversation_id, exc)
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

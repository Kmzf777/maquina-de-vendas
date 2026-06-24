"""Mutex distribuído por lead (Redis) para serializar o run do agente.

Race real (auditoria lead 5544991611703, 2026-06-24): a latência de 30-47s do LLM cria
um vácuo de resposta; o lead manda OUTRA mensagem achando que a IA travou; esse 2º flush
dispara um run concorrente que lê o histórico ANTES de o 1º run persistir as bolhas →
saída duplicada/atropelada (duas saudações "que legal...", pitch e handoff simultâneos).

Este lock serializa o turno POR lead_id: enquanto a RUN 1 segura `lock:agent_run:{lead_id}`,
a RUN 2 BLOQUEIA (espera com poll/timeout) até a RUN 1 liberar — aí lê o histórico já
atualizado. Garante exclusão mútua absoluta por lead, seguro entre múltiplos workers uvicorn.

Fail-open por design: se o Redis estiver indisponível, NÃO trava o atendimento — loga e
segue sem serialização (degradação graciosa é melhor do que bloquear todos os leads).
"""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# TTL do lock: teto de segurança caso o worker morra segurando a trava (nunca bloquear o
# lead pra sempre). Cobre folgado o pior turno observado (~47s de LLM+tools+pacing).
LOCK_TTL_SECONDS = 90
# Quanto a RUN 2 espera pela RUN 1 antes de desistir e seguir mesmo assim (fail-open).
# Cobre 1-2 turnos enfileirados; além disso é raro e a degradação é aceitável.
LOCK_WAIT_TIMEOUT = 80.0
LOCK_POLL_INTERVAL = 0.25
# Após uma falha de Redis, espera este tempo antes de tentar de novo — evita pagar o
# timeout de conexão a cada chamada (mantém a suíte rápida) e permite recuperação em prod.
_UNAVAILABLE_COOLDOWN = 30.0

_KEY_PREFIX = "lock:agent_run:"
# Lua: só deleta a chave se o valor for o NOSSO token — libera apenas o dono. Evita que uma
# RUN cuja trava expirou por TTL apague a trava de outra RUN que já reassumiu o lead.
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)

_client: aioredis.Redis | None = None
_unavailable_until: float = 0.0  # monotonic; >now ⇒ Redis em cooldown, fail-open imediato


def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _client


def _mark_unavailable() -> None:
    global _client, _unavailable_until
    _unavailable_until = time.monotonic() + _UNAVAILABLE_COOLDOWN
    _client = None  # força reconexão limpa na próxima tentativa pós-cooldown


@asynccontextmanager
async def lead_run_lock(lead_id: str):
    """Serializa o processamento do agente por lead. Fail-open se o Redis cair.

    Yields True se a trava foi efetivamente adquirida, False se seguiu sem trava
    (sem lead_id, Redis indisponível, ou timeout de espera).
    """
    key = f"{_KEY_PREFIX}{lead_id}"
    token = uuid.uuid4().hex
    acquired = False

    if not lead_id or time.monotonic() < _unavailable_until:
        yield False
        return

    try:
        client = _get_client()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + LOCK_WAIT_TIMEOUT
        while True:
            ok = await client.set(key, token, nx=True, ex=LOCK_TTL_SECONDS)
            if ok:
                acquired = True
                break
            if loop.time() >= deadline:
                logger.warning(
                    "[LEAD LOCK] timeout (%.0fs) esperando lock de lead=%s — seguindo sem trava",
                    LOCK_WAIT_TIMEOUT, lead_id,
                )
                break
            await asyncio.sleep(LOCK_POLL_INTERVAL)
    except Exception as exc:
        _mark_unavailable()
        logger.error(
            "[LEAD LOCK] Redis indisponível (%s) — seguindo SEM serialização (fail-open)", exc,
        )

    try:
        yield acquired
    finally:
        if acquired:
            try:
                await _get_client().eval(_RELEASE_LUA, 1, key, token)
            except Exception as exc:
                logger.warning("[LEAD LOCK] falha ao liberar lock de lead=%s: %s", lead_id, exc)

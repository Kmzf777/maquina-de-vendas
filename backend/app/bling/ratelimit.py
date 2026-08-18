"""Token-bucket distribuido para a conta Bling (3 req/s, 120.000/dia).

O limite do Bling e por CONTA, entao a contagem precisa ser central — Redis, nao
memoria de processo. Um contador por segundo (chave `bling:rl:{unix_second}`) se
auto-particiona: a chave do segundo seguinte comeca do zero sem limpeza.

FAIL-CLOSED por design. O `buffer/lead_lock.py` e fail-open porque bloquear o
atendimento e pior que duplicar um turno; aqui e o oposto — seguir sem contagem
arrisca 600 req/10s e bloqueio de IP por tempo INDETERMINADO. Chamada recusada
vai para a fila (`bling_jobs`) e e retentada.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.bling import config
from app.bling.errors import BlingDailyCapError, BlingRateLimitError
from app.config import settings

logger = logging.getLogger(__name__)

# INCR + EXPIRE atomico. EXPIRE 2s (nao 1s) da folga na virada do segundo.
_INCR_LUA = (
    "local c = redis.call('INCR', KEYS[1]) "
    "if c == 1 then redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1])) end "
    "return c"
)

_SECOND_TTL = 2
_DAY_TTL = 172_800  # 48h — cobre fuso e virada sem limpeza manual
# Quantas vezes esperamos o proximo segundo antes de desistir. 5s de espera ja e
# muito para o modal de venda; alem disso, enfileirar e melhor que segurar o request.
_MAX_WAIT_ROUNDS = 5

_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _client


def _second_key(now: float) -> str:
    return f"bling:rl:{int(now)}"


def _day_key() -> str:
    return "bling:rl:day:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _incr(key: str, ttl: int) -> int:
    return int(await _get_client().eval(_INCR_LUA, 1, key, str(ttl)))


async def acquire() -> None:
    """Reserva uma requisicao. Espera o proximo segundo se preciso.

    Levanta BlingDailyCapError (teto diario), BlingRateLimitError (Redis fora ou
    espera longa demais). Ambos sao TRANSIENT — o chamador enfileira.
    """
    for _ in range(_MAX_WAIT_ROUNDS):
        now = time.time()
        try:
            count = await _incr(_second_key(now), _SECOND_TTL)
        except Exception as exc:  # noqa: BLE001 — qualquer falha de Redis e fail-closed
            logger.warning("[BLING RL] Redis indisponivel, recusando chamada: %s", exc)
            raise BlingRateLimitError("rate limiter indisponivel (Redis)") from exc

        if count > config.REQUESTS_PER_SECOND:
            # Ja incrementamos, mas a chave morre no fim do segundo — a proxima
            # janela comeca limpa. Dorme o que falta do segundo corrente.
            await asyncio.sleep(max(0.01, 1.0 - (time.time() - int(now))))
            continue

        try:
            day = await _incr(_day_key(), _DAY_TTL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BLING RL] Redis indisponivel no contador diario: %s", exc)
            raise BlingRateLimitError("rate limiter indisponivel (Redis)") from exc

        if day > config.DAILY_SOFT_CAP:
            raise BlingDailyCapError(
                f"teto diario local atingido ({day}/{config.DAILY_SOFT_CAP})"
            )
        return

    raise BlingRateLimitError("orcamento de 3 req/s saturado apos varias tentativas")

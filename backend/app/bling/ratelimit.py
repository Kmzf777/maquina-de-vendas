"""Token-bucket distribuido para a conta Bling (3 req/s, 120.000/dia).

O limite do Bling e por CONTA, entao a contagem precisa ser central — Redis, nao
memoria de processo. Um contador por segundo (chave `bling:rl:{unix_second}`) se
auto-particiona: a chave do segundo seguinte comeca do zero sem limpeza.

FAIL-CLOSED por design. O `buffer/lead_lock.py` e fail-open porque bloquear o
atendimento e pior que duplicar um turno; aqui e o oposto — seguir sem contagem
arrisca 600 req/10s e bloqueio de IP por tempo INDETERMINADO. Chamada recusada
vai para a fila (`bling_jobs`) e e retentada.

Os dois contadores (segundo e dia) sao verificados num UNICO script Lua/eval, nao
duas chamadas sequenciais. Dois motivos:
1. Latencia do caminho feliz: um Redis lento-mas-vivo (ex.: 1,5s por comando, sem
   estourar o socket_timeout) dobraria o tempo do modal de venda com duas chamadas
   sequenciais, sem nunca cair no fail-closed — so lentidao silenciosa.
2. Atomicidade: com o script unico, a garantia "o contador diario so incrementa
   depois do de segundo passar" vem da propria atomicidade do Lua, nao da ordem
   do codigo Python. Isso tambem elimina por construcao o modo de falha "Redis
   caiu entre os dois contadores" — nao existe mais uma janela onde isso acontece.
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

# Um unico round-trip: incrementa o contador por segundo (KEYS[1]) e, so se ele
# passar, o contador diario (KEYS[2]). ARGV: [ttl_segundo, ttl_dia, limite_segundo,
# teto_diario]. Retorno {status, valor} — status 0 = ok, 1 = estourou por segundo
# (nao mexe no diario), 2 = estourou o teto diario.
_RATE_LIMIT_LUA = (
    "local sec = redis.call('INCR', KEYS[1]) "
    "if sec == 1 then redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1])) end "
    "if sec > tonumber(ARGV[3]) then return {1, sec} end "
    "local day = redis.call('INCR', KEYS[2]) "
    "if day == 1 then redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2])) end "
    "if day > tonumber(ARGV[4]) then return {2, day} end "
    "return {0, day}"
)

_SECOND_TTL = 2
_DAY_TTL = 172_800  # 48h — cobre fuso e virada sem limpeza manual
# Quantas vezes esperamos o proximo segundo antes de desistir. 5s de espera ja e
# muito para o modal de venda; alem disso, enfileirar e melhor que segurar o request.
_MAX_WAIT_ROUNDS = 5
# Apos uma falha de Redis, espera este tempo antes de tentar de novo — evita pagar o
# timeout de CONEXAO a cada chamada durante uma queda prolongada (o job de sync em
# lote pagaria ~2-4s por item sem isso). Mesmo padrao de `buffer/lead_lock.py`, mas
# aqui o cooldown so poupa o timeout: o comportamento continua fail-closed (recusa e
# enfileira), nunca vira fail-open.
_UNAVAILABLE_COOLDOWN = 30.0

_client: aioredis.Redis | None = None
_unavailable_until: float = 0.0  # monotonic; >now ⇒ Redis em cooldown, recusa imediata


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
    _client = None  # forca reconexao limpa na proxima tentativa pos-cooldown


def _second_key(now: float) -> str:
    return f"bling:rl:{int(now)}"


def _day_key() -> str:
    return "bling:rl:day:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def acquire() -> None:
    """Reserva uma requisicao. Espera o proximo segundo se preciso.

    Levanta BlingDailyCapError (teto diario), BlingRateLimitError (Redis fora,
    Redis em cooldown pos-falha, ou espera longa demais). Ambos sao TRANSIENT — o
    chamador enfileira.
    """
    for _ in range(_MAX_WAIT_ROUNDS):
        if time.monotonic() < _unavailable_until:
            # Ainda em cooldown pos-falha: recusa sem nem tentar conectar, para nao
            # pagar o timeout de conexao de novo. Fail-closed, nao fail-open.
            raise BlingRateLimitError("rate limiter em cooldown apos falha do Redis")

        now = time.time()
        try:
            status, value = await _get_client().eval(
                _RATE_LIMIT_LUA, 2,
                _second_key(now), _day_key(),
                str(_SECOND_TTL), str(_DAY_TTL),
                str(config.REQUESTS_PER_SECOND), str(config.DAILY_SOFT_CAP),
            )
        except Exception as exc:  # noqa: BLE001 — qualquer falha de Redis e fail-closed
            _mark_unavailable()
            logger.warning("[BLING RL] Redis indisponivel, recusando chamada: %s", exc)
            raise BlingRateLimitError("rate limiter indisponivel (Redis)") from exc

        status, value = int(status), int(value)

        if status == 1:
            # Ja incrementamos o contador por segundo, mas a chave morre no fim do
            # segundo — a proxima janela comeca limpa. Dorme o que falta do segundo
            # corrente. O contador diario nao foi tocado (o script para antes).
            await asyncio.sleep(max(0.01, 1.0 - (time.time() - int(now))))
            continue

        if status == 2:
            raise BlingDailyCapError(
                f"teto diario local atingido ({value}/{config.DAILY_SOFT_CAP})"
            )

        return

    raise BlingRateLimitError("orcamento de 3 req/s saturado apos varias tentativas")

"""Trava por conta para os jobs de PEDIDOS do Bling (backfill, varredura e
reconciliacao).

Os tres listam `/pedidos/vendas` e gravam em `sales` na mesma conta. Rodando em
paralelo na mesma conta, eles dividem o orcamento de 3 req/s (cada um anda na
metade da velocidade) e reimportam o mesmo pedido duas vezes. Uma trava so,
`bling:pedidos:{conta}`, serializa os tres; contas diferentes nao se bloqueiam.

FAIL-CLOSED: Redis fora => nao roda. Pular uma rodada da varredura custa
pouco (a proxima pega tudo pelo cursor); rodar sem trava pode duplicar o
backfill inteiro.

A trava tem dono (token aleatorio): so quem a pegou consegue soltar ou
estender. Sem isso, um job que demorou mais que o TTL soltaria a trava que
outro job ja tinha pegado.
"""
import logging
import secrets
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from app.bling import config
from app.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None

# Solta/estende so se o valor ainda for o token de quem pegou.
_SOLTAR_LUA = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
    "return redis.call('DEL', KEYS[1]) else return 0 end"
)
_ESTENDER_LUA = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
    "return redis.call('PEXPIRE', KEYS[1], ARGV[2]) else return 0 end"
)


class TravaOcupada(Exception):
    """Outro job de pedidos ja esta rodando nesta conta (ou o Redis caiu)."""


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True,
                                   socket_connect_timeout=2, socket_timeout=2)
    return _redis


def chave(account: str) -> str:
    return f"bling:pedidos:{config.account(account).key}"


class Trava:
    def __init__(self, account: str, ttl_segundos: int):
        self.chave = chave(account)
        self.ttl_ms = int(ttl_segundos * 1000)
        self.token = secrets.token_hex(8)

    async def pegar(self) -> None:
        try:
            ok = await _get_redis().set(self.chave, self.token, nx=True, px=self.ttl_ms)
        except Exception as exc:  # noqa: BLE001 — fail-closed
            raise TravaOcupada(f"Redis indisponivel para a trava {self.chave}: {exc}") from exc
        if not ok:
            raise TravaOcupada(f"{self.chave} ja esta em uso por outro job")

    async def estender(self) -> None:
        """Renova o TTL (o backfill chama a cada janela). Falha aqui so loga."""
        try:
            await _get_redis().eval(_ESTENDER_LUA, 1, self.chave, self.token, str(self.ttl_ms))
        except Exception:  # noqa: BLE001
            logger.warning("[BLING TRAVA] nao consegui estender %s", self.chave, exc_info=True)

    async def soltar(self) -> None:
        try:
            await _get_redis().eval(_SOLTAR_LUA, 1, self.chave, self.token)
        except Exception:  # noqa: BLE001 — o TTL solta sozinho
            logger.warning("[BLING TRAVA] nao consegui soltar %s (expira pelo TTL)",
                           self.chave, exc_info=True)


@asynccontextmanager
async def trava_pedidos(account: str, ttl_segundos: int = 3600):
    """`async with trava_pedidos(conta) as t:` — levanta TravaOcupada se nao pegou."""
    trava = Trava(account, ttl_segundos)
    await trava.pegar()
    try:
        yield trava
    finally:
        await trava.soltar()

"""OAuth 2.0 do Bling: authorization_code, refresh e storage dos tokens.

Tres decisoes que este modulo materializa:

1. `enable-jwt: 1` em TODA chamada ao /oauth/token. O token opaco esta
   descontinuado; sem o header o Bling devolve o formato antigo, que vai parar
   de funcionar.
2. Refresh SERIALIZADO por lock Redis. O Bling bloqueia o IP por 60 MINUTOS
   apos 20 chamadas ao /oauth/token em 60s — refresh concorrente entre workers
   derruba a integracao inteira.
3. Tokens no Postgres, cache no Redis. O FLUSHALL de 07/06/2026 mostrou que
   Redis nao e storage: perder o refresh_token (30 dias de validade) obriga a
   refazer o fluxo OAuth manualmente no navegador.
"""
import asyncio
import base64
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
import redis.asyncio as aioredis

from app.bling import config
from app.bling.errors import BlingAuthError, BlingNotConfigured
from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_CACHE_KEY = "bling:access_token"
_LOCK_KEY = "lock:bling_token_refresh"
_STATE_PREFIX = "bling:oauth_state:"
_LOCK_TTL = 30
_STATE_TTL = 600
# Renova quando faltar menos que isso para expirar (access_token dura 6h).
_RENEW_MARGIN_SECONDS = 300

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _redis


def _basic_auth_header() -> str:
    cid, csec = config.require_credentials()
    return "Basic " + base64.b64encode(f"{cid}:{csec}".encode()).decode()


# --------------------------------------------------------------------------
# Fluxo de autorizacao
# --------------------------------------------------------------------------
async def new_state() -> str:
    """Gera e guarda o state (anti-CSRF). TTL de 10 min."""
    state = secrets.token_urlsafe(24)
    await _get_redis().setex(_STATE_PREFIX + state, _STATE_TTL, "1")
    return state


async def consume_state(state: str) -> bool:
    """Valida e queima o state. False se invalido ou ja usado."""
    if not state:
        return False
    return bool(await _get_redis().delete(_STATE_PREFIX + state))


def authorize_url(state: str) -> str:
    cid, _ = config.require_credentials()
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": cid,
        "state": state,
    })
    return f"{config.AUTHORIZE_URL}?{params}"


async def _token_request(data: dict) -> dict:
    headers = {
        "Authorization": _basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "1.0",
        "enable-jwt": "1",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(config.TOKEN_URL, headers=headers, data=data)
    if resp.status_code != 200:
        # Nunca logar o corpo: pode conter o code ou o refresh_token.
        logger.error("[BLING AUTH] /oauth/token devolveu %s", resp.status_code)
        raise BlingAuthError(f"/oauth/token devolveu {resp.status_code}")
    return resp.json()


async def exchange_code(code: str) -> dict:
    """Troca o authorization_code pelos tokens. O code expira em 1 MINUTO."""
    payload = await _token_request({"grant_type": "authorization_code", "code": code})
    await _persist(payload)
    return payload


async def _refresh_now(refresh_token: str) -> str:
    payload = await _token_request({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })
    await _persist(payload)
    return payload["access_token"]


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
async def _persist(payload: dict) -> None:
    now = datetime.now(timezone.utc)
    expires_in = int(payload.get("expires_in") or 21600)
    row = {
        "id": "default",
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "access_expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
        "refresh_expires_at": (now + timedelta(days=30)).isoformat(),
        "scope": payload.get("scope") or "",
        "updated_at": now.isoformat(),
    }
    await asyncio.to_thread(
        lambda: get_supabase().table("bling_credentials")
        .upsert(row, on_conflict="id").execute()
    )
    logger.info("[BLING AUTH] tokens renovados; access expira em %ss", expires_in)
    await _cache_set(row["access_token"], max(60, expires_in - _RENEW_MARGIN_SECONDS))


def _stored_row() -> dict | None:
    res = (get_supabase().table("bling_credentials")
           .select("*").eq("id", "default").limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _stored_refresh_token() -> str | None:
    row = _stored_row() or {}
    return row.get("refresh_token")


async def _cache_get() -> str | None:
    try:
        return await _get_redis().get(_CACHE_KEY)
    except Exception:  # noqa: BLE001 — cache indisponivel cai para o Postgres
        return None


async def _cache_set(token: str | None, ttl: int) -> None:
    if not token:
        return
    try:
        await _get_redis().setex(_CACHE_KEY, ttl, token)
    except Exception:  # noqa: BLE001
        logger.warning("[BLING AUTH] nao foi possivel cachear o access_token")


async def _refresh_lock():
    """Lock de refresh. Devolve um context manager que entrega True se pegou."""
    client = _get_redis()
    token = secrets.token_hex(8)

    class _Ctx:
        owned = False

        async def __aenter__(self):
            for _ in range(60):  # ate ~30s esperando quem esta renovando
                if await client.set(_LOCK_KEY, token, nx=True, ex=_LOCK_TTL):
                    self.owned = True
                    return True
                await asyncio.sleep(0.5)
            return False

        async def __aexit__(self, *_a):
            if self.owned:
                # Libera so se a trava ainda e nossa (mesmo padrao do lead_lock).
                lua = ("if redis.call('get', KEYS[1]) == ARGV[1] then "
                       "return redis.call('del', KEYS[1]) else return 0 end")
                await client.eval(lua, 1, _LOCK_KEY, token)
            return False

    return _Ctx()


async def get_access_token() -> str:
    """Devolve um access_token valido, renovando se preciso (serializado)."""
    cached = await _cache_get()
    if cached:
        return cached

    ctx = await _refresh_lock()
    async with ctx as owned:
        # Quem esperou o lock rele o cache: o dono anterior ja renovou.
        cached = await _cache_get()
        if cached:
            return cached
        if not owned:
            raise BlingAuthError("nao foi possivel obter o lock de refresh")
        refresh_token = await asyncio.to_thread(_stored_refresh_token)
        if not refresh_token:
            raise BlingNotConfigured(
                "nenhum refresh_token salvo — refaca o fluxo OAuth em /config"
            )
        return await _refresh_now(refresh_token)


async def invalidate_cache() -> None:
    """Descarta o access_token cacheado (usado no retry de 401)."""
    try:
        await _get_redis().delete(_CACHE_KEY)
    except Exception:  # noqa: BLE001
        pass


async def status() -> dict:
    """Resumo para /api/bling/status: conectado, expiracoes, escopos."""
    row = await asyncio.to_thread(_stored_row) or {}
    return {
        # Fonte unica da regra "o que conta como configurado" (config.is_configured).
        # Repetir a condicao aqui faria os dois lados divergirem no dia em que a
        # integracao passar a exigir tambem o redirect_uri.
        "configured": config.is_configured(),
        "connected": bool(row.get("refresh_token")),
        "access_expires_at": row.get("access_expires_at"),
        "refresh_expires_at": row.get("refresh_expires_at"),
        "scope": row.get("scope"),
    }

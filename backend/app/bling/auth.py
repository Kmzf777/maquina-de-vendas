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
from app.bling.errors import BlingAuthError, BlingNotConfigured, BlingServerError
from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_STATE_PREFIX = "bling:oauth_state:"
_LOCK_TTL = 30
_STATE_TTL = 600
# Renova quando faltar menos que isso para expirar (access_token dura 6h).
_RENEW_MARGIN_SECONDS = 300
# upsert do _persist: poucas tentativas, delay curto. Perder o refresh_token
# rotacionado aqui e catastrofico — o Bling ja invalidou o antigo do lado dele —
# entao vale insistir mesmo em erros que normalmente nao seriam retentados.
_PERSIST_RETRY_ATTEMPTS = 3
_PERSIST_RETRY_DELAY_SECONDS = 0.3

_redis: aioredis.Redis | None = None


# As chaves sao POR CONTA. Uma chave global entregaria o access_token da conta 1
# para as chamadas da conta 2 — silenciosamente, porque o token e valido, so que
# do CNPJ errado.
def _cache_key(account: str) -> str:
    return f"bling:{account}:access_token"


def _lock_key(account: str) -> str:
    return f"lock:bling_token_refresh:{account}"


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _redis


def _basic_auth_header(account: str) -> str:
    conta = config.account(account)
    # `conta.configured` e a fonte unica da regra "o que conta como configurado"
    # (Task 1). Repetir `client_id and client_secret` aqui criaria uma segunda
    # versao da mesma regra, que diverge no dia em que a integracao passar a
    # exigir tambem o redirect_uri.
    if not conta.configured:
        raise BlingNotConfigured(
            f"conta {account!r}: BLING_CLIENT_ID e BLING_CLIENT_SECRET "
            "precisam estar configurados"
        )
    return "Basic " + base64.b64encode(
        f"{conta.client_id}:{conta.client_secret}".encode()).decode()


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


async def _token_request(data: dict, account: str) -> dict:
    headers = {
        "Authorization": _basic_auth_header(account),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "1.0",
        "enable-jwt": "1",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(config.TOKEN_URL, headers=headers, data=data)
    if resp.status_code != 200:
        # Nunca logar o corpo: pode conter o code ou o refresh_token.
        logger.error("[BLING AUTH] conta %s: /oauth/token devolveu %s", account, resp.status_code)
        raise BlingAuthError(f"/oauth/token devolveu {resp.status_code}")
    return resp.json()


async def exchange_code(code: str, account: str = config.DEFAULT_ACCOUNT) -> dict:
    """Troca o authorization_code pelos tokens. O code expira em 1 MINUTO."""
    payload = await _token_request(
        {"grant_type": "authorization_code", "code": code}, account)
    await _persist(payload, account)
    return payload


async def _refresh_now(refresh_token: str, account: str) -> str:
    payload = await _token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}, account)
    await _persist(payload, account)
    return payload["access_token"]


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
async def _persist(payload: dict, account: str) -> None:
    now = datetime.now(timezone.utc)
    expires_in = int(payload.get("expires_in") or 21600)
    row = {
        "id": account,
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "access_expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
        "refresh_expires_at": (now + timedelta(days=30)).isoformat(),
        "scope": payload.get("scope") or "",
        "updated_at": now.isoformat(),
    }

    def _upsert():
        return (get_supabase().table("bling_credentials")
                .upsert(row, on_conflict="id").execute())

    ultimo_erro: Exception | None = None
    for tentativa in range(1, _PERSIST_RETRY_ATTEMPTS + 1):
        try:
            await asyncio.to_thread(_upsert)
            ultimo_erro = None
            break
        except Exception as exc:  # noqa: BLE001 — qualquer falha aqui e catastrofica
            ultimo_erro = exc
            if tentativa < _PERSIST_RETRY_ATTEMPTS:
                await asyncio.sleep(_PERSIST_RETRY_DELAY_SECONDS)

    if ultimo_erro is not None:
        # Nesse ponto o Bling ja rotacionou o refresh_token do lado dele — se nao
        # persistir agora, o token antigo que ainda esta no Postgres ja foi
        # invalidado la, e a proxima tentativa toma 401 sem nenhuma pista do
        # motivo real. NUNCA logar o payload/token aqui — so o TIPO do erro, para
        # nao vazar segredo caso a excecao da lib carregue o corpo da resposta na
        # propria mensagem.
        logger.critical(
            "[BLING AUTH] conta %s: refresh_token rotacionado no Bling mas NAO "
            "persistido no Postgres apos %d tentativas (%s) — reautorizacao manual "
            "necessaria",
            account, _PERSIST_RETRY_ATTEMPTS, type(ultimo_erro).__name__,
        )
        raise ultimo_erro

    logger.info("[BLING AUTH] tokens renovados; access expira em %ss", expires_in)
    await _cache_set(row["access_token"], max(60, expires_in - _RENEW_MARGIN_SECONDS), account)


def _stored_row(account: str) -> dict | None:
    res = (get_supabase().table("bling_credentials")
           .select("*").eq("id", account).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _seconds_until(iso_ts: str | None) -> float:
    """Segundos ate o timestamp ISO 8601 informado. Ausente/invalido conta como
    ja vencido (-1), forcando o caminho de renovacao em vez de usar lixo."""
    if not iso_ts:
        return -1.0
    try:
        return (datetime.fromisoformat(iso_ts) - datetime.now(timezone.utc)).total_seconds()
    except ValueError:
        return -1.0


async def _cache_get(account: str) -> str | None:
    try:
        return await _get_redis().get(_cache_key(account))
    except Exception:  # noqa: BLE001 — cache indisponivel cai para o Postgres
        return None


async def _cache_set(token: str | None, ttl: int, account: str) -> None:
    if not token:
        return
    try:
        await _get_redis().setex(_cache_key(account), ttl, token)
    except Exception:  # noqa: BLE001
        logger.warning("[BLING AUTH] nao foi possivel cachear o access_token "
                       "da conta %s", account)


async def _refresh_lock(account: str):
    """Lock de refresh. Devolve um context manager que entrega True se pegou."""
    client = _get_redis()
    token = secrets.token_hex(8)
    chave = _lock_key(account)

    class _Ctx:
        owned = False

        async def __aenter__(self):
            # 70x0.5s = ~35s > _LOCK_TTL (30s): da folga para pelo menos uma
            # tentativa depois que o TTL do lock anterior expirar sozinho — se a
            # janela de espera fosse igual ao TTL, quem espera podia desistir no
            # exato instante em que a chave morreria, sem nunca tentar de novo.
            for _ in range(70):
                if await client.set(chave, token, nx=True, ex=_LOCK_TTL):
                    self.owned = True
                    return True
                await asyncio.sleep(0.5)
            return False

        async def __aexit__(self, *_a):
            if self.owned:
                # Libera so se a trava ainda e nossa (mesmo padrao do lead_lock).
                lua = ("if redis.call('get', KEYS[1]) == ARGV[1] then "
                       "return redis.call('del', KEYS[1]) else return 0 end")
                await client.eval(lua, 1, chave, token)
            return False

    return _Ctx()


async def get_access_token(account: str = config.DEFAULT_ACCOUNT) -> str:
    """Devolve um access_token valido, renovando se preciso (serializado)."""
    cached = await _cache_get(account)
    if cached:
        return cached

    ctx = await _refresh_lock(account)
    async with ctx as owned:
        # Quem esperou o lock rele o cache: o dono anterior ja renovou.
        cached = await _cache_get(account)
        if cached:
            return cached
        if not owned:
            # Contencao momentanea (outro processo esta renovando agora), NAO
            # credencial morta — precisa ser TRANSIENT para o modal de venda
            # enfileirar e tentar de novo, em vez de mandar o vendedor refazer
            # o fluxo OAuth em /config por causa de um timeout de lock.
            raise BlingServerError(
                f"conta {account}: nao foi possivel obter o lock de refresh (timeout)")

        # Rele o Postgres INTEIRO, nao so o refresh_token: um FLUSHALL no Redis
        # (incidente 07/06/2026) zera o cache mas NAO o Postgres. Sem reler o
        # access_token persistido aqui, cache vazio + chamadas sequenciais viram
        # chamadas reais ao /oauth/token mesmo com um token ainda valido por
        # horas guardado — e 20 chamadas em 60s bloqueiam o IP por 60 minutos.
        row = await asyncio.to_thread(_stored_row, account) or {}
        access_token = row.get("access_token")
        restante = _seconds_until(row.get("access_expires_at"))
        if access_token and restante > _RENEW_MARGIN_SECONDS:
            await _cache_set(access_token, max(60, int(restante) - _RENEW_MARGIN_SECONDS), account)
            return access_token

        refresh_token = row.get("refresh_token")
        if not refresh_token:
            raise BlingNotConfigured(
                f"conta {account}: nenhum refresh_token salvo — "
                "refaca o fluxo OAuth em /config"
            )
        return await _refresh_now(refresh_token, account)


async def invalidate_cache(account: str = config.DEFAULT_ACCOUNT) -> None:
    """Descarta o access_token cacheado (usado no retry de 401)."""
    try:
        await _get_redis().delete(_cache_key(account))
    except Exception:  # noqa: BLE001
        pass


async def status() -> dict:
    """Resumo para /api/bling/status: conectado, expiracoes, escopos."""
    row = await asyncio.to_thread(_stored_row, config.DEFAULT_ACCOUNT) or {}
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

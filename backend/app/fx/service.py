"""Cotação USD→BRL para o dashboard.

O painel mistura valores nativos em dólar (custo de token do Gemini) e em real
(valor de venda do CAPI), e precisa exibir os dois. Este módulo é o dono único
da taxa.

Contrato: `get_usd_brl()` NUNCA levanta. A cadeia de resolução degrada em vez de
falhar, porque um KPI aproximado e rotulado como tal é melhor que um card vazio:

    cache (6h) → API → último-bom (stale) → fallback do env (stale)

Quem consome decide o que fazer com `stale` — a UI escreve "(aprox.)".
Mesma disciplina do `app/agent/catalog.py`, que serve preço velho quando a fonte cai.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

FX_CACHE_KEY = "fx:usd_brl"
FX_LAST_GOOD_KEY = "fx:usd_brl:last"
FX_COOLDOWN_KEY = "fx:usd_brl:cooldown"
FX_CACHE_TTL_SECONDS = 6 * 60 * 60

# Cooldown pós-falha. Sem isto, um cache vazio faz CADA carga do painel (2 componentes,
# polling de 60s) bater nas fontes externas — foi exatamente assim que o IP do VPS
# estourou a cota da AwesomeAPI (429 QuotaExceeded, 13/07). Quando todas as fontes
# falham, paramos de tentar por um tempo e servimos o degradado.
FX_COOLDOWN_SECONDS = 15 * 60

_ER_API_URL = "https://open.er-api.com/v6/latest/USD"
_AWESOME_URL = "https://economia.awesomeapi.com.br/json/last/USD-BRL"
_HTTP_TIMEOUT_SECONDS = 5.0

# Piso de último recurso quando nem FX_USD_BRL_FALLBACK existe (dev, homolog, deploy
# novo). Colhido da AwesomeAPI em 13/07/2026. Envelhece: em produção o valor autoritativo
# é o da env, e todo uso deste caminho vai marcado como stale ("aprox.") na UI.
DEFAULT_FALLBACK_RATE = 5.1488

# Faixa de sanidade. Uma cotação fora disso é lixo da fonte (0, negativo, campo
# trocado) e não pode virar valor financeiro no painel.
_MIN_PLAUSIBLE_RATE = 1.0
_MAX_PLAUSIBLE_RATE = 20.0


@dataclass(frozen=True)
class FxRate:
    rate: float
    date: str
    stale: bool
    source: str


_redis_client: "aioredis.Redis | None" = None


def _get_redis() -> "aioredis.Redis":
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


def _fallback_rate() -> float:
    raw = os.environ.get("FX_USD_BRL_FALLBACK", "").strip()
    if not raw:
        return DEFAULT_FALLBACK_RATE
    try:
        value = float(raw)
    except ValueError:
        logger.warning("FX_USD_BRL_FALLBACK inválido (%r); usando default", raw)
        return DEFAULT_FALLBACK_RATE
    return value if _is_plausible(value) else DEFAULT_FALLBACK_RATE


def _is_plausible(rate: float) -> bool:
    return _MIN_PLAUSIBLE_RATE < rate < _MAX_PLAUSIBLE_RATE


async def _fetch_er_api(client: httpx.AsyncClient) -> tuple[float, str]:
    resp = await client.get(_ER_API_URL)
    resp.raise_for_status()
    payload = resp.json()
    rate = float(payload["rates"]["BRL"])
    date = str(payload.get("time_last_update_utc", ""))
    return rate, _parse_date(date)


async def _fetch_awesome(client: httpx.AsyncClient) -> tuple[float, str]:
    resp = await client.get(_AWESOME_URL)
    resp.raise_for_status()
    payload = resp.json()["USDBRL"]
    rate = float(payload["bid"])
    return rate, str(payload.get("create_date", ""))[:10] or _today()


# Ordem importa: a AwesomeAPI limita por IP no tier gratuito e o IP do VPS de produção
# já está com a cota estourada (429 QuotaExceeded). O er-api responde de lá, então é o
# primário; a AwesomeAPI fica como segunda opinião para quem tiver cota.
_SOURCES: list[tuple[str, "object"]] = [
    ("er-api", _fetch_er_api),
    ("awesomeapi", _fetch_awesome),
]


async def _fetch_remote() -> tuple[float, str, str]:
    """Primeira fonte que responder com cotação plausível vence. Levanta se nenhuma responder."""
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        for name, fetch in _SOURCES:
            try:
                rate, date = await fetch(client)  # type: ignore[operator]
                if not _is_plausible(rate):
                    raise ValueError(f"cotação implausível: {rate}")
                return rate, date, name
            except Exception as exc:
                errors.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors) or "nenhuma fonte de câmbio configurada")


def _parse_date(raw: str) -> str:
    """'Mon, 13 Jul 2026 00:02:31 +0000' → '2026-07-13'. Formato desconhecido → hoje."""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return _today()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _read_key(key: str) -> tuple[float, str] | None:
    try:
        raw = await _get_redis().get(key)
    except Exception as exc:  # Redis fora não pode derrubar o painel.
        logger.warning("fx: leitura de %s falhou: %s", key, exc)
        return None
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        rate = float(parsed["rate"])
    except (ValueError, KeyError, TypeError):
        logger.warning("fx: conteúdo corrompido em %s", key)
        return None
    if not _is_plausible(rate):
        return None
    return rate, str(parsed.get("date") or _today())


async def _write(rate: float, date: str) -> None:
    payload = json.dumps({"rate": rate, "date": date})
    redis = _get_redis()
    try:
        # Cache com TTL (a cotação do dia) + último-bom sem TTL (a rede de segurança
        # que sobrevive à expiração e é o que salva o painel quando a API cai).
        await redis.set(FX_CACHE_KEY, payload, ex=FX_CACHE_TTL_SECONDS)
        await redis.set(FX_LAST_GOOD_KEY, payload)
    except Exception as exc:
        logger.warning("fx: gravação do cache falhou: %s", exc)


async def _degraded() -> FxRate:
    last_good = await _read_key(FX_LAST_GOOD_KEY)
    if last_good is not None:
        return FxRate(rate=last_good[0], date=last_good[1], stale=True, source="stale")
    return FxRate(rate=_fallback_rate(), date=_today(), stale=True, source="fallback")


async def _in_cooldown() -> bool:
    try:
        return bool(await _get_redis().get(FX_COOLDOWN_KEY))
    except Exception:
        return False


async def get_usd_brl() -> FxRate:
    cached = await _read_key(FX_CACHE_KEY)
    if cached is not None:
        return FxRate(rate=cached[0], date=cached[1], stale=False, source="cache")

    # Falhou há pouco: não bate nas fontes de novo. Servir degradado é barato;
    # martelar um terceiro que já respondeu 429 é o que estoura a cota de vez.
    if await _in_cooldown():
        return await _degraded()

    try:
        rate, date, source = await _fetch_remote()
    except Exception as exc:
        logger.warning("fx: nenhuma fonte respondeu (%s); degradando por %ds", exc, FX_COOLDOWN_SECONDS)
        try:
            await _get_redis().set(FX_COOLDOWN_KEY, "1", ex=FX_COOLDOWN_SECONDS)
        except Exception:
            pass  # Redis fora: sem cooldown, mas o painel ainda responde.
        return await _degraded()

    await _write(rate, date)
    return FxRate(rate=rate, date=date, stale=False, source=source)

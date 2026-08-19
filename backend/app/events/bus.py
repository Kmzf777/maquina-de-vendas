"""Barramento de eventos wake-up sobre Redis Streams.

Eventos NÃO carregam estado de trabalho: apenas acordam o loop do domínio no
worker (app/worker/runtime.py). A fonte de verdade é o banco (varredura de
due/pending + claim atômico); perder um evento custa no máximo um tick de
fallback. Por isso a emissão é fail-open: Redis fora NUNCA falha a criação
do trabalho.
"""
import json
import logging

import redis

from app.config import settings

logger = logging.getLogger(__name__)

DOMAINS = ("broadcasts", "followups", "automation", "bling-webhook")
_MAXLEN = 1024

_client: redis.Redis | None = None


def stream_key(domain: str) -> str:
    return f"events:{domain}"


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _client


def emit_event(domain: str, payload: dict | None = None) -> bool:
    """XADD no stream do domínio. Retorna False (e loga) em qualquer falha."""
    if domain not in DOMAINS:
        logger.warning("[EVENTS] domínio desconhecido: %s", domain)
        return False
    fields = {"payload": json.dumps(payload or {}, default=str)}
    try:
        _get_client().xadd(stream_key(domain), fields, maxlen=_MAXLEN, approximate=True)
        return True
    except Exception as exc:
        logger.warning("[EVENTS] emit %s falhou (fail-open): %s", domain, exc)
        return False

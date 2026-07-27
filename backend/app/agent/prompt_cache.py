"""Cache explícito de prefixo de prompt na Gemini API (context caching).

Contexto (incidente 19-27/07/2026): a Valéria ficou muda por 5 dias após o projeto
estourar o teto de gasto MENSAL da Gemini API. O turno do agente carrega ~36K tokens de
entrada para produzir ~47 tokens de saída (razão ~767:1) — o bloco estático
(BASE_STATIC + roteiro do stage + catálogo) é ~79% disso e é reenviado inteiro a cada
turno. O implicit caching (ligado por default nos modelos 2.5+) já descontava parte
disso, mas de forma NÃO determinística: hit medido entre 10,0% e 31,9% contra um teto
teórico de ~78% (ver docs/superpowers/specs/2026-07-27-gemini-context-caching-design.md).

Este módulo troca essa loteria por um cache EXPLÍCITO, cujo desconto é contratual
(90% no input que bate o cache, tarifário 2.5 Flash: US$0,30 -> US$0,03 por 1M).

O QUE ESTE MÓDULO NÃO RESOLVE (registrado para não induzir a erro): tokens em cache
CONTINUAM contando para o rate limit de TPM — a documentação do Google é explícita
("token limits include cached tokens"). Portanto o cache reduz CUSTO, nunca o
429 RESOURCE_EXHAUSTED por taxa. Quem resolve o 429 é subir o tier do projeto ou
reduzir o número absoluto de tokens.

ECONOMIA DO TTL (por que lazy + expiração natural, e não um cache perene): o storage
custa US$1,00 por 1M tokens por HORA. Um cache de ~20K tokens vivo 24/7 custa
~US$14,70/mês e a economia no volume atual é ~US$11,87/mês — ou seja, cache perene dá
PREJUÍZO. Criando sob demanda e deixando expirar fora do horário de tráfego (medido:
fins de semana têm tráfego de IA ~zero), o storage cai para ~US$4,49/mês e o resultado
fica positivo. Por isso: nunca criar preventivamente, nunca renovar sem uso.

FAIL-OPEN ABSOLUTO: qualquer falha aqui devolve None e o chamador segue pelo caminho
normal (system_instruction inteiro no request). Um turno da Valéria JAMAIS pode cair
por causa de cache — mesmo princípio já adotado em catalog.get_products_by_funnel.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time

from google.genai import types

logger = logging.getLogger(__name__)

# Índice local {chave: (nome_do_cache_no_google, expira_em_monotonic)}.
# O Google é a fonte de verdade; isto é só um atalho para não recriar a cada turno.
# Processos/réplicas distintos mantêm índices distintos e podem criar caches
# separados para o mesmo prefixo — desperdício aceitável (o TTL os recolhe) e
# preferível a introduzir dependência de Redis no caminho crítico do turno.
_index: dict[str, tuple[str, float]] = {}

# Piso de segurança: a API rejeita cache explícito abaixo de 2.048 tokens no 2.5 Flash.
# 8.192 chars ~ 2.048 tokens (~4 chars/token em pt-BR). Abaixo disso nem tentamos.
_MIN_CHARS_DEFAULT = 8192


def cache_enabled() -> bool:
    """GEMINI_EXPLICIT_CACHE=on liga o cache explícito. Default OFF.

    Nasce desligado porque há um risco não documentado: o Google não documenta se
    `tools` podem acompanhar `cached_content` no mesmo request, e o agente SEMPRE usa
    tools. Validar em dev antes de ligar em produção (ver plano, Passo 2.5).
    """
    return os.environ.get("GEMINI_EXPLICIT_CACHE", "off").strip().lower() == "on"


def _ttl_seconds() -> int:
    try:
        return int(os.environ.get("GEMINI_CACHE_TTL_SECONDS", "3600"))
    except ValueError:
        return 3600


def _min_chars() -> int:
    try:
        return int(os.environ.get("GEMINI_CACHE_MIN_CHARS", str(_MIN_CHARS_DEFAULT)))
    except ValueError:
        return _MIN_CHARS_DEFAULT


def cache_key(model: str, static_prefix: str) -> str:
    """Chave estável do par (modelo, prefixo). Um único byte diferente => outra chave.

    O \\x00 separa os campos para que ("ab", "c") e ("a", "bc") não colidam.
    """
    raw = f"{model}\x00{static_prefix}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _get_fresh(key: str) -> str | None:
    """Entrada ainda válida do índice, ou None (removendo a vencida)."""
    entry = _index.get(key)
    if not entry:
        return None
    name, expires_at = entry
    if time.monotonic() >= expires_at:
        _index.pop(key, None)
        return None
    return name


def invalidate(model: str, static_prefix: str) -> None:
    """Remove a entrada do índice local (não apaga no Google — o TTL cuida disso).

    Usado quando o request falha citando o cache: ele pode ter expirado no servidor
    entre a nossa leitura do índice e a chamada.
    """
    _index.pop(cache_key(model, static_prefix), None)


def invalidate_all() -> None:
    """Zera o índice local. Existe para os testes e para recuperação manual."""
    _index.clear()


async def get_or_create(model: str, static_prefix: str) -> str | None:
    """Nome do cache explícito para este prefixo, criando-o se necessário.

    Devolve None — e o chamador segue sem cache — quando: a flag está desligada, o
    prefixo é curto demais para a API aceitar, ou QUALQUER erro acontece.
    Nunca levanta.
    """
    if not cache_enabled():
        return None
    if not static_prefix or len(static_prefix) < _min_chars():
        return None

    key = cache_key(model, static_prefix)
    existing = _get_fresh(key)
    if existing:
        return existing

    ttl = _ttl_seconds()
    try:
        # Import tardio: mantém este módulo importável (e testável) sem GEMINI_API_KEY.
        from app.agent.gemini_client import get_genai_client

        cache = await get_genai_client().aio.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                display_name=f"valeria-prefix-{key}",
                system_instruction=static_prefix,
                ttl=f"{ttl}s",
            ),
        )
    except Exception as exc:  # noqa: BLE001 — fail-open é o contrato deste módulo
        logger.warning(
            "[PROMPT CACHE] falha ao criar cache p/ %s (key=%s) — seguindo sem cache: %s",
            model, key, exc,
        )
        return None

    name = getattr(cache, "name", None)
    if not name:
        logger.warning("[PROMPT CACHE] criacao devolveu cache sem name (key=%s)", key)
        return None

    # Expira o índice ANTES do Google (margem de 60s) para nunca oferecer um nome que
    # já morreu do outro lado.
    _index[key] = (name, time.monotonic() + max(ttl - 60, 60))
    logger.info(
        "[PROMPT CACHE] cache criado key=%s name=%s ttl=%ss chars=%d",
        key, name, ttl, len(static_prefix),
    )
    return name

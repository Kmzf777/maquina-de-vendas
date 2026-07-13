"""Serviço de câmbio USD→BRL do dashboard (app/fx/service.py).

O painel financeiro NUNCA pode ficar sem número: a cadeia é
cache → API → último-bom (stale) → fallback do env (stale). Nenhum degrau
levanta exceção para o chamador; o que muda é a flag `stale`, que a UI usa
para dizer "aprox.".
"""

import json

import pytest

from app.fx import service as fx


class FakeRedis:
    """Redis em memória com controle de falha, no espírito dos fakes do repo."""

    def __init__(self, initial: dict[str, str] | None = None, down: bool = False):
        self.store: dict[str, str] = dict(initial or {})
        self.down = down

    async def get(self, key: str):
        if self.down:
            raise ConnectionError("redis down")
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        if self.down:
            raise ConnectionError("redis down")
        self.store[key] = value


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("FX_USD_BRL_FALLBACK", raising=False)
    yield


def _cached(rate: float, date: str = "2026-07-13") -> str:
    return json.dumps({"rate": rate, "date": date})


@pytest.mark.asyncio
async def test_cache_hit_nao_chama_a_api(monkeypatch):
    redis = FakeRedis({fx.FX_CACHE_KEY: _cached(5.42)})
    monkeypatch.setattr(fx, "_get_redis", lambda: redis)

    async def _boom(*_a, **_kw):
        raise AssertionError("não deveria bater na API com cache quente")

    monkeypatch.setattr(fx, "_fetch_remote", _boom)

    result = await fx.get_usd_brl()

    assert result.rate == 5.42
    assert result.stale is False
    assert result.source == "cache"


@pytest.mark.asyncio
async def test_miss_busca_api_e_grava_cache(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(fx, "_get_redis", lambda: redis)

    async def _fake_fetch():
        return 5.61, "2026-07-13"

    monkeypatch.setattr(fx, "_fetch_remote", _fake_fetch)

    result = await fx.get_usd_brl()

    assert result.rate == 5.61
    assert result.stale is False
    assert result.source == "awesomeapi"
    # Grava tanto o cache com TTL quanto o último-bom sem TTL (rede de segurança).
    assert json.loads(redis.store[fx.FX_CACHE_KEY])["rate"] == 5.61
    assert json.loads(redis.store[fx.FX_LAST_GOOD_KEY])["rate"] == 5.61


@pytest.mark.asyncio
async def test_api_fora_serve_ultimo_bom_marcado_stale(monkeypatch):
    redis = FakeRedis({fx.FX_LAST_GOOD_KEY: _cached(5.38, "2026-07-11")})
    monkeypatch.setattr(fx, "_get_redis", lambda: redis)

    async def _fetch_falha():
        raise RuntimeError("awesomeapi 503")

    monkeypatch.setattr(fx, "_fetch_remote", _fetch_falha)

    result = await fx.get_usd_brl()

    assert result.rate == 5.38
    assert result.date == "2026-07-11"
    assert result.stale is True
    assert result.source == "stale"


@pytest.mark.asyncio
async def test_sem_cache_nem_ultimo_bom_cai_no_fallback_do_env(monkeypatch):
    monkeypatch.setenv("FX_USD_BRL_FALLBACK", "5.75")
    monkeypatch.setattr(fx, "_get_redis", lambda: FakeRedis())

    async def _fetch_falha():
        raise RuntimeError("sem rede")

    monkeypatch.setattr(fx, "_fetch_remote", _fetch_falha)

    result = await fx.get_usd_brl()

    assert result.rate == 5.75
    assert result.stale is True
    assert result.source == "fallback"


@pytest.mark.asyncio
async def test_redis_fora_nao_derruba_o_painel(monkeypatch):
    """Redis indisponível ainda deve render um número (via API), não uma exceção."""
    monkeypatch.setattr(fx, "_get_redis", lambda: FakeRedis(down=True))

    async def _fake_fetch():
        return 5.5, "2026-07-13"

    monkeypatch.setattr(fx, "_fetch_remote", _fake_fetch)

    result = await fx.get_usd_brl()

    assert result.rate == 5.5
    assert result.source == "awesomeapi"


@pytest.mark.asyncio
async def test_taxa_absurda_da_api_e_rejeitada(monkeypatch):
    """Guarda de sanidade: 0, negativo ou fora de faixa não vira KPI financeiro."""
    monkeypatch.setattr(fx, "_get_redis", lambda: FakeRedis())

    async def _fetch_lixo():
        return 0.0, "2026-07-13"

    monkeypatch.setattr(fx, "_fetch_remote", _fetch_lixo)

    result = await fx.get_usd_brl()

    assert result.source == "fallback"
    assert result.stale is True
    assert result.rate == fx.DEFAULT_FALLBACK_RATE

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
        return 5.61, "2026-07-13", "er-api"

    monkeypatch.setattr(fx, "_fetch_remote", _fake_fetch)

    result = await fx.get_usd_brl()

    assert result.rate == 5.61
    assert result.stale is False
    assert result.source == "er-api"
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
        return 5.5, "2026-07-13", "er-api"

    monkeypatch.setattr(fx, "_fetch_remote", _fake_fetch)

    result = await fx.get_usd_brl()

    assert result.rate == 5.5
    assert result.source == "er-api"


@pytest.mark.asyncio
async def test_taxa_absurda_da_api_e_rejeitada(monkeypatch):
    """Guarda de sanidade: 0, negativo ou fora de faixa não vira KPI financeiro."""
    monkeypatch.setattr(fx, "_get_redis", lambda: FakeRedis())

    async def _fetch_lixo():
        raise ValueError("cotação implausível: 0.0")

    monkeypatch.setattr(fx, "_fetch_remote", _fetch_lixo)

    result = await fx.get_usd_brl()

    assert result.source == "fallback"
    assert result.stale is True
    assert result.rate == fx.DEFAULT_FALLBACK_RATE


# --- Cooldown e multi-fonte (regressão do 429 QuotaExceeded em prod, 13/07) -------


@pytest.mark.asyncio
async def test_cooldown_impede_martelar_a_fonte_apos_falha(monkeypatch):
    """Com cooldown ativo, NENHUMA chamada externa acontece — só o degradado."""
    redis = FakeRedis({fx.FX_COOLDOWN_KEY: "1"})
    monkeypatch.setattr(fx, "_get_redis", lambda: redis)

    async def _boom():
        raise AssertionError("cooldown ativo não pode bater na fonte externa")

    monkeypatch.setattr(fx, "_fetch_remote", _boom)

    result = await fx.get_usd_brl()

    assert result.stale is True
    assert result.source == "fallback"


@pytest.mark.asyncio
async def test_falha_total_arma_o_cooldown(monkeypatch):
    """A 1ª falha precisa armar o cooldown, senão cada carga do painel tenta de novo."""
    redis = FakeRedis()
    monkeypatch.setattr(fx, "_get_redis", lambda: redis)

    async def _falha():
        raise RuntimeError("er-api: timeout; awesomeapi: 429")

    monkeypatch.setattr(fx, "_fetch_remote", _falha)

    await fx.get_usd_brl()

    assert redis.store.get(fx.FX_COOLDOWN_KEY) == "1"


@pytest.mark.asyncio
async def test_fonte_primaria_fora_cai_na_secundaria(monkeypatch):
    """_fetch_remote percorre as fontes: a 1ª que responder plausível vence."""

    async def _er_api_fora(_client):
        raise RuntimeError("503")

    async def _awesome_ok(_client):
        return 5.20, "2026-07-13"

    monkeypatch.setattr(fx, "_SOURCES", [("er-api", _er_api_fora), ("awesomeapi", _awesome_ok)])

    rate, _date, source = await fx._fetch_remote()

    assert rate == 5.20
    assert source == "awesomeapi"


@pytest.mark.asyncio
async def test_cotacao_implausivel_nao_encerra_a_busca(monkeypatch):
    """Uma fonte devolvendo lixo (0) não pode virar KPI nem abortar as outras fontes."""

    async def _lixo(_client):
        return 0.0, "2026-07-13"

    async def _boa(_client):
        return 5.15, "2026-07-13"

    monkeypatch.setattr(fx, "_SOURCES", [("er-api", _lixo), ("awesomeapi", _boa)])

    rate, _date, source = await fx._fetch_remote()

    assert rate == 5.15
    assert source == "awesomeapi"


def test_parse_date_do_formato_rfc_do_er_api():
    assert fx._parse_date("Mon, 13 Jul 2026 00:02:31 +0000") == "2026-07-13"
    assert fx._parse_date("2026-07-13") == "2026-07-13"
    assert fx._parse_date("formato marciano") == fx._today()

import asyncio

import pytest

import app.bling.ratelimit as rl
from app.bling.errors import BlingDailyCapError, BlingRateLimitError


class FakeRedis:
    """Redis em memoria com a semantica de INCR/EXPIRE que o script Lua usa."""

    def __init__(self, fail: bool = False):
        self.counts: dict[str, int] = {}
        self.fail = fail

    async def eval(self, script, numkeys, key, *args):
        if self.fail:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Nao dorme de verdade — so registra que dormiu."""
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(rl.asyncio, "sleep", fake_sleep)
    return slept


def test_tres_chamadas_no_mesmo_segundo_passam(monkeypatch, _no_sleep):
    fake = FakeRedis()
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    async def run():
        for _ in range(3):
            await rl.acquire()

    asyncio.run(run())
    assert _no_sleep == [], "nao deveria esperar dentro do orcamento de 3 req/s"


def test_quarta_chamada_no_mesmo_segundo_espera(monkeypatch, _no_sleep):
    fake = FakeRedis()
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    # Primeiro o relogio fica parado (forca o estouro), depois avanca 1s.
    ticks = iter([1_000_000.0] * 5 + [1_000_001.0] * 5)
    monkeypatch.setattr(rl.time, "time", lambda: next(ticks))

    async def run():
        for _ in range(4):
            await rl.acquire()

    asyncio.run(run())
    assert _no_sleep, "a 4a chamada no mesmo segundo tinha que esperar o proximo segundo"


def test_teto_diario_recusa(monkeypatch, _no_sleep):
    fake = FakeRedis()
    fake.counts[rl._day_key()] = rl.config.DAILY_SOFT_CAP
    monkeypatch.setattr(rl, "_get_client", lambda: fake)
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    with pytest.raises(BlingDailyCapError):
        asyncio.run(rl.acquire())


def test_redis_fora_do_ar_e_fail_closed(monkeypatch, _no_sleep):
    """Ao contrario do lead_lock (fail-open), aqui seguir sem contagem arrisca
    bloqueio de IP por tempo indeterminado. Melhor recusar e enfileirar."""
    monkeypatch.setattr(rl, "_get_client", lambda: FakeRedis(fail=True))
    monkeypatch.setattr(rl.time, "time", lambda: 1_000_000.0)

    with pytest.raises(BlingRateLimitError):
        asyncio.run(rl.acquire())

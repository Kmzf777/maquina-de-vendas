"""Mutex distribuído por lead — auditoria lead 5544991611703 (race condition), 2026-06-24.

Garante que dois runs concorrentes do MESMO lead são serializados: a RUN 2 espera a RUN 1
liberar o lock antes de prosseguir. E que, sem Redis, o lock é fail-open (não trava o bot).
"""
import asyncio
import pytest

from app.buffer import lead_lock


class _FakeLockRedis:
    """Redis mínimo p/ o lock: SET NX EX + EVAL (compare-and-del por token)."""
    def __init__(self):
        self.store = {}

    async def set(self, key, val, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = val
        return True

    async def eval(self, script, numkeys, key, token):
        if self.store.get(key) == token:
            self.store.pop(key, None)
            return 1
        return 0


@pytest.fixture(autouse=True)
def _reset_lock_state(monkeypatch):
    monkeypatch.setattr(lead_lock, "_unavailable_until", 0.0, raising=False)
    monkeypatch.setattr(lead_lock, "LOCK_POLL_INTERVAL", 0.02, raising=False)


@pytest.mark.asyncio
async def test_lock_serializa_runs_do_mesmo_lead(monkeypatch):
    monkeypatch.setattr(lead_lock, "_get_client", lambda: _FakeLockRedis_shared)
    global _FakeLockRedis_shared
    _FakeLockRedis_shared = _FakeLockRedis()

    order: list[str] = []

    async def worker(tag: str, hold: float):
        async with lead_lock.lead_run_lock("L1") as acquired:
            order.append(f"{tag}:start:{acquired}")
            await asyncio.sleep(hold)
            order.append(f"{tag}:end")

    t1 = asyncio.create_task(worker("A", 0.20))
    await asyncio.sleep(0.03)  # garante que A pega o lock primeiro
    t2 = asyncio.create_task(worker("B", 0.02))
    await asyncio.gather(t1, t2)

    # B só pode começar DEPOIS de A terminar (serialização absoluta)
    assert order == ["A:start:True", "A:end", "B:start:True", "B:end"]


@pytest.mark.asyncio
async def test_lock_diferentes_leads_nao_bloqueiam(monkeypatch):
    monkeypatch.setattr(lead_lock, "_get_client", lambda: _FakeLockRedis())  # cada lead, store próprio? não — precisa compartilhado
    shared = _FakeLockRedis()
    monkeypatch.setattr(lead_lock, "_get_client", lambda: shared)

    started: list[str] = []

    async def worker(lead_id: str):
        async with lead_lock.lead_run_lock(lead_id) as acquired:
            started.append(f"{lead_id}:{acquired}")
            await asyncio.sleep(0.1)

    await asyncio.gather(worker("L1"), worker("L2"))
    # ambos adquirem (leads distintos → chaves distintas → sem espera)
    assert set(started) == {"L1:True", "L2:True"}


@pytest.mark.asyncio
async def test_lock_fail_open_quando_redis_indisponivel(monkeypatch):
    def _boom():
        raise ConnectionError("redis down")
    monkeypatch.setattr(lead_lock, "_get_client", _boom)

    async with lead_lock.lead_run_lock("L1") as acquired:
        assert acquired is False  # não travou — seguiu sem serialização


@pytest.mark.asyncio
async def test_lock_sem_lead_id_nao_bloqueia(monkeypatch):
    async with lead_lock.lead_run_lock("") as acquired:
        assert acquired is False

"""Runtime do worker: isolamento por domínio, wake-up por evento, fallback scan.

NOTA: fakeredis NÃO implementa a semântica de BLOCK do XREADGROUP (retorna []
imediatamente — verificado em 09/07/2026), então estes testes usam um stub que
emula o bloqueio com asyncio.Queue. O BLOCK real é coberto pelo smoke de
runtime contra o Redis local (plano, Task 6).
"""
import asyncio

from app.worker import runtime


class StubRedis:
    """Emula XREADGROUP com BLOCK real (espera em fila) + XACK/XGROUP."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.acked: list[str] = []
        self.groups: list[tuple[str, str]] = []

    async def xgroup_create(self, stream, group, id="$", mkstream=False):
        self.groups.append((stream, group))

    async def xreadgroup(self, group, consumer, streams, count=1, block=None):
        stream = next(iter(streams))
        try:
            item = await asyncio.wait_for(self.queue.get(), timeout=(block or 0) / 1000)
            return [(stream, [item])]
        except asyncio.TimeoutError:
            return []

    async def xack(self, stream, group, *ids):
        self.acked.extend(ids)

    async def push(self, entry_id="1-0"):
        await self.queue.put((entry_id, {"payload": "{}"}))


async def _cancel(task: asyncio.Task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_run_periodic_isola_excecao_e_continua():
    calls = []

    async def boom():
        calls.append(1)
        raise RuntimeError("tick quebrado")

    task = asyncio.create_task(runtime.run_periodic("t", boom, interval=0.01))
    await asyncio.sleep(0.08)
    await _cancel(task)
    assert len(calls) >= 3  # exceção não matou o loop


async def test_run_periodic_aceita_funcao_sincrona():
    calls = []
    task = asyncio.create_task(runtime.run_periodic("t", lambda: calls.append(1), interval=0.01))
    await asyncio.sleep(0.05)
    await _cancel(task)
    assert calls


async def test_event_driven_roda_no_startup_e_acorda_com_evento():
    r = StubRedis()
    calls = []

    async def fn():
        calls.append(1)

    task = asyncio.create_task(
        runtime.run_event_driven("t", fn, "followups", fallback_interval=5, client=r)
    )
    await asyncio.sleep(0.1)
    assert len(calls) == 1  # rodou no startup, agora bloqueado no XREADGROUP

    await r.push()
    await asyncio.sleep(0.2)
    assert len(calls) == 2  # evento acordou bem antes do fallback de 5s
    assert ("events:followups", runtime.GROUP) in r.groups  # grupo criado
    await _cancel(task)


async def test_event_driven_ack_imediato():
    r = StubRedis()

    async def fn():
        pass

    task = asyncio.create_task(
        runtime.run_event_driven("t", fn, "broadcasts", fallback_interval=5, client=r)
    )
    await asyncio.sleep(0.1)
    await r.push("7-0")
    await asyncio.sleep(0.2)
    assert r.acked == ["7-0"]  # ACK imediato (wake-up, não durabilidade)
    await _cancel(task)


async def test_event_driven_excecao_no_fn_nao_mata_o_loop():
    r = StubRedis()
    calls = []

    async def boom():
        calls.append(1)
        raise RuntimeError("dominio quebrado")

    task = asyncio.create_task(
        runtime.run_event_driven("t", boom, "automation", fallback_interval=5, client=r)
    )
    await asyncio.sleep(0.1)
    await r.push()
    await asyncio.sleep(0.2)
    assert len(calls) == 2  # startup + evento, apesar das exceções
    await _cancel(task)


async def test_event_driven_fallback_varre_sem_evento():
    r = StubRedis()
    calls = []

    async def fn():
        calls.append(1)

    task = asyncio.create_task(
        runtime.run_event_driven("t", fn, "followups", fallback_interval=0.03, client=r)
    )
    await asyncio.sleep(0.2)
    await _cancel(task)
    assert len(calls) >= 3  # timeout do BLOCK = varredura de fallback


async def test_event_driven_degrada_para_tick_sem_redis():
    class DeadRedis:
        def __getattr__(self, name):
            async def _fail(*a, **k):
                raise ConnectionError("redis down")
            return _fail

    calls = []

    async def fn():
        calls.append(1)

    task = asyncio.create_task(
        runtime.run_event_driven("t", fn, "followups", fallback_interval=0.02, client=DeadRedis())
    )
    await asyncio.sleep(0.15)
    await _cancel(task)
    assert len(calls) >= 3  # continua varrendo no ritmo do fallback

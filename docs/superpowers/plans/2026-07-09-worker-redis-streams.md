# Worker Redis Streams + db_call Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o loop sequencial único de 30s do worker por tasks asyncio isoladas por domínio, acordadas por eventos Redis Streams (XADD/XREADGROUP) com varredura de fallback, e unificar retry/acesso a dados nos hot paths via `db_call` (asyncio.to_thread + run_with_retry).

**Architecture:** Eventos são *wake-ups* (fail-open, ACK imediato); o banco continua fonte de verdade com os claims atômicos existentes — perder evento custa no máximo um tick de fallback. Spec: `docs/superpowers/specs/2026-07-09-worker-redis-streams-design.md`.

**Tech Stack:** redis-py (sync p/ emissão, asyncio p/ consumo — já no requirements), fakeredis (testes, já no requirements-dev), FastAPI/asyncio existentes.

## Global Constraints

- Somente a instância Redis existente (`settings.redis_url`); PROIBIDO Celery/arq/mensageria externa.
- Comando do container worker (`python -m app.campaign.worker`) e docker-compose intocados.
- `pytest -q -m "not integration"` 100% verde ao final (é gate de deploy).
- Emissão de eventos NUNCA pode levantar exceção (fail-open) — criação de broadcast/follow-up não pode falhar por Redis fora.
- Push para master somente com autorização do usuário.

---

### Task 1: Barramento de eventos — `app/events/bus.py`

**Files:**
- Create: `backend/app/events/__init__.py` (vazio)
- Create: `backend/app/events/bus.py`
- Test: `backend/tests/test_events_bus.py`

**Interfaces:**
- Produces: `emit_event(domain: str, payload: dict | None = None) -> bool`; `stream_key(domain: str) -> str` (= `f"events:{domain}"`); `DOMAINS = ("broadcasts", "followups", "automation")`. Consumido pelas Tasks 2-4.

- [ ] **Step 1: Teste falhando**

`backend/tests/test_events_bus.py`:

```python
"""Barramento de eventos (wake-up) — emissão fail-open sobre Redis Streams."""
from unittest.mock import MagicMock, patch

from app.events import bus


def _fresh_client(mock_client):
    """Injeta client mockado e limpa o cache module-level."""
    bus._client = mock_client


def test_emit_event_faz_xadd_no_stream_do_dominio():
    client = MagicMock()
    _fresh_client(client)
    ok = bus.emit_event("followups", {"job_id": "abc"})
    assert ok is True
    args, kwargs = client.xadd.call_args
    assert args[0] == "events:followups"
    assert kwargs.get("maxlen") == 1024 and kwargs.get("approximate") is True


def test_emit_event_fail_open_quando_redis_fora():
    client = MagicMock()
    client.xadd.side_effect = ConnectionError("redis down")
    _fresh_client(client)
    assert bus.emit_event("broadcasts") is False  # não levanta


def test_emit_event_rejeita_dominio_desconhecido():
    client = MagicMock()
    _fresh_client(client)
    assert bus.emit_event("nope") is False
    client.xadd.assert_not_called()


def test_stream_key():
    assert bus.stream_key("automation") == "events:automation"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_events_bus.py -q`
Expected: FAIL/ERROR (`ModuleNotFoundError: app.events`)

- [ ] **Step 3: Implementar `app/events/bus.py`**

```python
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

DOMAINS = ("broadcasts", "followups", "automation")
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_events_bus.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/events/ backend/tests/test_events_bus.py
git commit -m "feat(events): barramento wake-up fail-open sobre Redis Streams (XADD)"
```

---

### Task 2: Runtime do worker — `app/worker/runtime.py`

**Files:**
- Create: `backend/app/worker/__init__.py` (vazio)
- Create: `backend/app/worker/runtime.py`
- Test: `backend/tests/test_worker_runtime.py`

**Interfaces:**
- Consumes: `stream_key` da Task 1.
- Produces: `run_periodic(name: str, fn, interval: float) -> None` (coroutine infinita); `run_event_driven(name: str, fn, domain: str, fallback_interval: float, *, client=None) -> None` (coroutine infinita; `client` injetável para testes); constantes `GROUP = "worker"`, `CONSUMER = "worker-main"`. Consumido pela Task 3.

- [ ] **Step 1: Testes falhando**

`backend/tests/test_worker_runtime.py`:

```python
"""Runtime do worker: isolamento por domínio, wake-up por evento, fallback scan."""
import asyncio

import fakeredis.aioredis
import pytest

from app.worker import runtime


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
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    calls = []

    async def fn():
        calls.append(1)

    task = asyncio.create_task(
        runtime.run_event_driven("t", fn, "followups", fallback_interval=5, client=r)
    )
    await asyncio.sleep(0.1)
    assert len(calls) == 1  # rodou no startup, agora bloqueado no XREADGROUP

    await r.xadd("events:followups", {"payload": "{}"})
    await asyncio.sleep(0.2)
    assert len(calls) == 2  # evento acordou bem antes do fallback de 5s
    await _cancel(task)


async def test_event_driven_ack_imediato_sem_pendencias():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def fn():
        pass

    task = asyncio.create_task(
        runtime.run_event_driven("t", fn, "broadcasts", fallback_interval=5, client=r)
    )
    await asyncio.sleep(0.1)
    await r.xadd("events:broadcasts", {"payload": "{}"})
    await asyncio.sleep(0.2)
    pending = await r.xpending("events:broadcasts", runtime.GROUP)
    assert pending["pending"] == 0  # ACK imediato (wake-up, não durabilidade)
    await _cancel(task)


async def test_event_driven_excecao_no_fn_nao_mata_o_loop():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    calls = []

    async def boom():
        calls.append(1)
        raise RuntimeError("dominio quebrado")

    task = asyncio.create_task(
        runtime.run_event_driven("t", boom, "automation", fallback_interval=5, client=r)
    )
    await asyncio.sleep(0.1)
    await r.xadd("events:automation", {"payload": "{}"})
    await asyncio.sleep(0.2)
    assert len(calls) == 2  # startup + evento, apesar das exceções
    await _cancel(task)


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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_worker_runtime.py -q`
Expected: ERROR (`ModuleNotFoundError: app.worker`)

- [ ] **Step 3: Implementar `app/worker/runtime.py`**

```python
"""Runtime do worker: um loop isolado por domínio.

- run_periodic: tick fixo; exceção do fn é logada e o loop continua.
- run_event_driven: processa, depois bloqueia em XREADGROUP até chegar evento
  (wake-up) ou estourar o fallback (varredura de segurança). ACK imediato:
  o evento não é a camada de durabilidade — o banco é (claims atômicos +
  recovery de stale). Redis fora ⇒ degrada para tick puro (comportamento antigo).
"""
import asyncio
import inspect
import logging

import redis.asyncio as aioredis
from redis import exceptions as redis_exceptions

from app.config import settings
from app.events.bus import stream_key

logger = logging.getLogger(__name__)

GROUP = "worker"
CONSUMER = "worker-main"


async def _call(fn) -> None:
    if inspect.iscoroutinefunction(fn):
        await fn()
    else:
        await asyncio.to_thread(fn)


async def run_periodic(name: str, fn, interval: float) -> None:
    logger.info("[WORKER:%s] loop periódico (%.0fs)", name, interval)
    while True:
        try:
            await _call(fn)
        except Exception:
            logger.error("[WORKER:%s] erro no tick (isolado)", name, exc_info=True)
        await asyncio.sleep(interval)


def _default_client(fallback_interval: float) -> aioredis.Redis:
    return aioredis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=2, socket_timeout=fallback_interval + 10,
    )


async def run_event_driven(
    name: str, fn, domain: str, fallback_interval: float, *, client: aioredis.Redis | None = None
) -> None:
    r = client if client is not None else _default_client(fallback_interval)
    stream = stream_key(domain)
    group_ready = False
    logger.info("[WORKER:%s] loop por evento (stream=%s, fallback=%.0fs)", name, stream, fallback_interval)
    while True:
        # Processa primeiro: cobre o startup (pendências acumuladas em restart)
        # e o pós-wake-up. A varredura decide o que fazer; o evento só acorda.
        try:
            await _call(fn)
        except Exception:
            logger.error("[WORKER:%s] erro no processamento (isolado)", name, exc_info=True)
        # Espera o próximo wake-up (evento) ou o fallback (timeout do BLOCK).
        try:
            if not group_ready:
                try:
                    await r.xgroup_create(stream, GROUP, id="$", mkstream=True)
                except redis_exceptions.ResponseError as exc:
                    if "BUSYGROUP" not in str(exc):
                        raise
                group_ready = True
            entries = await r.xreadgroup(
                GROUP, CONSUMER, {stream: ">"}, count=32, block=int(fallback_interval * 1000)
            )
            if entries:
                ids = [entry_id for _stream, items in entries for entry_id, _fields in items]
                if ids:
                    await r.xack(stream, GROUP, *ids)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            group_ready = False  # força recriar grupo/conexão na próxima volta
            logger.warning(
                "[WORKER:%s] Redis indisponível — degradando p/ tick de %.0fs: %s",
                name, fallback_interval, exc,
            )
            await asyncio.sleep(fallback_interval)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_worker_runtime.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/worker/ backend/tests/test_worker_runtime.py
git commit -m "feat(worker): runtime de loops isolados — periodico e event-driven (XREADGROUP)"
```

---

### Task 3: Entrypoint por domínios — `app/worker/main.py` + remoção do loop antigo

**Files:**
- Create: `backend/app/worker/main.py`
- Modify: `backend/app/campaign/worker.py` (shim)
- Modify: `backend/app/broadcast/worker.py:739-769` (remover `run_worker`; manter todas as funções de domínio e `WORKER_TICK_SECONDS` se referenciado em testes — verificar com grep)
- Test: `backend/tests/test_worker_main.py`

**Interfaces:**
- Consumes: `run_periodic`/`run_event_driven` (Task 2).
- Produces: `app.worker.main.run_worker()` — coroutine que faz `asyncio.gather` das 7 tasks; `TASK_SPECS` (lista de tuplas para introspecção nos testes).

- [ ] **Step 1: Teste falhando**

`backend/tests/test_worker_main.py`:

```python
"""Registro de domínios do worker: cobertura e isolamento."""
from app.worker import main


def test_task_specs_cobrem_todos_os_dominios():
    names = {spec[0] for spec in main.TASK_SPECS}
    assert names == {
        "broadcasts", "followups", "automation",
        "llm-parking", "memory", "channel-health", "reconcile",
    }


def test_dominios_quentes_sao_event_driven():
    kinds = {spec[0]: spec[1] for spec in main.TASK_SPECS}
    assert kinds["broadcasts"] == "event"
    assert kinds["followups"] == "event"
    assert kinds["automation"] == "event"
    assert kinds["reconcile"] == "periodic"


def test_shim_do_container_aponta_para_o_novo_runtime():
    from app.campaign import worker as shim
    assert shim.run_worker is main.run_worker
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_worker_main.py -q`
Expected: ERROR (`ModuleNotFoundError`/`ImportError`)

- [ ] **Step 3: Implementar `app/worker/main.py`**

```python
"""Entrypoint do worker: uma asyncio.Task isolada por domínio.

Substitui o loop sequencial único de 30s (antigo broadcast/worker.run_worker):
falha ou lentidão em um domínio não atrasa os demais. Domínios quentes são
acordados por eventos (app/events/bus.py) com varredura de fallback; os de
manutenção rodam em tick próprio, mais espaçado (egress).
"""
import asyncio
import logging

from app.worker.runtime import run_event_driven, run_periodic

logger = logging.getLogger(__name__)


async def _broadcasts_tick() -> None:
    from app.broadcast.worker import process_broadcasts, process_scheduled_broadcasts
    await process_scheduled_broadcasts()
    await process_broadcasts()


async def _followups_tick() -> None:
    from app.follow_up.scheduler import process_due_followups
    await process_due_followups()


async def _automation_tick() -> None:
    from app.automation.engine import process_due_enrollments
    from app.automation.triggers import check_polling_triggers
    await check_polling_triggers()
    await process_due_enrollments()


async def _llm_parking_tick() -> None:
    from app.buffer.parking import drain_parked_llm_turns
    await drain_parked_llm_turns()


async def _memory_tick() -> None:
    from app.agent.memory_manager import process_stale_lead_memories
    await process_stale_lead_memories()


async def _channel_health_tick() -> None:
    from app.broadcast.worker import check_meta_channel_health
    await check_meta_channel_health()


async def _reconcile_tick() -> None:
    from app.broadcast.worker import (
        process_wrong_number_deadends,
        reconcile_broadcast_replies,
        reconcile_delivery_timeouts,
        retry_undelivered_cold_sends,
    )
    await asyncio.to_thread(reconcile_broadcast_replies)
    await asyncio.to_thread(reconcile_delivery_timeouts)
    await retry_undelivered_cold_sends()
    await asyncio.to_thread(process_wrong_number_deadends)


# (nome, tipo, fn, intervalo/fallback em segundos)
TASK_SPECS = [
    ("broadcasts", "event", _broadcasts_tick, 60),
    ("followups", "event", _followups_tick, 30),
    ("automation", "event", _automation_tick, 30),
    ("llm-parking", "periodic", _llm_parking_tick, 30),
    ("memory", "periodic", _memory_tick, 60),
    ("channel-health", "periodic", _channel_health_tick, 300),
    ("reconcile", "periodic", _reconcile_tick, 300),
]


async def run_worker() -> None:
    logger.info("Worker started — %d domínios isolados (event-driven + periódicos)", len(TASK_SPECS))
    tasks = []
    for name, kind, fn, seconds in TASK_SPECS:
        if kind == "event":
            tasks.append(run_event_driven(name, fn, name, seconds))
        else:
            tasks.append(run_periodic(name, fn, seconds))
    await asyncio.gather(*tasks)
```

- [ ] **Step 4: Atualizar o shim `app/campaign/worker.py`**

```python
# Legacy entry point (docker-compose: python -m app.campaign.worker) —
# delega para o runtime por domínios.
from app.worker.main import run_worker

if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
```

- [ ] **Step 5: Remover `run_worker` de `broadcast/worker.py`**

Deletar a função `run_worker` (linhas 739-769). Antes, rodar `grep -rn "WORKER_TICK_SECONDS\|from app.broadcast.worker import.*run_worker" backend/ --include="*.py"` e ajustar referências restantes (constante fica se houver teste que a use).

- [ ] **Step 6: Rodar testes do módulo + suíte de broadcast**

Run: `cd backend && python -m pytest tests/test_worker_main.py tests/test_worker_runtime.py -q && python -m pytest tests/ -q -k "broadcast or worker" -m "not integration"`
Expected: tudo verde

- [ ] **Step 7: Commit**

```bash
git add backend/app/worker/main.py backend/app/campaign/worker.py backend/app/broadcast/worker.py backend/tests/test_worker_main.py
git commit -m "feat(worker): dominios isolados via asyncio.gather substituem loop sequencial de 30s"
```

---

### Task 4: Pontos de emissão de eventos

**Files:**
- Modify: `backend/app/broadcast/router.py` (`create_broadcast`, `update_broadcast`, `start_broadcast`)
- Modify: `backend/app/follow_up/service.py` (`schedule_followup:198`, `schedule_handoff_rescue:360`, `schedule_ai_return:405`)
- Modify: `backend/app/lp_webhook/service.py:332`
- Modify: `backend/app/campaigns/service.py` (`create_enrollment`) + ponto de criação de enrollment do automation engine (localizar com `grep -rn "enrollments\").insert" backend/app --include="*.py"`)
- Test: `backend/tests/test_event_emission.py`

**Interfaces:**
- Consumes: `emit_event` (Task 1).
- Padrão em todos os sites: `emit_event("<dominio>")` imediatamente APÓS o `.execute()` do insert/update que cria o trabalho. Sem payload obrigatório (wake-up); fail-open já é garantido pelo bus.

- [ ] **Step 1: Teste falhando (spy no bus)**

`backend/tests/test_event_emission.py`:

```python
"""Criação de trabalho emite wake-up para o worker (fail-open)."""
from unittest.mock import MagicMock, patch


def test_start_broadcast_emite_evento(monkeypatch):
    import app.broadcast.router as router_mod
    emitted = []
    monkeypatch.setattr(router_mod, "emit_event", lambda d, p=None: emitted.append(d))
    # sb mockado: billing sem alerta, broadcast draft, 3 pendentes
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    with patch.object(router_mod, "get_supabase", return_value=sb):
        # o corpo completo é exercitado nos testes existentes de router;
        # aqui basta garantir que o caminho feliz emite:
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "draft"}
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 3
        import asyncio
        asyncio.get_event_loop().run_until_complete(router_mod.start_broadcast("b-1"))
    assert emitted == ["broadcasts"]


def test_schedule_followup_emite_evento(monkeypatch):
    import app.follow_up.service as svc
    emitted = []
    monkeypatch.setattr(svc, "emit_event", lambda d, p=None: emitted.append(d))
    sb = MagicMock()
    with patch.object(svc, "get_supabase", return_value=sb):
        svc.schedule_followup(conversation_id="c-1", lead_id="l-1", channel_id="ch-1")
    assert "followups" in emitted
```

(Adaptar as assinaturas reais de `schedule_followup` ao escrever — conferir parâmetros obrigatórios no arquivo; usar os defaults mínimos que os testes existentes de `test_followup_*` já usam como referência.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_event_emission.py -q`
Expected: FAIL (`AttributeError: emit_event` — símbolo ainda não importado nos módulos)

- [ ] **Step 3: Adicionar emissões**

Em cada arquivo, `from app.events.bus import emit_event` e:

- `broadcast/router.py`:
  - `start_broadcast`: após `sb.table("broadcasts").update({"status": "running"})...execute()` → `emit_event("broadcasts")`.
  - `create_broadcast`: após o insert, se `status == "scheduled"` → `emit_event("broadcasts")`.
  - `update_broadcast`: se o body contém `status == "running"` ou `scheduled_at` → `emit_event("broadcasts")` após o update (cobre resume).
- `follow_up/service.py`: após cada um dos 3 inserts de `follow_up_jobs` → `emit_event("followups")`.
- `lp_webhook/service.py`: após o insert da linha 332 → `emit_event("followups")`.
- `campaigns/service.py` `create_enrollment` (e o insert equivalente do automation engine, se distinto) → `emit_event("automation")`.

- [ ] **Step 4: Rodar testes novos + regressão dos módulos tocados**

Run: `cd backend && python -m pytest tests/test_event_emission.py -q && python -m pytest tests/ -q -k "followup or broadcast or lp_ or campaign or automation" -m "not integration"`
Expected: tudo verde (os testes existentes não mockam `emit_event`; como ele é fail-open e o Redis dos testes não existe, ele só loga warning — verificar que nenhum teste asserta logs)

- [ ] **Step 5: Commit**

```bash
git add backend/app/broadcast/router.py backend/app/follow_up/service.py backend/app/lp_webhook/service.py backend/app/campaigns/service.py backend/tests/test_event_emission.py
git commit -m "feat(events): criacao de broadcast/follow-up/enrollment emite wake-up p/ o worker"
```

(Se o insert do automation engine estiver em outro arquivo, incluí-lo no add.)

---

### Task 5: `db_call` + conversão dos hot paths (Otimização 3)

**Files:**
- Modify: `backend/app/db/supabase.py` (novo helper)
- Modify: `backend/app/broadcast/worker.py` (varreduras de `process_broadcasts` e `process_scheduled_broadcasts`)
- Modify: `backend/app/follow_up/scheduler.py` (`process_due_followups`: recovery, due-scan e claim)
- Modify: `backend/app/automation/engine.py` (varredura de due-enrollments)
- Modify: `backend/app/buffer/processor.py` (`_save_with_retry` → delega a `run_with_retry` via thread; site do TODO `:791`)
- Test: `backend/tests/test_db_call.py`

**Interfaces:**
- Produces em `app/db/supabase.py`:

```python
async def db_call(fn, *, label: str = "db"):
    """Chamada Supabase síncrona FORA do event loop, com retry de transporte.

    Une as duas pendências dos hot paths: (1) não bloquear o loop asyncio com
    httpx síncrono; (2) política única de retry (run_with_retry). O executor
    default reusa threads ⇒ o cliente por thread (threading.local) é reaproveitado.
    """
    import asyncio
    return await asyncio.to_thread(run_with_retry, fn, label=label)
```

(import de `asyncio` no topo do módulo, não dentro da função — mostrado aqui junto por clareza.)

- [ ] **Step 1: Teste falhando**

`backend/tests/test_db_call.py`:

```python
"""db_call: retry de transporte unificado + execução fora do event loop."""
import threading

import httpx
import pytest

from app.db.supabase import db_call


async def test_db_call_roda_fora_da_thread_do_loop():
    loop_thread = threading.get_ident()
    seen = {}

    def q():
        seen["thread"] = threading.get_ident()
        return 42

    assert await db_call(q) == 42
    assert seen["thread"] != loop_thread


async def test_db_call_retenta_transport_error():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 2:
            raise httpx.RemoteProtocolError("GOAWAY")
        return "ok"

    assert await db_call(flaky, label="test") == "ok"
    assert len(attempts) == 2


async def test_db_call_nao_retenta_erro_de_aplicacao():
    attempts = []

    def bad():
        attempts.append(1)
        raise httpx.HTTPStatusError("409", request=None, response=None)

    with pytest.raises(httpx.HTTPStatusError):
        await db_call(bad)
    assert len(attempts) == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_db_call.py -q`
Expected: ImportError (`db_call`)

- [ ] **Step 3: Implementar `db_call` e rodar o teste**

Run: `cd backend && python -m pytest tests/test_db_call.py -q`
Expected: 3 passed

- [ ] **Step 4: Converter os call-sites dos hot paths**

Padrão de conversão (query única → lambda):

```python
# antes
broadcasts = sb.table("broadcasts").select("*").eq("status", "running").eq("env_tag", _ENV_TAG).execute().data
# depois
broadcasts = (await db_call(
    lambda: get_supabase().table("broadcasts").select("*")
    .eq("status", "running").eq("env_tag", _ENV_TAG).execute(),
    label="broadcasts.scan",
)).data
```

Sites (funções multi-query síncronas inteiras vão via `asyncio.to_thread(fn, ...)` em vez de lambda):

1. `broadcast/worker.py process_broadcasts`: varredura de `status=running`.
2. `broadcast/worker.py process_scheduled_broadcasts`: varredura de `status=scheduled` e o count de pendentes.
3. `follow_up/scheduler.py process_due_followups`: `_recover_stale_followup_jobs(now)` → `await asyncio.to_thread(...)`; `get_due_followups(now)` → `await asyncio.to_thread(...)`; `_claim_followup_job(job["id"])` → `await db_call(lambda: ...)` se for query única (conferir no arquivo).
4. `automation/engine.py process_due_enrollments`: `get_due_enrollments(now)` → `await asyncio.to_thread(...)`.
5. `buffer/processor.py`: corpo de `_save_with_retry` passa a chamar `run_with_retry` (remove a política própria); o call-site marcado com TODO `:791` (`_wamid_already_processed`) → `await asyncio.to_thread(...)`. Manter as assinaturas públicas para não quebrar os testes de fatias existentes.

- [ ] **Step 5: Regressão dos módulos convertidos**

Run: `cd backend && python -m pytest tests/ -q -k "processor or followup or broadcast or automation or worker" -m "not integration"`
Expected: tudo verde (mocks `MagicMock` de `get_supabase` funcionam inalterados dentro de `to_thread`)

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/supabase.py backend/app/broadcast/worker.py backend/app/follow_up/scheduler.py backend/app/automation/engine.py backend/app/buffer/processor.py backend/tests/test_db_call.py
git commit -m "refactor(db): db_call unifica retry+to_thread nos hot paths do worker/scheduler/processor"
```

---

### Task 6: Suíte completa + verificação de runtime

**Files:** nenhum novo.

- [ ] **Step 1: Suíte completa (gate local)**

Run: `cd backend && python -m pytest -q -m "not integration" -p no:cacheprovider`
Expected: ≥1835 passed + novos, 0 failed

- [ ] **Step 2: Verificação de runtime com Redis local**

Com o Redis dev disponível (`scripts/start-redis.ps1` se necessário):

```bash
cd backend && timeout 20 python -m app.campaign.worker 2>&1 | head -30
```

Expected: logs `Worker started — 7 domínios`, um `[WORKER:<nome>] loop ...` por domínio, sem tracebacks nos primeiros ticks.

Smoke do wake-up:

```bash
cd backend && python -c "from app.events.bus import emit_event; print(emit_event('followups'))"
```

Expected: `True`, e no log do worker um processamento de followups imediato (< 1s, não 30s).

- [ ] **Step 3: Commit da spec + plano e apresentação do diff ao usuário**

```bash
git add docs/superpowers/specs/2026-07-09-worker-redis-streams-design.md docs/superpowers/plans/2026-07-09-worker-redis-streams.md
git commit -m "docs: spec e plano do worker event-driven (Redis Streams) + db_call"
```

Apresentar diff consolidado e aguardar autorização para push (CLAUDE.md).

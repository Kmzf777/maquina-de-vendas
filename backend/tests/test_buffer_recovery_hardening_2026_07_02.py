"""Buffer hardening — timer supervisionado + recovery reutilizável (Etapa 1 / A1).

Contexto forense: durante o apagão de produção (01-02/07), os timers asyncio
in-process de `_wait_and_flush` (manager.py) morreram em silêncio (sem log, sem
supervisão) e a recuperação de buffers órfãos (`recover_orphaned_buffers`) só
rodava no startup (`main.py`). Este arquivo cobre:

1. `_wait_and_flush` não pode morrer em silêncio — exceção é logada com o
   marcador `[BUFFER TIMER DIED]` e NUNCA propaga; a referência do timer é
   sempre limpa de `_active_timers` (mesmo quando ele morre no meio do polling).
2. `recover_orphaned_buffers` (extraída para `app/buffer/recovery.py`) é
   reutilizável pelo futuro watchdog periódico via `require_no_deadline=True` —
   nesse modo, não pode brigar com um timer vivo (deadline ainda não expirou).
"""
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from app.buffer.manager import _active_timers, _wait_and_flush
from app.buffer.recovery import recover_orphaned_buffers


class FakeRedis:
    """FakeRedis mínimo dict-backed para estes testes.

    Cobre só os métodos usados por recover_orphaned_buffers/_wait_and_flush:
    scan (single-pass — sempre devolve cursor=0, sem paginação real), exists,
    lrange, delete, get, rpush e set (este último só para montar o cenário de
    cada teste).
    """

    def __init__(self):
        self._lists: dict[str, list[str]] = {}
        self._strings: dict[str, str] = {}

    async def scan(self, cursor, match="*", count=None):
        import fnmatch
        keys = [
            k for k in list(self._strings.keys()) + list(self._lists.keys())
            if fnmatch.fnmatch(k, match)
        ]
        return 0, keys

    async def exists(self, key):
        return 1 if (key in self._strings or key in self._lists) else 0

    async def lrange(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            return list(items[start:])
        return list(items[start:end + 1])

    async def delete(self, *keys):
        for k in keys:
            self._lists.pop(k, None)
            self._strings.pop(k, None)

    async def get(self, key):
        return self._strings.get(key)

    async def set(self, key, value, ex=None):
        self._strings[key] = value

    async def rpush(self, key, *values):
        self._lists.setdefault(key, []).extend(values)
        return len(self._lists[key])


# --- Caso 1: timer morto não propaga e limpa _active_timers ---

async def test_wait_and_flush_timer_morto_nao_propaga_e_limpa_active_timers(caplog):
    """Se o Redis falhar dentro do loop de polling, o timer não pode morrer em silêncio."""
    phone, channel_id = "5511888880001", "chan-dead-timer"
    timer_key = f"{phone}:{channel_id}"
    _active_timers[timer_key] = MagicMock()  # simula a task viva registrada pelo caller

    r = FakeRedis()

    async def _boom(*_a, **_k):
        raise RuntimeError("redis indisponivel durante polling do lock")

    with patch("app.buffer.manager.asyncio.sleep", new=AsyncMock()), \
         patch.object(r, "exists", side_effect=_boom), \
         caplog.at_level(logging.ERROR, logger="app.buffer.manager"):
        await _wait_and_flush(r, phone, channel_id)  # não deve levantar RuntimeError

    assert "[BUFFER TIMER DIED]" in caplog.text
    assert f"phone={phone}" in caplog.text
    assert f"channel={channel_id}" in caplog.text
    assert timer_key not in _active_timers


# --- Casos 2-5: recover_orphaned_buffers ---

async def test_recover_com_require_no_deadline_pula_buffer_com_deadline_vivo():
    """require_no_deadline=True não pode brigar com um timer vivo (deadline presente)."""
    phone, channel_id = "5511888880002", "chan-alive"
    buf_key = f"buffer:{phone}:{channel_id}"
    deadline_key = f"{buf_key}:deadline"

    r = FakeRedis()
    await r.rpush(buf_key, "mensagem ainda dentro da janela")
    await r.set(deadline_key, str(9999999999.0))  # deadline no futuro distante

    with patch("app.buffer.processor.process_buffered_messages", new_callable=AsyncMock) as mock_process:
        recovered = await recover_orphaned_buffers(r, require_no_deadline=True, source="watchdog")

    assert recovered == 0
    mock_process.assert_not_called()
    assert await r.lrange(buf_key, 0, -1) == ["mensagem ainda dentro da janela"], (
        "buffer com deadline vivo não pode ser drenado"
    )


async def test_recover_com_require_no_deadline_drena_buffer_orfao_e_limpa_pending():
    """Sem lock/deadline: buffer é órfão de verdade — drena e chama process_buffered_messages."""
    phone, channel_id = "5511888880003", "chan-orphan"
    buf_key = f"buffer:{phone}:{channel_id}"

    r = FakeRedis()
    await r.rpush(buf_key, "oi", "tudo bem?")
    await r.set(f"pending_wamid:{phone}:{channel_id}", "wamid.123")
    await r.set(f"pending_quoted:{phone}:{channel_id}", "wamid.999")

    captured_coros = []

    def _capture_task(coro, *_a, **_k):
        captured_coros.append(coro)
        return MagicMock()

    with patch("app.buffer.processor.process_buffered_messages", new_callable=AsyncMock) as mock_process, \
         patch("app.buffer.recovery.asyncio.create_task", side_effect=_capture_task):
        recovered = await recover_orphaned_buffers(r, require_no_deadline=True, source="watchdog")

    assert recovered == 1
    for coro in captured_coros:
        await coro  # drena a coroutine capturada (evita RuntimeWarning "never awaited")

    mock_process.assert_called_once_with(
        phone, "oi\ntudo bem?", channel_id,
        wamid="wamid.123", quoted_wamid="wamid.999",
    )
    assert await r.exists(buf_key) == 0
    assert await r.exists(f"pending_wamid:{phone}:{channel_id}") == 0
    assert await r.exists(f"pending_quoted:{phone}:{channel_id}") == 0


async def test_recover_startup_drena_mesmo_com_deadline_presente():
    """require_no_deadline=False (startup) preserva o comportamento atual: drena mesmo com deadline vivo."""
    phone, channel_id = "5511888880004", "chan-startup"
    buf_key = f"buffer:{phone}:{channel_id}"
    deadline_key = f"{buf_key}:deadline"

    r = FakeRedis()
    await r.rpush(buf_key, "mensagem presa apos restart")
    await r.set(deadline_key, str(9999999999.0))

    captured_coros = []

    def _capture_task(coro, *_a, **_k):
        captured_coros.append(coro)
        return MagicMock()

    with patch("app.buffer.processor.process_buffered_messages", new_callable=AsyncMock) as mock_process, \
         patch("app.buffer.recovery.asyncio.create_task", side_effect=_capture_task):
        recovered = await recover_orphaned_buffers(r, require_no_deadline=False, source="startup")

    assert recovered == 1
    for coro in captured_coros:
        await coro

    mock_process.assert_called_once_with(
        phone, "mensagem presa apos restart", channel_id,
        wamid=None, quoted_wamid=None,
    )
    assert await r.exists(buf_key) == 0


async def test_recover_pula_lock_ativo_e_chave_malformada_sem_erro():
    """Buffer com :lock ativo é pulado (timer vivo); chave malformada é ignorada sem exceção."""
    phone, channel_id = "5511888880005", "chan-locked"
    buf_key = f"buffer:{phone}:{channel_id}"
    lock_key = f"{buf_key}:lock"

    r = FakeRedis()
    await r.rpush(buf_key, "mensagem com timer normal rodando")
    await r.set(lock_key, "1")
    await r.set("buffer:soUmaParte", "valor-qualquer")  # chave malformada (só 2 partes)

    with patch("app.buffer.processor.process_buffered_messages", new_callable=AsyncMock) as mock_process:
        recovered = await recover_orphaned_buffers(r, require_no_deadline=True, source="watchdog")

    assert recovered == 0
    mock_process.assert_not_called()
    assert await r.lrange(buf_key, 0, -1) == ["mensagem com timer normal rodando"]

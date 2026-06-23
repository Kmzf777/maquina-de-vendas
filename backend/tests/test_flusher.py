# backend/tests/test_flusher.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.buffer.flusher import flush_due_items, run_flusher


def _make_redis(members: list[str], raw_messages: list[str] | None = None):
    """AsyncMock Redis com pipeline (async ctx) retornando buffer não-vazio por membro."""
    raw = raw_messages if raw_messages is not None else ["oi"]
    r = AsyncMock()
    r.zrangebyscore = AsyncMock(return_value=list(members))
    r.zrem = AsyncMock(return_value=1)  # claim sempre bem-sucedido

    def _pipeline(*_a, **_k):
        pipe = MagicMock()
        pipe.lrange = MagicMock()
        pipe.delete = MagicMock()
        pipe.get = MagicMock()
        pipe.execute = AsyncMock(return_value=[list(raw), 1, None])
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        return pipe

    r.pipeline = MagicMock(side_effect=_pipeline)
    return r


@pytest.mark.asyncio
async def test_flush_processes_all_due_items():
    """Todos os itens vencidos devem ser processados (nenhum perdido)."""
    members = ["chanA:111", "chanA:222", "chanA:333"]
    r = _make_redis(members)
    proc = AsyncMock()
    with patch("app.buffer.flusher.get_channel", return_value={"id": "chanA"}), \
         patch("app.buffer.flusher.process_buffered_messages", new=proc):
        await flush_due_items(r)

    assert proc.await_count == 3
    processed_phones = {call.args[0] for call in proc.await_args_list}
    assert processed_phones == {"111", "222", "333"}


@pytest.mark.asyncio
async def test_flush_respects_concurrency_limit():
    """Processamento concorrente, mas limitado pelo Semaphore (não afoga LLM/rede)."""
    members = [f"chanA:{i}" for i in range(25)]
    r = _make_redis(members)
    state = {"current": 0, "max": 0}

    async def fake_proc(phone, combined, channel_id):
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        await asyncio.sleep(0.01)
        state["current"] -= 1

    with patch("app.buffer.flusher.get_channel", return_value={"id": "chanA"}), \
         patch("app.buffer.flusher.process_buffered_messages", new=fake_proc):
        await flush_due_items(r)

    assert state["max"] > 1, "deve processar em paralelo"
    assert state["max"] <= 10, "não deve exceder o limite do Semaphore"


@pytest.mark.asyncio
async def test_flush_isolates_per_item_failure():
    """Falha em um item não deve cancelar/abortar o processamento dos demais."""
    members = ["chanA:111", "chanA:222", "chanA:333"]
    r = _make_redis(members)

    def _side(phone, *_a, **_k):
        if phone == "111":
            raise RuntimeError("boom")

    proc = AsyncMock(side_effect=_side)
    with patch("app.buffer.flusher.get_channel", return_value={"id": "chanA"}), \
         patch("app.buffer.flusher.process_buffered_messages", new=proc):
        # Não deve levantar — falha isolada por item.
        await flush_due_items(r)

    assert proc.await_count == 3


@pytest.mark.asyncio
async def test_flush_skipped_when_buffer_disabled():
    """Flusher should skip processing when config:buffer_enabled == '0'."""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value="0")

    with patch("app.buffer.flusher.flush_due_items") as mock_flush:
        # Simulate one loop iteration then cancel
        async def fake_run(app):
            r = app.state.redis
            flag = await r.get("config:buffer_enabled")
            if flag != "0":
                await flush_due_items(r)

        app_mock = MagicMock()
        app_mock.state.redis = redis_mock

        await fake_run(app_mock)
        mock_flush.assert_not_called()


@pytest.mark.asyncio
async def test_flush_called_when_buffer_enabled():
    """Flusher should process when config:buffer_enabled == '1'."""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value="1")
    redis_mock.zrangebyscore = AsyncMock(return_value=[])

    app_mock = MagicMock()
    app_mock.state.redis = redis_mock

    # One iteration: flag is "1", zrangebyscore returns empty (no work)
    await flush_due_items(redis_mock)
    redis_mock.zrangebyscore.assert_called_once()

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.buffer.flusher import FLUSH_QUEUE_KEY, flush_due_items


async def test_item_vencido_e_processado(fake_redis):
    channel_id = "chan-uuid"
    phone = "5511999999999"
    member = f"{channel_id}:{phone}"
    buffer_key = f"buffer:{channel_id}:{phone}"

    # Adicionar item vencido (score no passado)
    past_score = time.time() - 1
    await fake_redis.zadd(FLUSH_QUEUE_KEY, {member: past_score})
    await fake_redis.rpush(buffer_key, "mensagem de teste")

    processed = []

    async def mock_process(ph, text, ch):
        processed.append((ph, text, ch["id"]))

    mock_channel = {"id": channel_id, "name": "Test", "provider": "meta_cloud", "agent_profile_id": None}

    with patch("app.buffer.flusher.process_buffered_messages", side_effect=mock_process), \
         patch("app.buffer.flusher.get_channel", return_value=mock_channel):
        await flush_due_items(fake_redis)

    assert len(processed) == 1
    assert processed[0][0] == phone
    assert processed[0][1] == "mensagem de teste"
    assert processed[0][2] == channel_id


async def test_item_futuro_nao_e_processado(fake_redis):
    channel_id = "chan-uuid"
    phone = "5511999999999"
    member = f"{channel_id}:{phone}"

    # Adicionar item com score no futuro
    future_score = time.time() + 60
    await fake_redis.zadd(FLUSH_QUEUE_KEY, {member: future_score})

    processed = []

    async def mock_process(ph, text, ch):
        processed.append(ph)

    with patch("app.buffer.flusher.process_buffered_messages", side_effect=mock_process):
        await flush_due_items(fake_redis)

    assert processed == []


async def test_buffer_e_deletado_atomicamente_apos_flush(fake_redis):
    channel_id = "chan-uuid"
    phone = "5511999999999"
    member = f"{channel_id}:{phone}"
    buffer_key = f"buffer:{channel_id}:{phone}"

    await fake_redis.zadd(FLUSH_QUEUE_KEY, {member: time.time() - 1})
    await fake_redis.rpush(buffer_key, "msg1")
    await fake_redis.rpush(buffer_key, "msg2")

    mock_channel = {"id": channel_id, "name": "Test", "provider": "meta_cloud", "agent_profile_id": None}

    with patch("app.buffer.flusher.process_buffered_messages", new_callable=AsyncMock), \
         patch("app.buffer.flusher.get_channel", return_value=mock_channel):
        await flush_due_items(fake_redis)

    remaining = await fake_redis.lrange(buffer_key, 0, -1)
    assert remaining == []


async def test_dois_workers_nao_processam_mesmo_item(fake_redis):
    """Simula dois workers tentando flush simultâneo: apenas um processa."""
    channel_id = "chan-uuid"
    phone = "5511999999999"
    member = f"{channel_id}:{phone}"
    buffer_key = f"buffer:{channel_id}:{phone}"

    await fake_redis.zadd(FLUSH_QUEUE_KEY, {member: time.time() - 1})
    await fake_redis.rpush(buffer_key, "msg")

    process_calls = []

    async def mock_process(ph, text, ch):
        process_calls.append(ph)

    mock_channel = {"id": channel_id, "name": "Test", "provider": "meta_cloud", "agent_profile_id": None}

    with patch("app.buffer.flusher.process_buffered_messages", side_effect=mock_process), \
         patch("app.buffer.flusher.get_channel", return_value=mock_channel):
        # Ambos workers rodam flush_due_items "ao mesmo tempo"
        await asyncio.gather(
            flush_due_items(fake_redis),
            flush_due_items(fake_redis),
        )

    # Apenas um deve ter processado
    assert len(process_calls) == 1

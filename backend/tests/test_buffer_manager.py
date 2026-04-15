import time
import pytest
from unittest.mock import AsyncMock, patch
from app.webhook.parser import IncomingMessage
from app.buffer.manager import push_to_buffer, FLUSH_QUEUE_KEY


def _make_msg(text="oi", message_id="wamid.test1", msg_type="text", media_url=None):
    return IncomingMessage(
        from_number="5511999999999",
        remote_jid="5511999999999@s.whatsapp.net",
        message_id=message_id,
        timestamp="1234567890",
        type=msg_type,
        text=text,
        media_url=media_url,
        channel_id="chan-uuid",
    )


async def test_push_adiciona_texto_ao_buffer(fake_redis):
    """push_to_buffer deve adicionar texto ao buffer list quando buffer está habilitado."""
    await fake_redis.set("config:buffer_enabled", "1")
    # Simulamos 'exists' retornando 0 (sem lock ainda)
    msg = _make_msg("hello")

    with patch("app.buffer.manager.asyncio.create_task"), \
         patch.object(fake_redis, "exists", AsyncMock(return_value=0)), \
         patch.object(fake_redis, "set", wraps=fake_redis.set), \
         patch.object(fake_redis, "rpush", wraps=fake_redis.rpush):
        await push_to_buffer(fake_redis, msg)

    items = await fake_redis.lrange("buffer:5511999999999", 0, -1)
    assert items == ["hello"]


async def test_push_texto_imediato_quando_buffer_desativado(fake_redis):
    """Quando buffer_enabled == '0', push_to_buffer processa imediatamente."""
    await fake_redis.set("config:buffer_enabled", "0")
    msg = _make_msg("oi direto")

    # Local import inside push_to_buffer means we patch at processor level
    with patch("app.buffer.processor.process_buffered_messages", new_callable=AsyncMock) as mock_process:
        await push_to_buffer(fake_redis, msg)

    mock_process.assert_called_once_with("5511999999999", "oi direto", "chan-uuid")


async def test_segunda_push_estende_lock(fake_redis, monkeypatch):
    """Segunda mensagem com lock ativo deve chamar expire (extend TTL)."""
    monkeypatch.setattr("app.buffer.manager.settings.buffer_base_timeout", 15)
    monkeypatch.setattr("app.buffer.manager.settings.buffer_extend_timeout", 10)
    monkeypatch.setattr("app.buffer.manager.settings.buffer_max_timeout", 45)
    await fake_redis.set("config:buffer_enabled", "1")

    msg2 = _make_msg("msg2", "wamid.2")

    expire_calls = []
    call_count = [0]

    async def fake_exists(key):
        call_count[0] += 1
        return 1  # Lock already exists

    async def fake_expire(key, ttl):
        expire_calls.append(ttl)

    async def fake_ttl(key):
        return 10

    with patch("app.buffer.manager.asyncio.create_task"), \
         patch.object(fake_redis, "exists", side_effect=fake_exists), \
         patch.object(fake_redis, "expire", side_effect=fake_expire), \
         patch.object(fake_redis, "ttl", side_effect=fake_ttl):
        await push_to_buffer(fake_redis, msg2)

    # expire should have been called with a TTL within bounds
    assert len(expire_calls) >= 1
    assert expire_calls[0] <= 45


async def test_media_url_gera_placeholder_no_buffer(fake_redis):
    """Mensagem de áudio com media_url deve gerar placeholder no buffer."""
    await fake_redis.set("config:buffer_enabled", "1")
    msg = _make_msg(text=None, msg_type="audio", media_url="https://example.com/audio.ogg")

    with patch("app.buffer.manager.asyncio.create_task"), \
         patch.object(fake_redis, "exists", AsyncMock(return_value=0)):
        await push_to_buffer(fake_redis, msg)

    items = await fake_redis.lrange("buffer:5511999999999", 0, -1)
    assert len(items) == 1
    assert "audio" in items[0]
    assert "media_url" in items[0]

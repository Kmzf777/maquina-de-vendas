"""Resiliência de startup: o backend espera o Redis aceitar conexões (Docker/Windows
demora a expor a porta 6379) antes de derrubar a aplicação."""
from unittest.mock import AsyncMock, patch

import pytest

from app.main import _wait_for_redis


@pytest.mark.asyncio
async def test_wait_for_redis_retries_then_succeeds():
    redis = AsyncMock()
    redis.ping = AsyncMock(side_effect=[
        ConnectionRefusedError("[WinError 1225]"),
        ConnectionRefusedError("[WinError 1225]"),
        True,
    ])
    with patch("app.main.asyncio.sleep", new=AsyncMock()) as sleep:
        await _wait_for_redis(redis, max_wait=15.0)

    assert redis.ping.await_count == 3   # falhou 2x, conectou na 3ª
    assert sleep.await_count == 2         # esperou entre as tentativas


@pytest.mark.asyncio
async def test_wait_for_redis_raises_after_timeout():
    redis = AsyncMock()
    redis.ping = AsyncMock(side_effect=ConnectionRefusedError("[WinError 1225]"))
    with patch("app.main.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(ConnectionRefusedError):
            await _wait_for_redis(redis, max_wait=0.0)  # deadline imediato → desiste já

    assert redis.ping.await_count == 1

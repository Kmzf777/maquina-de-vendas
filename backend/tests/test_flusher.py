# backend/tests/test_flusher.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.buffer.flusher import flush_due_items, run_flusher


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

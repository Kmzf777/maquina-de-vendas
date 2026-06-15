"""Unit tests for _is_duplicate_wamid — wamid-based idempotency helper."""
import pytest

from app.webhook.meta_router import _is_duplicate_wamid


@pytest.mark.anyio
async def test_first_call_returns_false(fake_redis):
    """A brand-new wamid must NOT be considered a duplicate."""
    result = await _is_duplicate_wamid(fake_redis, "wamid.abc123")
    assert result is False


@pytest.mark.anyio
async def test_second_call_same_wamid_returns_true(fake_redis):
    """The second call with the same wamid must be flagged as a duplicate."""
    wamid = "wamid.abc123"
    first = await _is_duplicate_wamid(fake_redis, wamid)
    second = await _is_duplicate_wamid(fake_redis, wamid)
    assert first is False
    assert second is True


@pytest.mark.anyio
async def test_different_wamids_are_independent(fake_redis):
    """Different wamids must be tracked independently."""
    assert await _is_duplicate_wamid(fake_redis, "wamid.AAA") is False
    assert await _is_duplicate_wamid(fake_redis, "wamid.BBB") is False
    # Second call to each should now be a duplicate
    assert await _is_duplicate_wamid(fake_redis, "wamid.AAA") is True
    assert await _is_duplicate_wamid(fake_redis, "wamid.BBB") is True


@pytest.mark.anyio
async def test_empty_wamid_returns_false(fake_redis):
    """An empty string wamid must return False (not a duplicate)."""
    # The guard `if msg.message_id` in meta_router prevents calling with None at the call site;
    # this test documents that passing an empty string directly also returns False gracefully.
    # We don't call with None because key=f"seen_wamid:{None}" would be a valid key — the
    # None guard lives at the webhook call site, not inside this helper.
    result = await _is_duplicate_wamid(fake_redis, "")
    assert result is False


@pytest.mark.anyio
async def test_redis_error_is_fail_open(fake_redis, monkeypatch):
    """If Redis raises, _is_duplicate_wamid must return False (fail-open, never drop messages)."""
    async def broken_set(*args, **kwargs):
        raise ConnectionError("Redis unreachable")

    monkeypatch.setattr(fake_redis, "set", broken_set)
    result = await _is_duplicate_wamid(fake_redis, "wamid.xyz")
    assert result is False

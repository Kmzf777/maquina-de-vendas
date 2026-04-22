from unittest.mock import MagicMock, patch

import pytest

from scripts.rehearsal import supabase_io


def _make_sb_chain(return_data=None):
    """Build a mock Supabase client that returns chained .table().select().eq()... calls."""
    sb = MagicMock()
    table = MagicMock()
    sb.table.return_value = table
    table.select.return_value = table
    table.delete.return_value = table
    table.eq.return_value = table
    table.gt.return_value = table
    table.order.return_value = table
    result = MagicMock()
    result.data = return_data or []
    table.execute.return_value = result
    return sb, table


def test_wipe_lead_deletes_in_right_order(monkeypatch):
    sb, table = _make_sb_chain(return_data=[{"id": "lead-1"}])
    monkeypatch.setattr(supabase_io, "get_supabase", lambda: sb)

    supabase_io.wipe_lead("5500000000")

    # sb.table() called in order: leads (to find id), then messages, conversations, deals, leads (delete)
    table_calls = [call.args[0] for call in sb.table.call_args_list]
    # first call to find lead id
    assert table_calls[0] == "leads"
    # subsequent calls: messages, conversations, deals, leads (delete)
    assert "messages" in table_calls
    assert "conversations" in table_calls
    assert "deals" in table_calls


def test_wipe_lead_no_lead_is_noop(monkeypatch):
    sb, table = _make_sb_chain(return_data=[])
    monkeypatch.setattr(supabase_io, "get_supabase", lambda: sb)

    # Should not raise
    supabase_io.wipe_lead("5500000000")


def test_get_messages_since_filters_by_timestamp(monkeypatch):
    sb, table = _make_sb_chain(return_data=[{"role": "assistant", "content": "oi"}])
    monkeypatch.setattr(supabase_io, "get_supabase", lambda: sb)

    result = supabase_io.get_messages_since("lead-id", "2026-04-20T10:00:00Z")

    assert len(result) == 1
    assert result[0]["role"] == "assistant"
    # Confirm .gt("created_at", ...) was called
    table.gt.assert_called_with("created_at", "2026-04-20T10:00:00Z")


def test_wipe_redis_buffer_deletes_all_keys():
    from unittest.mock import AsyncMock
    redis = AsyncMock()
    # sync wrapper
    import asyncio

    asyncio.run(supabase_io.wipe_redis_buffer("5500000000", redis))

    # Must delete: buffer:<phone>, buffer:<phone>:lock, buffer:<phone>:deadline,
    # pushname:<phone>, channel:<phone>
    deleted_keys = [call.args[0] for call in redis.delete.call_args_list]
    assert "buffer:5500000000" in deleted_keys
    assert "buffer:5500000000:lock" in deleted_keys
    assert "buffer:5500000000:deadline" in deleted_keys
    assert "pushname:5500000000" in deleted_keys
    assert "channel:5500000000" in deleted_keys

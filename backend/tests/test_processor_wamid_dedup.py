"""Unit tests for wamid-based duplicate detection in the message processor.

Covers:
- _wamid_already_processed: returns True when row found, False when empty, False on DB error.
- process_buffered_messages: returns early (no save, no agent) when wamid is already processed.
- process_buffered_messages: proceeds normally when wamid is None (internal/media paths).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helper: minimal mocks shared across tests
# ---------------------------------------------------------------------------

def _make_channel():
    return {
        "id": "chan-uuid",
        "name": "Test",
        "mode": "ai",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "12345", "access_token": "tok"},
        "agent_profiles": {
            "id": "profile-uuid", "model": "gemini-2.0-flash",
            "base_prompt": "You are ValerIA", "stages": {},
        },
    }


def _make_supabase_mock(rows: list):
    """Return a get_supabase mock whose .table().select().eq().limit().execute().data == rows."""
    mock_result = MagicMock()
    mock_result.data = rows

    mock_query = MagicMock()
    mock_query.execute.return_value = mock_result
    mock_query.limit.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.select.return_value = mock_query

    mock_sb = MagicMock()
    mock_sb.table.return_value = mock_query

    return mock_sb


# ---------------------------------------------------------------------------
# Tests for the _wamid_already_processed helper
# ---------------------------------------------------------------------------

def test_wamid_already_processed_returns_true_when_row_found():
    """Returns True when the DB query yields at least one row."""
    from app.buffer.processor import _wamid_already_processed

    mock_sb = _make_supabase_mock([{"id": "msg-uuid-1"}])

    with patch("app.buffer.processor.get_supabase", return_value=mock_sb):
        result = _wamid_already_processed("wamid_abc123")

    assert result is True


def test_wamid_already_processed_returns_false_when_no_rows():
    """Returns False when the DB query returns an empty list."""
    from app.buffer.processor import _wamid_already_processed

    mock_sb = _make_supabase_mock([])

    with patch("app.buffer.processor.get_supabase", return_value=mock_sb):
        result = _wamid_already_processed("wamid_new_message")

    assert result is False


def test_wamid_already_processed_fail_open_on_exception():
    """Returns False (fail-open) when the DB query raises any exception."""
    from app.buffer.processor import _wamid_already_processed

    with patch("app.buffer.processor.get_supabase", side_effect=RuntimeError("DB unavailable")):
        result = _wamid_already_processed("wamid_db_error")

    assert result is False


# ---------------------------------------------------------------------------
# Tests for the early-return path in process_buffered_messages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_buffered_messages_skips_on_duplicate_wamid():
    """When _wamid_already_processed returns True, save_message and run_agent are NOT called."""
    from app.buffer.processor import process_buffered_messages

    with patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider", return_value=AsyncMock()), \
         patch("app.buffer.processor.get_or_create_lead", return_value={"id": "lead-1", "phone": "5511999999999", "ai_enabled": True}), \
         patch("app.buffer.processor.get_or_create_conversation", return_value={
             "id": "conv-1", "status": "active", "stage": "secretaria"
         }), \
         patch("app.buffer.processor._resolve_media", return_value=("oi", None, None, None, None)), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor._wamid_already_processed", return_value=True), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor.get_supabase"):
        await process_buffered_messages(
            "5511999999999", "oi", "chan-uuid", wamid="wamid_dup_abc"
        )

    mock_save.assert_not_called()
    mock_agent.assert_not_called()


@pytest.mark.asyncio
async def test_process_buffered_messages_proceeds_when_wamid_is_none():
    """When wamid=None, the DB dedup check is skipped entirely and processing continues normally.

    run_agent returns a non-empty reply string to exercise the normal flow (not the handoff path).
    """
    from app.buffer.processor import process_buffered_messages

    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock()

    with patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider", return_value=mock_provider), \
         patch("app.buffer.processor.get_or_create_lead", return_value={"id": "lead-1", "phone": "5511999999999", "ai_enabled": True}), \
         patch("app.buffer.processor.get_or_create_conversation", return_value={
             "id": "conv-1", "status": "active", "stage": "secretaria"
         }), \
         patch("app.buffer.processor._resolve_media", return_value=("oi", None, None, None, None)), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor._wamid_already_processed") as mock_dedup_db, \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent", return_value="Olá!"), \
         patch("app.buffer.processor.get_supabase"), \
         patch("app.buffer.processor._update_last_msg"), \
         patch("app.buffer.processor._schedule_followup"), \
         patch("app.buffer.processor.pop_deferred_media", return_value=[]):
        await process_buffered_messages(
            "5511999999999", "oi", "chan-uuid", wamid=None
        )

    # DB dedup must NOT be called when wamid is None
    mock_dedup_db.assert_not_called()
    # User message must still be saved (normal flow, not handoff)
    mock_save.assert_called()


@pytest.mark.asyncio
async def test_process_buffered_messages_proceeds_when_wamid_new():
    """When _wamid_already_processed returns False, processing continues and save_message is called."""
    from app.buffer.processor import process_buffered_messages

    with patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider", return_value=AsyncMock()), \
         patch("app.buffer.processor.get_or_create_lead", return_value={"id": "lead-1", "phone": "5511999999999", "ai_enabled": True}), \
         patch("app.buffer.processor.get_or_create_conversation", return_value={
             "id": "conv-1", "status": "active", "stage": "secretaria"
         }), \
         patch("app.buffer.processor._resolve_media", return_value=("oi", None, None, None, None)), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor._wamid_already_processed", return_value=False), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent", return_value=None), \
         patch("app.buffer.processor.get_supabase"), \
         patch("app.buffer.processor._update_last_msg"):
        await process_buffered_messages(
            "5511999999999", "oi", "chan-uuid", wamid="wamid_fresh_msg"
        )

    # User message must be saved for a fresh wamid
    mock_save.assert_called_once()

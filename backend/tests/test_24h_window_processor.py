from unittest.mock import MagicMock, patch, AsyncMock
import pytest


@pytest.mark.asyncio
async def test_process_buffered_messages_updates_last_customer_message_at():
    """After saving an inbound user message, last_customer_message_at must be updated on the lead."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = None

    with (
        patch("app.buffer.processor.get_or_create_lead", return_value={"id": "lead-1", "human_control": False, "stage": "secretaria"}),
        patch("app.buffer.processor.get_or_create_conversation", return_value={"id": "conv-1", "stage": "secretaria", "status": "active", "leads": {"id": "lead-1"}}),
        patch("app.buffer.processor.get_channel_by_id", return_value={"id": "channel-1", "agent_profiles": None}),
        patch("app.buffer.processor._is_recent_duplicate", return_value=False),
        patch("app.buffer.processor.get_active_enrollment", return_value=None),
        patch("app.buffer.processor.save_message"),
        patch("app.buffer.processor.get_supabase", return_value=mock_sb),
        patch("app.buffer.processor.get_provider", return_value=AsyncMock()),
        patch("app.buffer.processor._update_last_msg"),
        patch("app.buffer.processor.run_agent", new_callable=AsyncMock, return_value="agent response"),
        patch("app.buffer.processor._resolve_media", new_callable=AsyncMock, return_value="hello"),
    ):
        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("5511999999999", "hello", "channel-1")

    # Verify the update was called with last_customer_message_at on the correct lead
    update_calls = mock_sb.table.return_value.update.call_args_list
    assert len(update_calls) >= 1, "update() was never called on leads table"
    update_args = update_calls[0].args[0]
    assert "last_customer_message_at" in update_args, "last_customer_message_at not in update payload"
    assert update_args["last_customer_message_at"] is not None, "last_customer_message_at must not be None"
    mock_sb.table.return_value.update.return_value.eq.assert_called_with("id", "lead-1")

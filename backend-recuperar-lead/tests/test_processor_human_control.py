from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_human_control_skips_agent():
    """When lead.human_control is True, agent should NOT be called."""
    lead = {
        "id": "lead-123",
        "phone": "+5511999999999",
        "stage": "atacado",
        "status": "active",
        "human_control": True,
        "name": "João",
    }
    channel = {
        "id": "channel-1",
        "is_active": True,
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    conversation = {
        "id": "conv-1",
        "lead_id": "lead-123",
        "channel_id": "channel-1",
        "stage": "atacado",
        "status": "active",
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conversation), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"):

        mock_provider = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi quero comprar", "channel-1")

        mock_agent.assert_not_called()
        # user message saved even under human_control
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        # save_message(conversation_id, lead_id, role, content, stage)
        # positional arg index 2 is role
        assert call_kwargs.args[2] == "user"


@pytest.mark.asyncio
async def test_agent_called_when_no_human_control():
    """When lead.human_control is False and agent_profile present, agent runs."""
    lead = {
        "id": "lead-456",
        "phone": "+5511888888888",
        "stage": "secretaria",
        "status": "active",
        "human_control": False,
        "name": None,
    }
    channel = {
        "id": "channel-2",
        "is_active": True,
        "agent_profiles": {"id": "p2", "stages": {"secretaria": {"prompt": "test", "model": "gemini-2.0-flash", "tools": []}}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    conversation = {
        "id": "conv-2",
        "lead_id": "lead-456",
        "channel_id": "channel-2",
        "stage": "secretaria",
        "status": "active",
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conversation), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent", return_value="Oi! Como posso ajudar?") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"):

        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511888888888", "oi", "channel-2")

        mock_agent.assert_called_once()
        # user message saved before agent
        assert mock_save.call_count >= 1
        first_call = mock_save.call_args_list[0]
        # save_message(conversation_id, lead_id, role, content, stage)
        assert first_call.args[2] == "user"

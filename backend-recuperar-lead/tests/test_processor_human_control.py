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
        "provider_config": {},
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel), \
         patch("app.buffer.processor.get_whatsapp_client") as mock_wa_factory, \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor.update_lead"), \
         patch("app.buffer.processor.get_supabase"):

        mock_wa = AsyncMock()
        mock_wa_factory.return_value = mock_wa

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi quero comprar", "channel-1")

        mock_agent.assert_not_called()
        mock_save.assert_called_once()  # message saved but agent not called

# backend/tests/test_outbound_dispatcher.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_dispatch_uses_provider_send_text():
    """dispatcher must call provider.send_text, not httpx directly."""
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.xxx"}]})

    mock_channel = {
        "id": "chan-001",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }

    with patch("app.outbound.dispatcher.get_provider", return_value=mock_provider), \
         patch("app.outbound.dispatcher.get_channel_by_id", return_value=mock_channel), \
         patch("app.outbound.dispatcher.get_or_create_lead", return_value={"id": "lead-001"}), \
         patch("app.outbound.dispatcher.update_lead"), \
         patch("app.outbound.dispatcher.get_or_create_conversation", return_value={"id": "conv-001"}), \
         patch("app.outbound.dispatcher.update_conversation"), \
         patch("app.outbound.dispatcher.save_message"):

        from app.outbound.dispatcher import dispatch_to_lead

        result = await dispatch_to_lead(
            phone="+5511999990000",
            lead_context={"channel_id": "chan-001"},
        )

    mock_provider.send_text.assert_called_once()
    assert result["status"] == "sent"
    assert result["phone"] == "+5511999990000"


@pytest.mark.asyncio
async def test_dispatch_raises_without_channel_id():
    from app.outbound.dispatcher import dispatch_to_lead
    with pytest.raises(ValueError, match="channel_id"):
        await dispatch_to_lead(phone="+5511999990000", lead_context={})

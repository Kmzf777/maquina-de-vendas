from unittest.mock import AsyncMock, patch, MagicMock
import pytest


@pytest.mark.asyncio
async def test_dispatch_sends_template_saves_message_and_sets_status():
    """dispatch_to_lead should POST to Meta API, save message, and set lead+conversation status."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"messages": [{"id": "wamid.123"}]}

    mock_lead = {
        "id": "lead-abc",
        "phone": "+5511999999999",
        "stage": "secretaria",
        "status": "imported",
        "name": None,
    }
    mock_conversation = {
        "id": "conv-xyz",
        "lead_id": "lead-abc",
        "channel_id": "channel-1",
        "status": "template_sent",
        "stage": "secretaria",
    }

    with patch("app.outbound.dispatcher.settings") as mock_settings, \
         patch("app.outbound.dispatcher.get_or_create_lead", return_value=mock_lead), \
         patch("app.outbound.dispatcher.update_lead") as mock_update_lead, \
         patch("app.outbound.dispatcher.get_or_create_conversation", return_value=mock_conversation) as mock_get_conv, \
         patch("app.outbound.dispatcher.update_conversation") as mock_update_conv, \
         patch("app.outbound.dispatcher.save_message") as mock_save, \
         patch("httpx.AsyncClient") as mock_client_class:

        mock_settings.meta_access_token = "test-token"
        mock_settings.meta_phone_number_id = "123456"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        from app.outbound.dispatcher import dispatch_to_lead
        result = await dispatch_to_lead("+5511999999999", {"channel_id": "channel-1"})

        assert result["status"] == "sent"
        assert result["phone"] == "+5511999999999"
        mock_client.post.assert_called_once()
        mock_save.assert_called_once()
        # Lead status updated to template_sent
        mock_update_lead.assert_called_once_with("lead-abc", status="template_sent")
        # Conversation status updated to template_sent
        mock_update_conv.assert_called_once_with("conv-xyz", status="template_sent")
        # Verify get_or_create_conversation was called with correct args
        mock_get_conv.assert_called_once_with("lead-abc", "channel-1")


@pytest.mark.asyncio
async def test_dispatch_missing_token_raises():
    """dispatch_to_lead should raise ValueError when META_ACCESS_TOKEN is not set."""
    with patch("app.outbound.dispatcher.settings") as mock_settings:
        mock_settings.meta_access_token = ""
        mock_settings.meta_phone_number_id = "123456"

        from app.outbound.dispatcher import dispatch_to_lead
        with pytest.raises(ValueError, match="META_ACCESS_TOKEN"):
            await dispatch_to_lead("+5511999999999", {})


@pytest.mark.asyncio
async def test_dispatch_missing_channel_id_raises():
    """dispatch_to_lead should raise ValueError when channel_id is not in lead_context."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"messages": [{"id": "wamid.123"}]}

    mock_lead = {
        "id": "lead-abc",
        "phone": "+5511999999999",
        "stage": "secretaria",
        "status": "imported",
        "name": None,
    }

    with patch("app.outbound.dispatcher.settings") as mock_settings, \
         patch("app.outbound.dispatcher.get_or_create_lead", return_value=mock_lead), \
         patch("app.outbound.dispatcher.update_lead"), \
         patch("httpx.AsyncClient") as mock_client_class:

        mock_settings.meta_access_token = "test-token"
        mock_settings.meta_phone_number_id = "123456"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        from app.outbound.dispatcher import dispatch_to_lead
        with pytest.raises(ValueError, match="channel_id is required"):
            await dispatch_to_lead("+5511999999999", {})

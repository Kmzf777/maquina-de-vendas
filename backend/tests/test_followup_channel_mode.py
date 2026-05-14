"""Tests for channel mode='human' guard in follow_up scheduler."""
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
import pytest


def _make_job(channel_mode="ai"):
    return {
        "id": "job-1",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 1,
        "leads": {
            "id": "lead-1",
            "phone": "+5511999999999",
            "last_customer_message_at": datetime.now(timezone.utc).isoformat(),
        },
        "channels": {
            "id": "ch-1",
            "name": "Canal Comercial",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"},
            "mode": channel_mode,
        },
        "conversations": {
            "id": "conv-1",
            "stage": "atacado",
            "followup_enabled": True,
        },
    }


@pytest.mark.asyncio
async def test_human_channel_cancels_followup_job():
    """Canal mode='human': job é cancelado com razão human_channel."""
    job = _make_job(channel_mode="human")

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message"):

        mock_provider_fn.return_value = AsyncMock()

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_called_once_with("job-1", "human_channel")
        mock_sent.assert_not_called()


@pytest.mark.asyncio
async def test_ai_channel_processes_followup_job():
    """Canal mode='ai': job segue normalmente."""
    job = _make_job(channel_mode="ai")

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value="Oi, tudo bem?"):

        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_not_called()
        mock_sent.assert_called_once_with("job-1")
        mock_provider.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_channel_without_mode_processes_followup_job():
    """Canal sem campo mode (legado): funciona como 'ai'."""
    job = _make_job()
    del job["channels"]["mode"]  # simula canal legado sem o campo

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value="Oi!"):

        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_not_called()
        mock_sent.assert_called_once_with("job-1")

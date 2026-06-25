"""Tests for the per-channel (per-conversation) 24h attendance window.

Regression context: the 24h window was tracked by a single global field
`leads.last_customer_message_at`, so a lead with a recent inbound on channel A
appeared to have an open window on channel B too. The window source of truth
moved to `conversations.last_customer_message_at` (per lead+channel pair).
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# --- save_message: writes the per-conversation window on inbound user messages ---

def _mock_sb_for_save():
    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "m1"}]
    return mock_sb


def _conversation_update_payloads(mock_sb):
    return [c.args[0] for c in mock_sb.table.return_value.update.call_args_list if c.args]


def test_save_message_sets_conversation_window_for_user_message():
    """A customer (role='user') message must stamp conversations.last_customer_message_at."""
    mock_sb = _mock_sb_for_save()
    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message
        save_message("conv-1", "lead-1", "user", "oi", sent_by="user")

    payloads = _conversation_update_payloads(mock_sb)
    assert any("last_customer_message_at" in p for p in payloads), (
        "user message did not stamp conversations.last_customer_message_at"
    )
    stamped = next(p for p in payloads if "last_customer_message_at" in p)
    assert stamped["last_customer_message_at"] is not None


def test_save_message_does_not_set_window_for_assistant_message():
    """Our own (assistant) messages must NOT move the customer window."""
    mock_sb = _mock_sb_for_save()
    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message
        save_message("conv-1", "lead-1", "assistant", "ola", sent_by="agent")

    payloads = _conversation_update_payloads(mock_sb)
    assert not any("last_customer_message_at" in p for p in payloads), (
        "assistant message must not stamp the customer window"
    )


# --- _compute_window_expiration: reads the conversation field, not the lead field ---

def test_compute_window_expiration_uses_conversation_field():
    """Expiration is derived from the conversation's own last_customer_message_at."""
    from app.conversations.service import _compute_window_expiration
    last = datetime.now(timezone.utc).isoformat()
    conv = {"last_customer_message_at": last, "leads": {"last_customer_message_at": None}}
    assert _compute_window_expiration(conv) is not None


def test_compute_window_expiration_ignores_lead_global_field():
    """A recent lead-global value must NOT open the window for a conversation
    whose own channel had no recent inbound."""
    from app.conversations.service import _compute_window_expiration
    recent = datetime.now(timezone.utc).isoformat()
    conv = {"last_customer_message_at": None, "leads": {"last_customer_message_at": recent}}
    assert _compute_window_expiration(conv) is None


# --- follow-up scheduler: the 24h guard uses the per-conversation window ---

def _make_followup_job(conv_window, lead_window, job_type=None):
    job = {
        "id": "job-1",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 1,
        "leads": {"id": "lead-1", "phone": "+5511999999999", "last_customer_message_at": lead_window},
        "channels": {
            "id": "ch-1",
            "name": "Canal A",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"},
            "mode": "ai",
        },
        "conversations": {
            "id": "conv-1",
            "stage": "atacado",
            "followup_enabled": True,
            "last_customer_message_at": conv_window,
        },
    }
    if job_type:
        job["job_type"] = job_type
    return job


@pytest.mark.asyncio
async def test_followup_cancels_when_channel_window_expired_despite_recent_lead_global():
    """Per-channel: conversation window expired must cancel the job even when the
    lead's GLOBAL last_customer_message_at (other channel) is fresh."""
    now = datetime.now(timezone.utc)
    job = _make_followup_job(
        conv_window=(now - timedelta(hours=25)).isoformat(),  # this channel: expired
        lead_window=now.isoformat(),                          # other channel: fresh
    )
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.get_provider", return_value=AsyncMock()), \
         patch("app.follow_up.scheduler.save_message"):
        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=now)

    mock_cancel.assert_called_once_with("job-1", "window_expired")
    mock_sent.assert_not_called()


@pytest.mark.asyncio
async def test_followup_proceeds_when_channel_window_open_despite_null_lead_global():
    """Per-channel: conversation window open must let the job proceed even when the
    lead's GLOBAL field is null."""
    now = datetime.now(timezone.utc)
    job = _make_followup_job(
        conv_window=(now - timedelta(hours=1)).isoformat(),  # this channel: open
        lead_window=None,                                    # global: never set
    )
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value=("Oi!", "stop")):
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        with patch("app.follow_up.scheduler.get_provider", return_value=mock_provider):
            from app.follow_up.scheduler import process_due_followups
            await process_due_followups(now=now)

    mock_cancel.assert_not_called()
    mock_sent.assert_called_once_with("job-1")


@pytest.mark.asyncio
async def test_ai_reengage_uses_conversation_window():
    """ai_reengage 24h guard reads the per-conversation window: expired channel
    window cancels even with a fresh lead-global value."""
    now = datetime.now(timezone.utc)
    job = _make_followup_job(
        conv_window=(now - timedelta(hours=30)).isoformat(),  # this channel: expired
        lead_window=now.isoformat(),                          # global: fresh
        job_type="ai_reengage",
    )
    mock_sb = MagicMock()
    # Re-read of the lead returns ai_enabled True + the fresh global value.
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "lead-1", "phone": "+5511999999999", "name": "Fulano",
        "ai_enabled": True, "last_customer_message_at": now.isoformat(), "metadata": {},
    }
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent:
        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=now)

    mock_cancel.assert_called_once_with("job-1", "window_expired")
    mock_sent.assert_not_called()


# --- automation cadence: send_text 24h guard is per-channel ---

@pytest.mark.asyncio
async def test_automation_send_text_blocked_by_expired_channel_window():
    """_execute_send_text must block when the conversation window for the campaign's
    channel is expired — independent of any lead-global value."""
    now = datetime.now(timezone.utc)
    enrollment = {"id": "enr-1", "lead_id": "lead-1"}
    node = {"config": {"message_text": "oi", "channel_id": "ch-1"}}
    lead = {"id": "lead-1", "phone": "+5511999999999",
            "last_customer_message_at": now.isoformat()}  # global fresh — must be ignored
    campaign = {"channel_id": "ch-1"}

    mock_sb = MagicMock()
    # conversation window for (lead, channel) is expired
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"last_customer_message_at": (now - timedelta(hours=30)).isoformat()}
    ]
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock()

    with patch("app.automation.engine.get_supabase", return_value=mock_sb), \
         patch("app.automation.engine._update") as mock_update, \
         patch("app.whatsapp.registry.get_provider", return_value=mock_provider):
        from app.automation.engine import _execute_send_text
        await _execute_send_text(enrollment, node, lead, now, campaign)

    mock_provider.send_text.assert_not_called()
    assert any(
        kw.get("last_error") == "24h_window_expired"
        for _, kw in mock_update.call_args_list
    ), "expected enrollment to be marked 24h_window_expired"

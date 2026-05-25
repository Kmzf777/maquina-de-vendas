"""Tests for the followup_enabled gate that prevents cadence from acting
on conversations that the seller manually finalized via /conversas."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.automation.engine import _conversation_followup_disabled, _process_one
from app.automation.triggers import _safe_enroll, fire_trigger
from app.campaigns.worker import handle_campaign_reply


def _sb_with_conversation(followup_enabled: bool | None):
    """Mock supabase that returns a single conversation row with the given flag."""
    sb = MagicMock()
    if followup_enabled is None:
        rows = []
    else:
        rows = [{"followup_enabled": followup_enabled}]
    (
        sb.table.return_value
          .select.return_value
          .eq.return_value
          .eq.return_value
          .limit.return_value
          .execute.return_value.data
    ) = rows
    return sb


class TestConversationFollowupDisabledHelper:
    def test_returns_false_when_channel_id_is_none(self):
        with patch("app.automation.engine.get_supabase") as m:
            result = _conversation_followup_disabled("lead-1", None)
        assert result is False
        m.assert_not_called()

    def test_returns_false_when_no_conversation_exists(self):
        sb = _sb_with_conversation(None)
        with patch("app.automation.engine.get_supabase", return_value=sb):
            result = _conversation_followup_disabled("lead-1", "channel-1")
        assert result is False

    def test_returns_false_when_followup_enabled_true(self):
        sb = _sb_with_conversation(True)
        with patch("app.automation.engine.get_supabase", return_value=sb):
            result = _conversation_followup_disabled("lead-1", "channel-1")
        assert result is False

    def test_returns_true_when_followup_enabled_false(self):
        sb = _sb_with_conversation(False)
        with patch("app.automation.engine.get_supabase", return_value=sb):
            result = _conversation_followup_disabled("lead-1", "channel-1")
        assert result is True


class TestProcessOneRespectsFollowupGate:
    @pytest.mark.asyncio
    async def test_pauses_enrollment_when_conversation_finalized(self):
        sb_followup = _sb_with_conversation(False)
        enrollment = {
            "id": "e1",
            "lead_id": "lead-1",
            "leads": {"id": "lead-1", "phone": "5511999", "ai_enabled": True},
            "campaign_nodes": {"id": "n1", "type": "send", "config": {}},
            "campaigns": {"id": "c1", "status": "active", "channel_id": "channel-1"},
        }
        with patch("app.automation.engine.get_supabase", return_value=sb_followup), \
             patch("app.automation.engine._update") as mock_update:
            from datetime import datetime, timezone
            await _process_one(enrollment, datetime.now(timezone.utc))
        # Expect: enrollment paused with explanatory last_error, no further processing
        mock_update.assert_called_once()
        kwargs = mock_update.call_args.kwargs
        assert kwargs.get("status") == "paused"
        assert "conversation_finalized" in (kwargs.get("last_error") or "")

    @pytest.mark.asyncio
    async def test_proceeds_normally_when_conversation_active(self):
        """When followup_enabled=true, _process_one continues to its normal logic."""
        sb_followup = _sb_with_conversation(True)
        enrollment = {
            "id": "e1",
            "lead_id": "lead-1",
            "leads": {"id": "lead-1", "phone": "5511999", "ai_enabled": True},
            "campaign_nodes": {"id": "n1", "type": "end", "config": {}},
            "campaigns": {"id": "c1", "status": "active", "channel_id": "channel-1"},
        }
        with patch("app.automation.engine.get_supabase", return_value=sb_followup), \
             patch("app.automation.engine._complete") as mock_complete, \
             patch("app.automation.engine._execute_end"):
            from datetime import datetime, timezone
            await _process_one(enrollment, datetime.now(timezone.utc))
        # Reached end node — completed normally, NOT paused
        mock_complete.assert_called_once_with("e1")


class TestSafeEnrollRespectsFollowupGate:
    def test_skips_create_enrollment_when_conversation_finalized(self):
        trigger_node = {
            "campaign_id": "c1",
            "next_node_id": "n2",
            "channel_id": "channel-1",
            "config": {"trigger_type": "no_message", "days": 30},
            "type": "trigger",
        }
        from datetime import datetime, timezone
        with patch("app.automation.engine._conversation_followup_disabled", return_value=True), \
             patch("app.automation.triggers.create_enrollment") as mock_create:
            _safe_enroll(trigger_node, "lead-1", datetime.now(timezone.utc))
        mock_create.assert_not_called()

    def test_creates_enrollment_when_conversation_active(self):
        trigger_node = {
            "campaign_id": "c1",
            "next_node_id": "n2",
            "channel_id": "channel-1",
            "config": {"trigger_type": "no_message", "days": 30},
            "type": "trigger",
        }
        from datetime import datetime, timezone
        with patch("app.automation.engine._conversation_followup_disabled", return_value=False), \
             patch("app.automation.triggers.create_enrollment") as mock_create:
            _safe_enroll(trigger_node, "lead-1", datetime.now(timezone.utc))
        mock_create.assert_called_once()


class TestKeywordReceivedRespectsFollowupGate:
    @pytest.mark.asyncio
    async def test_skips_enrollment_when_conversation_finalized(self):
        active_trigger_nodes = [{
            "id": "node1",
            "campaign_id": "camp1",
            "next_node_id": "node2",
            "channel_id": "channel-1",
            "config": {"trigger_type": "keyword_received", "keywords": ["preço"]},
        }]
        with patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=active_trigger_nodes), \
             patch("app.automation.triggers.is_already_enrolled", return_value=False), \
             patch("app.automation.engine._conversation_followup_disabled", return_value=True), \
             patch("app.automation.triggers.create_enrollment") as mock_create:
            await fire_trigger("message_received", lead_id="lead1", data={"body": "Qual o PREÇO?"})
        mock_create.assert_not_called()


class TestHandleCampaignReplyUniversal:
    def test_pauses_enrollment_when_current_node_is_wait(self):
        enrollment = {"id": "e1", "campaign_nodes": {"type": "wait", "config": {"days": 5}}}
        with patch("app.campaigns.service.get_active_enrollment_for_lead", return_value=enrollment), \
             patch("app.campaigns.worker.pause_enrollment") as mock_pause, \
             patch("app.campaigns.worker.cancel_enrollment") as mock_cancel:
            handle_campaign_reply("lead-1")
        mock_pause.assert_called_once_with("e1")
        mock_cancel.assert_not_called()

    def test_pauses_enrollment_when_current_node_is_condition(self):
        enrollment = {"id": "e1", "campaign_nodes": {"type": "condition", "config": {}}}
        with patch("app.campaigns.service.get_active_enrollment_for_lead", return_value=enrollment), \
             patch("app.campaigns.worker.pause_enrollment") as mock_pause:
            handle_campaign_reply("lead-1")
        mock_pause.assert_called_once_with("e1")

    def test_cancels_when_send_with_on_reply_cancel(self):
        enrollment = {"id": "e1", "campaign_nodes": {"type": "send", "config": {"on_reply": "cancel"}}}
        with patch("app.campaigns.service.get_active_enrollment_for_lead", return_value=enrollment), \
             patch("app.campaigns.worker.cancel_enrollment") as mock_cancel, \
             patch("app.campaigns.worker.pause_enrollment") as mock_pause:
            handle_campaign_reply("lead-1")
        mock_cancel.assert_called_once_with("e1")
        mock_pause.assert_not_called()

    def test_pauses_when_send_with_on_reply_pause(self):
        enrollment = {"id": "e1", "campaign_nodes": {"type": "send", "config": {"on_reply": "pause"}}}
        with patch("app.campaigns.service.get_active_enrollment_for_lead", return_value=enrollment), \
             patch("app.campaigns.worker.pause_enrollment") as mock_pause:
            handle_campaign_reply("lead-1")
        mock_pause.assert_called_once_with("e1")

    def test_noop_when_no_active_enrollment(self):
        with patch("app.campaigns.service.get_active_enrollment_for_lead", return_value=None), \
             patch("app.campaigns.worker.pause_enrollment") as mock_pause:
            handle_campaign_reply("lead-1")
        mock_pause.assert_not_called()

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.cadence.scheduler import (
    process_due_cadences,
    process_reengagements,
    is_within_send_window,
    calculate_next_send_at,
)


class TestIsWithinSendWindow:
    def test_within_window(self):
        # 10:00 BRT (13:00 UTC) — within 7-18
        now_utc = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is True

    def test_before_window(self):
        # 05:00 BRT (08:00 UTC) — before 7
        now_utc = datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is False

    def test_after_window(self):
        # 19:00 BRT (22:00 UTC) — after 18
        now_utc = datetime(2026, 3, 28, 22, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is False

    def test_at_start_boundary(self):
        # 07:00 BRT (10:00 UTC) — exactly at start
        now_utc = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is True

    def test_at_end_boundary(self):
        # 18:00 BRT (21:00 UTC) — exactly at end, should be False (end is exclusive)
        now_utc = datetime(2026, 3, 28, 21, 0, tzinfo=timezone.utc)
        assert is_within_send_window(now_utc, start_hour=7, end_hour=18) is False


class TestCalculateNextSendAt:
    def test_next_send_within_window(self):
        # 10:00 BRT, interval 24h → tomorrow 10:00 BRT
        now_utc = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        result = calculate_next_send_at(now_utc, interval_hours=24, start_hour=7, end_hour=18)
        expected = datetime(2026, 3, 29, 13, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_next_send_lands_before_window(self):
        # 08:00 BRT (11:00 UTC), interval 20h → would be 04:00 BRT next day → push to 07:00 BRT (10:00 UTC)
        now_utc = datetime(2026, 3, 28, 11, 0, tzinfo=timezone.utc)
        result = calculate_next_send_at(now_utc, interval_hours=20, start_hour=7, end_hour=18)
        expected = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_next_send_lands_after_window(self):
        # 17:00 BRT (20:00 UTC), interval 3h → would be 20:00 BRT → push to 07:00 BRT next day (10:00 UTC)
        now_utc = datetime(2026, 3, 28, 20, 0, tzinfo=timezone.utc)
        result = calculate_next_send_at(now_utc, interval_hours=3, start_hour=7, end_hour=18)
        expected = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
        assert result == expected


@pytest.fixture
def mock_deps():
    with patch("app.cadence.scheduler.get_due_cadences") as mock_due, \
         patch("app.cadence.scheduler.get_next_step") as mock_step, \
         patch("app.cadence.scheduler.advance_cadence") as mock_advance, \
         patch("app.cadence.scheduler.cool_cadence") as mock_cool, \
         patch("app.cadence.scheduler.exhaust_cadence") as mock_exhaust, \
         patch("app.cadence.scheduler.save_message") as mock_save_msg, \
         patch("app.cadence.scheduler.send_text", new_callable=AsyncMock) as mock_send, \
         patch("app.cadence.scheduler.get_supabase") as mock_sb:
        yield {
            "get_due": mock_due,
            "get_step": mock_step,
            "advance": mock_advance,
            "cool": mock_cool,
            "exhaust": mock_exhaust,
            "save_msg": mock_save_msg,
            "send": mock_send,
            "sb": mock_sb.return_value,
        }


class TestProcessDueCadences:
    @pytest.mark.anyio
    async def test_sends_message_and_advances(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)  # 10:00 BRT
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]
        mock_deps["get_step"].return_value = {
            "id": "step-1", "message_text": "Oi! Viu nosso catalogo?", "step_order": 1,
        }

        await process_due_cadences(now)

        mock_deps["send"].assert_called_once_with("5511999999999", "Oi! Viu nosso catalogo?")
        mock_deps["advance"].assert_called_once()
        mock_deps["save_msg"].assert_called_once()

    @pytest.mark.anyio
    async def test_skips_paused_campaign(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "paused", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]

        await process_due_cadences(now)

        mock_deps["send"].assert_not_called()

    @pytest.mark.anyio
    async def test_skips_human_controlled_lead(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": True},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]

        await process_due_cadences(now)

        mock_deps["send"].assert_not_called()

    @pytest.mark.anyio
    async def test_cools_when_no_more_steps(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 3,
            "total_messages_sent": 3,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]
        mock_deps["get_step"].return_value = None  # No more steps

        await process_due_cadences(now)

        mock_deps["cool"].assert_called_once_with("state-1")
        mock_deps["send"].assert_not_called()

    @pytest.mark.anyio
    async def test_exhausts_when_max_messages_reached(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 7,
            "total_messages_sent": 7,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]
        mock_deps["get_step"].return_value = {
            "id": "step-8", "message_text": "Ultima tentativa!", "step_order": 8,
        }

        await process_due_cadences(now)

        # Should send the message (it's the 8th = max) then exhaust
        mock_deps["send"].assert_called_once()
        mock_deps["exhaust"].assert_called_once_with("state-1")

    @pytest.mark.anyio
    async def test_skips_outside_send_window(self, mock_deps):
        now = datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc)  # 05:00 BRT — before window
        mock_deps["get_due"].return_value = [{
            "id": "state-1",
            "lead_id": "lead-1",
            "campaign_id": "camp-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "max_messages": 8,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "campaigns": {"status": "running", "cadence_send_start_hour": 7, "cadence_send_end_hour": 18, "cadence_interval_hours": 24},
        }]

        await process_due_cadences(now)

        mock_deps["send"].assert_not_called()


class TestProcessReengagements:
    @pytest.mark.anyio
    async def test_resumes_cadence_after_cooldown(self, mock_deps):
        now = datetime(2026, 3, 30, 13, 0, tzinfo=timezone.utc)

        with patch("app.cadence.scheduler.get_reengagement_cadences") as mock_reengage, \
             patch("app.cadence.scheduler.resume_cadence") as mock_resume:
            mock_reengage.return_value = [{
                "id": "state-1",
                "lead_id": "lead-1",
                "campaign_id": "camp-1",
                "responded_at": "2026-03-28T13:00:00+00:00",
                "total_messages_sent": 2,
                "max_messages": 8,
                "current_step": 0,
                "leads": {"phone": "5511999999999", "last_msg_at": "2026-03-28T13:00:00+00:00", "human_control": False},
                "campaigns": {"status": "running", "cadence_cooldown_hours": 48},
            }]

            await process_reengagements(now)

            mock_resume.assert_called_once()

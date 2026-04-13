import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
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
        # 10:00 BRT (13:00 UTC), delay 1 day → tomorrow 10:00 BRT (13:00 UTC)
        now_utc = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        result = calculate_next_send_at(now_utc, delay_days=1, start_hour=7, end_hour=18)
        expected = datetime(2026, 3, 29, 13, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_next_send_lands_before_window(self):
        # 04:00 BRT (07:00 UTC), delay 0 days → push to 07:00 BRT (10:00 UTC)
        now_utc = datetime(2026, 3, 28, 7, 0, tzinfo=timezone.utc)
        result = calculate_next_send_at(now_utc, delay_days=0, start_hour=7, end_hour=18)
        expected = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_next_send_lands_after_window(self):
        # 19:00 BRT (22:00 UTC), delay 0 days — after window → push to 07:00 BRT next day (10:00 UTC)
        now_utc = datetime(2026, 3, 28, 22, 0, tzinfo=timezone.utc)
        result = calculate_next_send_at(now_utc, delay_days=0, start_hour=7, end_hour=18)
        expected = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
        assert result == expected


@pytest.fixture
def mock_deps():
    with patch("app.cadence.scheduler.get_due_enrollments") as mock_due, \
         patch("app.cadence.scheduler.get_next_step") as mock_step, \
         patch("app.cadence.scheduler.advance_enrollment") as mock_advance, \
         patch("app.cadence.scheduler.complete_enrollment") as mock_complete, \
         patch("app.cadence.scheduler.exhaust_enrollment") as mock_exhaust, \
         patch("app.cadence.scheduler.save_message") as mock_save_msg, \
         patch("app.cadence.scheduler.send_text", new_callable=AsyncMock) as mock_send, \
         patch("app.cadence.scheduler.asyncio.sleep", new_callable=AsyncMock):
        yield {
            "get_due": mock_due,
            "get_step": mock_step,
            "advance": mock_advance,
            "complete": mock_complete,
            "exhaust": mock_exhaust,
            "save_msg": mock_save_msg,
            "send": mock_send,
        }


class TestProcessDueCadences:
    @pytest.mark.anyio
    async def test_sends_message_and_advances(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)  # 10:00 BRT
        mock_deps["get_due"].return_value = [{
            "id": "enroll-1",
            "lead_id": "lead-1",
            "cadence_id": "cad-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False, "name": "João", "company": None},
            "cadences": {"status": "active", "send_start_hour": 7, "send_end_hour": 18, "max_messages": 8},
        }]
        mock_deps["get_step"].side_effect = [
            {"id": "step-1", "message_text": "Oi! Viu nosso catalogo?", "step_order": 1},
            {"id": "step-2", "message_text": "Segundo contato", "step_order": 2, "delay_days": 1},
        ]

        await process_due_cadences(now)

        mock_deps["send"].assert_called_once_with("5511999999999", "Oi! Viu nosso catalogo?")
        mock_deps["advance"].assert_called_once_with(
            "enroll-1",
            new_step=1,
            total_sent=1,
            next_send_at=ANY,
        )
        mock_deps["save_msg"].assert_called_once()

    @pytest.mark.anyio
    async def test_skips_paused_campaign(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "enroll-1",
            "lead_id": "lead-1",
            "cadence_id": "cad-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "cadences": {"status": "paused", "send_start_hour": 7, "send_end_hour": 18, "max_messages": 8},
        }]

        await process_due_cadences(now)

        mock_deps["send"].assert_not_called()

    @pytest.mark.anyio
    async def test_skips_human_controlled_lead(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "enroll-1",
            "lead_id": "lead-1",
            "cadence_id": "cad-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": True},
            "cadences": {"status": "active", "send_start_hour": 7, "send_end_hour": 18, "max_messages": 8},
        }]

        await process_due_cadences(now)

        mock_deps["send"].assert_not_called()

    @pytest.mark.anyio
    async def test_completes_when_no_more_steps(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "enroll-1",
            "lead_id": "lead-1",
            "cadence_id": "cad-1",
            "current_step": 3,
            "total_messages_sent": 3,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "cadences": {"status": "active", "send_start_hour": 7, "send_end_hour": 18, "max_messages": 8},
        }]
        mock_deps["get_step"].return_value = None  # No more steps

        await process_due_cadences(now)

        mock_deps["complete"].assert_called_once_with("enroll-1")
        mock_deps["send"].assert_not_called()

    @pytest.mark.anyio
    async def test_exhausts_when_max_messages_reached(self, mock_deps):
        now = datetime(2026, 3, 28, 13, 0, tzinfo=timezone.utc)
        mock_deps["get_due"].return_value = [{
            "id": "enroll-1",
            "lead_id": "lead-1",
            "cadence_id": "cad-1",
            "current_step": 7,
            "total_messages_sent": 7,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False, "name": None, "company": None},
            "cadences": {"status": "active", "send_start_hour": 7, "send_end_hour": 18, "max_messages": 8},
        }]
        mock_deps["get_step"].return_value = {
            "id": "step-8", "message_text": "Ultima tentativa!", "step_order": 8,
        }

        await process_due_cadences(now)

        # Should send the message (it's the 8th = max) then exhaust
        mock_deps["send"].assert_called_once()
        mock_deps["exhaust"].assert_called_once_with("enroll-1")

    @pytest.mark.anyio
    async def test_skips_outside_send_window(self, mock_deps):
        now = datetime(2026, 3, 28, 8, 0, tzinfo=timezone.utc)  # 05:00 BRT — before window
        mock_deps["get_due"].return_value = [{
            "id": "enroll-1",
            "lead_id": "lead-1",
            "cadence_id": "cad-1",
            "current_step": 0,
            "total_messages_sent": 0,
            "leads": {"phone": "5511999999999", "stage": "atacado", "human_control": False},
            "cadences": {"status": "active", "send_start_hour": 7, "send_end_hour": 18, "max_messages": 8},
        }]

        await process_due_cadences(now)

        mock_deps["send"].assert_not_called()


class TestProcessReengagements:
    @pytest.mark.anyio
    async def test_resumes_enrollment_after_cooldown(self, mock_deps):
        now = datetime(2026, 3, 30, 13, 0, tzinfo=timezone.utc)

        with patch("app.cadence.scheduler.get_reengagement_enrollments") as mock_reengage, \
             patch("app.cadence.scheduler.resume_enrollment") as mock_resume:
            mock_reengage.return_value = [{
                "id": "enroll-1",
                "lead_id": "lead-1",
                "cadence_id": "cad-1",
                "responded_at": "2026-03-28T13:00:00+00:00",
                "total_messages_sent": 2,
                "current_step": 0,
                "leads": {"phone": "5511999999999", "last_msg_at": "2026-03-28T13:00:00+00:00", "human_control": False},
                "cadences": {"status": "active", "cooldown_hours": 48},
            }]

            await process_reengagements(now)

            mock_resume.assert_called_once()

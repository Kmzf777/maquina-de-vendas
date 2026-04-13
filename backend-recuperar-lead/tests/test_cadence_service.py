import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.cadence.service import (
    create_enrollment,
    get_active_enrollment,
    pause_enrollment,
    resume_enrollment,
    advance_enrollment,
    exhaust_enrollment,
    complete_enrollment,
    get_next_step,
    get_due_enrollments,
    get_reengagement_enrollments,
    is_enrolled,
)


@pytest.fixture
def mock_sb():
    with patch("app.cadence.service.get_supabase") as mock:
        sb = MagicMock()
        mock.return_value = sb
        yield sb


class TestCreateEnrollment:
    def test_creates_enrollment_with_correct_fields(self, mock_sb):
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "enroll-1", "cadence_id": "cad-1", "lead_id": "lead-1", "status": "active"}
        ]
        next_send = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)

        result = create_enrollment("cad-1", "lead-1", next_send_at=next_send)

        mock_sb.table.assert_called_with("cadence_enrollments")
        insert_call = mock_sb.table.return_value.insert.call_args[0][0]
        assert insert_call["cadence_id"] == "cad-1"
        assert insert_call["lead_id"] == "lead-1"
        assert insert_call["status"] == "active"
        assert insert_call["current_step"] == 0
        assert insert_call["total_messages_sent"] == 0
        assert result["id"] == "enroll-1"

    def test_creates_enrollment_with_deal_id(self, mock_sb):
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "enroll-2", "cadence_id": "cad-1", "lead_id": "lead-1", "deal_id": "deal-1", "status": "active"}
        ]
        result = create_enrollment("cad-1", "lead-1", deal_id="deal-1")
        insert_call = mock_sb.table.return_value.insert.call_args[0][0]
        assert insert_call["deal_id"] == "deal-1"
        assert result["deal_id"] == "deal-1"


class TestGetActiveEnrollment:
    def test_returns_active_enrollment_for_lead(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "enroll-1", "status": "active"}
        ]
        result = get_active_enrollment("lead-1")
        assert result["status"] == "active"

    def test_returns_none_when_no_active_enrollment(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        result = get_active_enrollment("lead-1")
        assert result is None


class TestPauseEnrollment:
    def test_sets_responded_status(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "enroll-1", "status": "responded"}
        ]
        result = pause_enrollment("enroll-1")
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "responded"
        assert "responded_at" in update_call


class TestResumeEnrollment:
    def test_sets_active_status_resets_step(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "enroll-1", "status": "active"}
        ]
        next_send = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)
        result = resume_enrollment("enroll-1", next_send_at=next_send)
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "active"
        assert update_call["current_step"] == 0
        assert update_call["cooldown_until"] is None


class TestAdvanceEnrollment:
    def test_increments_step_and_messages_sent(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "enroll-1", "current_step": 2, "total_messages_sent": 2}
        ]
        next_send = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
        result = advance_enrollment("enroll-1", new_step=2, total_sent=2, next_send_at=next_send)
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["current_step"] == 2
        assert update_call["total_messages_sent"] == 2
        assert "next_send_at" in update_call


class TestExhaustEnrollment:
    def test_sets_exhausted_status(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "enroll-1", "status": "exhausted"}
        ]
        result = exhaust_enrollment("enroll-1")
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "exhausted"
        assert "completed_at" in update_call


class TestCompleteEnrollment:
    def test_sets_completed_status(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "enroll-1", "status": "completed"}
        ]
        result = complete_enrollment("enroll-1")
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "completed"
        assert "completed_at" in update_call


class TestGetNextStep:
    def test_returns_step_for_cadence_and_order(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "step-1", "message_text": "Oi, tudo bem?", "step_order": 1}
        ]
        result = get_next_step("cad-1", step_order=1)
        assert result["message_text"] == "Oi, tudo bem?"

    def test_returns_none_when_no_more_steps(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        result = get_next_step("cad-1", step_order=99)
        assert result is None


class TestGetDueEnrollments:
    def test_returns_active_enrollments_due_now(self, mock_sb):
        now = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)
        mock_sb.table.return_value.select.return_value.eq.return_value.lte.return_value.limit.return_value.execute.return_value.data = [
            {"id": "enroll-1", "lead_id": "lead-1"}
        ]
        result = get_due_enrollments(now, limit=10)
        assert len(result) == 1


class TestGetReengagementEnrollments:
    def test_returns_responded_enrollments_past_cooldown(self, mock_sb):
        now = datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc)
        mock_sb.table.return_value.select.return_value.eq.return_value.lte.return_value.limit.return_value.execute.return_value.data = [
            {"id": "enroll-1", "lead_id": "lead-1", "status": "responded"}
        ]
        result = get_reengagement_enrollments(now)
        assert len(result) == 1


class TestIsEnrolled:
    def test_returns_true_when_enrolled(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.limit.return_value.execute.return_value.data = [
            {"id": "enroll-1"}
        ]
        assert is_enrolled("cad-1", "lead-1") is True

    def test_returns_false_when_not_enrolled(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.limit.return_value.execute.return_value.data = []
        assert is_enrolled("cad-1", "lead-1") is False

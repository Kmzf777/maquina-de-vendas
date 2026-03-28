import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.cadence.service import (
    create_cadence_state,
    get_cadence_state,
    pause_cadence,
    resume_cadence,
    advance_cadence,
    exhaust_cadence,
    cool_cadence,
    get_next_step,
    get_due_cadences,
    get_reengagement_cadences,
)


@pytest.fixture
def mock_sb():
    with patch("app.cadence.service.get_supabase") as mock:
        sb = MagicMock()
        mock.return_value = sb
        yield sb


class TestCreateCadenceState:
    def test_creates_state_with_correct_fields(self, mock_sb):
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "state-1", "lead_id": "lead-1", "campaign_id": "camp-1", "status": "active"}
        ]
        next_send = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)

        result = create_cadence_state("lead-1", "camp-1", max_messages=8, next_send_at=next_send)

        mock_sb.table.assert_called_with("cadence_state")
        insert_call = mock_sb.table.return_value.insert.call_args[0][0]
        assert insert_call["lead_id"] == "lead-1"
        assert insert_call["campaign_id"] == "camp-1"
        assert insert_call["status"] == "active"
        assert insert_call["current_step"] == 0
        assert insert_call["total_messages_sent"] == 0
        assert insert_call["max_messages"] == 8
        assert result["id"] == "state-1"


class TestGetCadenceState:
    def test_returns_state_for_lead(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "state-1", "status": "active"}
        ]
        result = get_cadence_state("lead-1")
        assert result["status"] == "active"

    def test_returns_none_when_no_state(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        result = get_cadence_state("lead-1")
        assert result is None


class TestPauseCadence:
    def test_sets_responded_status(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "state-1", "status": "responded"}
        ]
        result = pause_cadence("state-1")
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "responded"
        assert "responded_at" in update_call


class TestResumeCadence:
    def test_sets_active_status_and_next_send(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "state-1", "status": "active"}
        ]
        next_send = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)
        result = resume_cadence("state-1", next_send_at=next_send)
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "active"
        assert update_call["cooldown_until"] is None


class TestAdvanceCadence:
    def test_increments_step_and_messages_sent(self, mock_sb):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "state-1", "current_step": 2, "total_messages_sent": 2}
        ]
        next_send = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
        result = advance_cadence("state-1", new_step=2, total_sent=2, next_send_at=next_send)
        update_call = mock_sb.table.return_value.update.call_args[0][0]
        assert update_call["current_step"] == 2
        assert update_call["total_messages_sent"] == 2


class TestGetNextStep:
    def test_returns_step_for_campaign_stage_order(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "step-1", "message_text": "Oi, tudo bem?", "step_order": 1}
        ]
        result = get_next_step("camp-1", "atacado", step_order=1)
        assert result["message_text"] == "Oi, tudo bem?"

    def test_returns_none_when_no_more_steps(self, mock_sb):
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        result = get_next_step("camp-1", "atacado", step_order=99)
        assert result is None


class TestGetDueCadences:
    def test_returns_active_cadences_due_now(self, mock_sb):
        now = datetime(2026, 3, 28, 10, 0, tzinfo=timezone.utc)
        mock_sb.table.return_value.select.return_value.eq.return_value.lte.return_value.limit.return_value.execute.return_value.data = [
            {"id": "state-1", "lead_id": "lead-1"}
        ]
        result = get_due_cadences(now, limit=10)
        assert len(result) == 1


class TestGetReengagementCadences:
    def test_returns_responded_cadences_past_cooldown(self, mock_sb):
        now = datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc)
        mock_sb.table.return_value.select.return_value.eq.return_value.lte.return_value.execute.return_value.data = [
            {"id": "state-1", "lead_id": "lead-1", "status": "responded"}
        ]
        result = get_reengagement_cadences(now)
        assert len(result) == 1

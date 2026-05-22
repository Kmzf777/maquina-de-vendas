import pytest
from unittest.mock import patch, MagicMock
from app.automation.engine import _execute_action


def _mock_sb_with_deals(deal_id="d1"):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": deal_id, "lead_id": "lead1"}
    ]
    return sb


class TestMarkDealWon:
    def test_updates_latest_deal_to_won_stage(self):
        sb = _mock_sb_with_deals()
        with patch("app.automation.engine.get_supabase", return_value=sb):
            enrollment = {"id": "e1", "lead_id": "lead1"}
            node = {"config": {"action_type": "mark_deal_won", "stage_id": "stage-won"}}
            lead = {"id": "lead1", "phone": "5511999"}
            _execute_action(enrollment, node, lead)
        # Espera-se 2 chamadas: select para pegar o deal, update no deal
        sb.table.assert_any_call("deals")
        update_calls = [c for c in sb.table.return_value.update.call_args_list]
        assert any(call[0][0].get("stage_id") == "stage-won" for call in update_calls)


class TestMarkDealLost:
    def test_updates_latest_deal_to_lost_stage(self):
        sb = _mock_sb_with_deals()
        with patch("app.automation.engine.get_supabase", return_value=sb):
            enrollment = {"id": "e1", "lead_id": "lead1"}
            node = {"config": {"action_type": "mark_deal_lost", "stage_id": "stage-lost"}}
            lead = {"id": "lead1", "phone": "5511999"}
            _execute_action(enrollment, node, lead)
        update_calls = [c for c in sb.table.return_value.update.call_args_list]
        assert any(call[0][0].get("stage_id") == "stage-lost" for call in update_calls)


class TestMarkDealNoDeal:
    def test_noop_when_no_deal_exists(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        with patch("app.automation.engine.get_supabase", return_value=sb):
            enrollment = {"id": "e1", "lead_id": "lead1"}
            node = {"config": {"action_type": "mark_deal_won", "stage_id": "stage-won"}}
            lead = {"id": "lead1", "phone": "5511999"}
            _execute_action(enrollment, node, lead)
        # Não deve chamar update se não houver deal
        sb.table.return_value.update.assert_not_called()


class TestAddNote:
    def test_inserts_note_with_substituted_text(self):
        sb = MagicMock()
        with patch("app.automation.engine.get_supabase", return_value=sb):
            enrollment = {"id": "e1", "lead_id": "lead1"}
            node = {"config": {"action_type": "add_note", "note_template": "Cliente {{lead.name}} respondeu"}}
            lead = {"id": "lead1", "name": "João", "phone": "5511999"}
            _execute_action(enrollment, node, lead)
        sb.table.assert_any_call("lead_notes")
        insert_call = sb.table.return_value.insert.call_args
        assert insert_call is not None
        payload = insert_call[0][0]
        assert payload["lead_id"] == "lead1"
        assert "João" in payload["content"]

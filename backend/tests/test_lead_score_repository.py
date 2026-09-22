from unittest.mock import MagicMock, patch

import pytest

from app.lead_score.repository import ScoreWriteConflictError, save_score_evidence


def _response(row):
    response = MagicMock()
    response.data = [row]
    return response


def test_save_merges_partial_updates_and_recalculates_snapshot():
    """A partial live update must retain earlier criteria and evidence."""
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _response({
        "lead_id": "lead-1",
        "segment": "cafeteria",
        "monthly_volume_kg": None,
        "supplier_reason": None,
        "purchase_timing": None,
        "purchase_intent": None,
        "evidence": {"segment": {"text": "Tenho uma cafeteria"}},
        "source": "live",
    })
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = _response({"lead_id": "lead-1"})

    with patch("app.lead_score.repository.get_supabase", return_value=client):
        result = save_score_evidence(
            "lead-1",
            {"monthly_volume_kg": 30},
            {"monthly_volume_kg": {"text": "Uso 30 kg por mês"}},
        )

    assert result["normal_score"] == 3
    payload = client.table.return_value.update.call_args.args[0]
    assert payload["segment"] == "cafeteria"
    assert payload["monthly_volume_kg"] == 30
    assert payload["evidence"] == {
        "segment": {"text": "Tenho uma cafeteria"},
        "monthly_volume_kg": {"text": "Uso 30 kg por mês"},
    }


def test_backfill_fills_unknown_live_criteria_without_overwriting_live_values():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _response({
        "lead_id": "lead-1",
        "segment": "cafeteria",
        "monthly_volume_kg": None,
        "supplier_reason": None,
        "purchase_timing": None,
        "purchase_intent": None,
        "evidence": {"segment": {"text": "Tenho uma cafeteria"}},
        "source": "live",
    })
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = _response({"lead_id": "lead-1"})

    with patch("app.lead_score.repository.get_supabase", return_value=client):
        result = save_score_evidence(
            "lead-1",
            {"segment": "other", "monthly_volume_kg": 30},
            {"segment": {"text": "loja"}, "monthly_volume_kg": {"text": "30 kg/mês"}},
            source="backfill",
        )

    assert result["segment"] == "cafeteria"
    assert result["monthly_volume_kg"] == 30
    assert result["source"] == "live"
    payload = client.table.return_value.update.call_args.args[0]
    assert payload["evidence"] == {
        "segment": {"text": "Tenho uma cafeteria"},
        "monthly_volume_kg": {"text": "30 kg/mês"},
    }


def test_known_accepted_criterion_requires_literal_evidence():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _response(None)
    with patch("app.lead_score.repository.get_supabase", return_value=client), pytest.raises(ValueError, match="monthly_volume_kg"):
        save_score_evidence("lead-1", {"monthly_volume_kg": 30})

    with patch("app.lead_score.repository.get_supabase", return_value=client), pytest.raises(ValueError, match="text"):
        save_score_evidence("lead-1", {"monthly_volume_kg": 30}, {"monthly_volume_kg": {"text": "   "}})


def test_unchanged_backfill_does_not_write():
    client = MagicMock()
    existing = {
        "lead_id": "lead-1",
        "segment": "cafeteria",
        "monthly_volume_kg": 30,
        "supplier_reason": "other",
        "purchase_timing": "no_timeline",
        "purchase_intent": "unclear",
        "evidence": {"segment": {"text": "cafeteria"}},
        "normal_score": 3,
        "final_score": 3,
        "priority": "moderate",
        "is_provisional": False,
        "source": "backfill",
        "updated_at": "2026-09-21T12:00:00Z",
    }
    client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _response(existing)

    with patch("app.lead_score.repository.get_supabase", return_value=client):
        result = save_score_evidence("lead-1", {"segment": "cafeteria"}, source="backfill")

    assert result == existing
    client.table.return_value.update.assert_not_called()
    client.table.return_value.insert.assert_not_called()


def test_backfill_re_reads_after_compare_and_set_loss_before_returning_live_snapshot():
    client = MagicMock()
    stale = {
        "lead_id": "lead-1", "segment": None, "monthly_volume_kg": None,
        "supplier_reason": None, "purchase_timing": None, "purchase_intent": None,
        "evidence": {}, "normal_score": 0, "final_score": 0, "priority": "low",
        "is_provisional": True, "source": "backfill", "updated_at": "old",
    }
    live = {
        "lead_id": "lead-1", "segment": None, "monthly_volume_kg": 50,
        "supplier_reason": None, "purchase_timing": None, "purchase_intent": None,
        "evidence": {"monthly_volume_kg": {"text": "50 kg"}},
        "normal_score": 0, "final_score": 0, "priority": "low",
        "is_provisional": True, "source": "live", "updated_at": "new",
    }
    select_execute = client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute
    select_execute.side_effect = [_response(stale), _response(live)]
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = _response(None)

    with patch("app.lead_score.repository.get_supabase", return_value=client):
        result = save_score_evidence(
            "lead-1",
            {"monthly_volume_kg": 30},
            {"monthly_volume_kg": {"text": "30 kg"}},
            source="backfill",
        )

    assert result == live
    assert client.table.return_value.update.call_count == 1


def test_database_error_is_propagated_instead_of_returning_an_unsaved_snapshot():
    client = MagicMock()
    existing = {
        "lead_id": "lead-1", "segment": None, "monthly_volume_kg": None,
        "supplier_reason": None, "purchase_timing": None, "purchase_intent": None,
        "evidence": {}, "source": "live", "updated_at": "old",
    }
    client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _response(existing)
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = OSError("database offline")

    with patch("app.lead_score.repository.get_supabase", return_value=client), pytest.raises(OSError, match="offline"):
        save_score_evidence("lead-1", {"monthly_volume_kg": 30}, {"monthly_volume_kg": {"text": "30 kg"}})


def test_repeated_compare_and_set_loss_raises_conflict():
    client = MagicMock()
    existing = {
        "lead_id": "lead-1", "segment": None, "monthly_volume_kg": None,
        "supplier_reason": None, "purchase_timing": None, "purchase_intent": None,
        "evidence": {}, "source": "live", "updated_at": "old",
    }
    client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _response(existing)
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = _response(None)

    with patch("app.lead_score.repository.get_supabase", return_value=client), pytest.raises(ScoreWriteConflictError):
        save_score_evidence("lead-1", {"monthly_volume_kg": 30}, {"monthly_volume_kg": {"text": "30 kg"}})

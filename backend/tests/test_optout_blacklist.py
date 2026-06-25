"""Tests for opt-out Blacklist move (Task 2.3).

Covers:
- move_lead_deals_to_blacklist: update path, insert fallback, fail-soft
- registrar_optout tool: call order — update_lead, move_lead_deals_to_blacklist, cancel_followups_by_phone
"""
import logging
from unittest.mock import MagicMock, patch, call

import pytest

from app.leads.service import (
    BLACKLIST_PIPELINE_ID,
    BLACKLIST_STAGE_ID,
    move_lead_deals_to_blacklist,
)
from app.agent.tools import execute_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sb_mock(update_data=None, insert_data=None):
    """Build a mock supabase client for leads service tests.

    update_data: list returned by .update().eq().execute().data
    insert_data: list returned by .insert().execute().data (for fallback)
    """
    sb = MagicMock()

    # --- update chain ---
    update_result = MagicMock()
    update_result.data = update_data if update_data is not None else []
    eq_after_update = MagicMock()
    eq_after_update.execute.return_value = update_result
    update_mock = MagicMock()
    update_mock.eq.return_value = eq_after_update
    sb.table.return_value.update.return_value = update_mock

    # --- insert chain (fallback) ---
    insert_result = MagicMock()
    insert_result.data = insert_data if insert_data is not None else [{"id": "deal-new"}]
    insert_mock = MagicMock()
    insert_mock.execute.return_value = insert_result
    sb.table.return_value.insert.return_value = insert_mock

    return sb


# ---------------------------------------------------------------------------
# move_lead_deals_to_blacklist — update path (deals exist)
# ---------------------------------------------------------------------------

def test_move_lead_deals_to_blacklist_updates_existing_deals():
    """When deals exist, update is called with Blacklist pipeline+stage for the lead."""
    fake_deal = {"id": "deal-1", "lead_id": "lead-abc", "pipeline_id": "old", "stage_id": "old-stage"}
    sb = _make_sb_mock(update_data=[fake_deal])

    with patch("app.leads.service.get_supabase", return_value=sb):
        move_lead_deals_to_blacklist("lead-abc")

    # Assert update was called on deals table
    sb.table.assert_any_call("deals")
    update_call = sb.table.return_value.update.call_args
    assert update_call is not None
    payload = update_call[0][0]
    assert payload["pipeline_id"] == BLACKLIST_PIPELINE_ID
    assert payload["stage_id"] == BLACKLIST_STAGE_ID
    assert "updated_at" in payload

    # eq filter must reference the correct lead
    eq_call = sb.table.return_value.update.return_value.eq.call_args
    assert eq_call[0] == ("lead_id", "lead-abc")


def test_move_lead_deals_to_blacklist_uses_correct_blacklist_ids():
    """Blacklist constants must match the confirmed production UUIDs."""
    assert BLACKLIST_PIPELINE_ID == "8988e852-2836-4add-b023-4db4d6cd0e6e"
    assert BLACKLIST_STAGE_ID == "fbace13d-d788-423a-879d-ee468dff29ed"


# ---------------------------------------------------------------------------
# move_lead_deals_to_blacklist — insert fallback (no deals)
# ---------------------------------------------------------------------------

def test_move_lead_deals_to_blacklist_inserts_when_no_deals_exist():
    """When no deals exist (update returns empty list), insert a tracking deal in Blacklist."""
    lead_data = {"id": "lead-xyz", "name": "Maria", "phone": "5511999990000"}

    sb = MagicMock()

    # update chain — returns empty list (no deals)
    update_result = MagicMock()
    update_result.data = []
    eq_after_update = MagicMock()
    eq_after_update.execute.return_value = update_result
    update_mock = MagicMock()
    update_mock.eq.return_value = eq_after_update
    sb.table.return_value.update.return_value = update_mock

    # insert chain
    insert_result = MagicMock()
    insert_result.data = [{"id": "deal-opt-new"}]
    insert_mock = MagicMock()
    insert_mock.execute.return_value = insert_result
    sb.table.return_value.insert.return_value = insert_mock

    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=lead_data):
        move_lead_deals_to_blacklist("lead-xyz")

    # insert must have been called with Blacklist ids
    insert_call = sb.table.return_value.insert.call_args
    assert insert_call is not None, "insert should have been called when no deals existed"
    inserted = insert_call[0][0]
    assert inserted["lead_id"] == "lead-xyz"
    assert inserted["pipeline_id"] == BLACKLIST_PIPELINE_ID
    assert inserted["stage_id"] == BLACKLIST_STAGE_ID
    assert "Opt-out" in inserted["title"]
    assert "Maria" in inserted["title"]


def test_move_lead_deals_to_blacklist_insert_uses_phone_when_no_name():
    """Fallback insert uses phone when lead has no name."""
    lead_data = {"id": "lead-noname", "name": None, "phone": "5511888880000"}

    sb = MagicMock()

    update_result = MagicMock()
    update_result.data = []
    eq_after_update = MagicMock()
    eq_after_update.execute.return_value = update_result
    update_mock = MagicMock()
    update_mock.eq.return_value = eq_after_update
    sb.table.return_value.update.return_value = update_mock

    insert_result = MagicMock()
    insert_result.data = [{"id": "deal-noname"}]
    insert_mock = MagicMock()
    insert_mock.execute.return_value = insert_result
    sb.table.return_value.insert.return_value = insert_mock

    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=lead_data):
        move_lead_deals_to_blacklist("lead-noname")

    insert_call = sb.table.return_value.insert.call_args
    inserted = insert_call[0][0]
    assert "5511888880000" in inserted["title"] or "Opt-out" in inserted["title"]


# ---------------------------------------------------------------------------
# move_lead_deals_to_blacklist — fail-soft
# ---------------------------------------------------------------------------

def test_move_lead_deals_to_blacklist_fail_soft_on_exception(caplog):
    """Exception inside move_lead_deals_to_blacklist must be caught — never raised."""
    sb = MagicMock()
    sb.table.return_value.update.side_effect = RuntimeError("db exploded")

    with patch("app.leads.service.get_supabase", return_value=sb):
        caplog.set_level(logging.ERROR, logger="app.leads.service")
        # Must NOT raise
        move_lead_deals_to_blacklist("lead-boom")

    assert any(
        "move_lead_deals_to_blacklist" in rec.message and rec.levelname == "ERROR"
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# apply_optout_side_effects — shared helper (move blacklist + cancel follow-ups)
# ---------------------------------------------------------------------------

def test_apply_optout_side_effects_moves_and_cancels():
    """Helper moves deals to Blacklist and cancels follow-ups with the given reason."""
    from app.leads.service import apply_optout_side_effects

    with patch("app.leads.service.move_lead_deals_to_blacklist") as mock_move, \
         patch("app.follow_up.service.cancel_followups_by_phone") as mock_cancel:
        apply_optout_side_effects("lead-h1", "5511999990000", reason="optout")

    mock_move.assert_called_once_with("lead-h1")
    mock_cancel.assert_called_once_with("5511999990000", reason="optout")


def test_apply_optout_side_effects_skips_cancel_without_phone():
    """No phone → blacklist still runs, cancel_followups is skipped."""
    from app.leads.service import apply_optout_side_effects

    with patch("app.leads.service.move_lead_deals_to_blacklist") as mock_move, \
         patch("app.follow_up.service.cancel_followups_by_phone") as mock_cancel:
        apply_optout_side_effects("lead-h2", "", reason="optout")

    mock_move.assert_called_once_with("lead-h2")
    mock_cancel.assert_not_called()


def test_apply_optout_side_effects_cancel_fail_soft(caplog):
    """If cancel_followups raises, the helper must not raise (fail-soft)."""
    from app.leads.service import apply_optout_side_effects

    with patch("app.leads.service.move_lead_deals_to_blacklist"), \
         patch("app.follow_up.service.cancel_followups_by_phone", side_effect=RuntimeError("redis down")):
        caplog.set_level(logging.ERROR, logger="app.leads.service")
        apply_optout_side_effects("lead-h3", "5511333330003", reason="optout")  # must not raise

    assert any(
        "apply_optout_side_effects" in rec.message and rec.levelname == "ERROR"
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# registrar_optout tool — delegates to apply_optout_side_effects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registrar_optout_calls_side_effects_after_update_lead():
    """registrar_optout must call apply_optout_side_effects(lead_id, phone, reason='optout') after update_lead."""
    call_order = []

    def fake_update_lead(lead_id, **kwargs):
        call_order.append(("update_lead", lead_id, kwargs))

    def fake_side_effects(lead_id, phone, reason):
        call_order.append(("side_effects", lead_id, phone, reason))

    with patch("app.agent.tools.update_lead", side_effect=fake_update_lead), \
         patch("app.agent.tools.apply_optout_side_effects", side_effect=fake_side_effects), \
         patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "registrar_optout",
            {"motivo": "clicou parar mensagens"},
            lead_id="lead-order-1",
            phone="5511111110001",
            conversation_id="conv-order-1",
        )

    assert result == "Opt-out registrado."
    assert call_order[0] == ("update_lead", "lead-order-1", {"ai_enabled": False, "opt_out": True})
    assert call_order[1] == ("side_effects", "lead-order-1", "5511111110001", "optout")


@pytest.mark.asyncio
async def test_registrar_optout_update_lead_failure_skips_side_effects():
    """If update_lead fails (early return), apply_optout_side_effects must NOT be called."""
    with patch("app.agent.tools.update_lead", side_effect=RuntimeError("db dead")), \
         patch("app.agent.tools.apply_optout_side_effects") as mock_side, \
         patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "registrar_optout",
            {"motivo": "opt-out"},
            lead_id="lead-earlyreturn",
            phone="5511555550005",
        )

    assert "ERRO" in result or "erro" in result.lower()
    mock_side.assert_not_called()

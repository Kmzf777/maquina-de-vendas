"""Tests for follow-up gate: schedule_followup is called only when interest is marked.

We test process_buffered_messages using the same mocking pattern as the existing
test_processor_channel_mode.py and test_processor_errors.py tests. The key assertion
is that _schedule_followup is or is not called depending on whether
pop_interest_marked returns a signal.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_lead():
    return {
        "id": "lead-fg-1",
        "phone": "+5511999999999",
        "stage": "atacado",
        "status": "active",
        "ai_enabled": True,
        "name": "Teste",
    }


def _make_channel():
    return {
        "id": "ch-fg-1",
        "is_active": True,
        "mode": "ai",
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }


def _make_conversation(followup_enabled=True):
    return {
        "id": "conv-fg-1",
        "lead_id": "lead-fg-1",
        "channel_id": "ch-fg-1",
        "stage": "atacado",
        "status": "active",
        "followup_enabled": followup_enabled,
    }


def _make_supabase_mock():
    return MagicMock(
        table=MagicMock(return_value=MagicMock(
            update=MagicMock(return_value=MagicMock(
                eq=MagicMock(return_value=MagicMock(execute=MagicMock(return_value=MagicMock()))),
            )),
            select=MagicMock(return_value=MagicMock(
                eq=MagicMock(return_value=MagicMock(
                    single=MagicMock(return_value=MagicMock(
                        execute=MagicMock(return_value=MagicMock(data={"unread_count": 0}))
                    ))
                ))
            )),
        ))
    )


def _mock_settings():
    """Settings stub that disables the ai_phone_number_id channel gate (mirrors test_processor_errors.py)."""
    s = MagicMock()
    s.ai_phone_number_id = None
    s.ai_phone_number_ids = frozenset()
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_followup_scheduled_when_interest_marked():
    """_schedule_followup is called when marcar_interesse was called during the turn."""
    interest_signal = {"nivel": "quente", "motivo": "perguntou preço"}

    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="Claro, vou te passar os valores!"), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.pop_interest_marked", return_value=interest_signal), \
         patch("app.buffer.processor.pop_deferred_media", return_value=[]), \
         patch("app.buffer.processor.get_supabase", return_value=_make_supabase_mock()), \
         patch("app.buffer.processor.settings", _mock_settings()), \
         patch("app.buffer.processor._check_frustration_guardrail", return_value=False), \
         patch("app.buffer.processor._update_last_msg"):

        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "qual o preço do atacado?", "ch-fg-1")

        mock_followup.assert_called_once_with(
            conversation_id="conv-fg-1",
            lead_id="lead-fg-1",
            channel_id="ch-fg-1",
        )


@pytest.mark.asyncio
async def test_followup_not_scheduled_when_no_interest():
    """_schedule_followup is NOT called when marcar_interesse was not called (no interest signal)."""

    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="Obrigado pelo contato!"), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.pop_interest_marked", return_value=None), \
         patch("app.buffer.processor.pop_deferred_media", return_value=[]), \
         patch("app.buffer.processor.get_supabase", return_value=_make_supabase_mock()), \
         patch("app.buffer.processor.settings", _mock_settings()), \
         patch("app.buffer.processor._check_frustration_guardrail", return_value=False), \
         patch("app.buffer.processor._update_last_msg"):

        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "ok obrigado", "ch-fg-1")

        mock_followup.assert_not_called()


@pytest.mark.asyncio
async def test_followup_not_scheduled_when_followup_disabled():
    """_schedule_followup is NOT called when followup_enabled=False even with interest."""
    interest_signal = {"nivel": "quente", "motivo": "pediu orçamento"}

    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation",
               return_value=_make_conversation(followup_enabled=False)), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="Vou te passar o orçamento agora."), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.pop_interest_marked", return_value=interest_signal), \
         patch("app.buffer.processor.pop_deferred_media", return_value=[]), \
         patch("app.buffer.processor.get_supabase", return_value=_make_supabase_mock()), \
         patch("app.buffer.processor.settings", _mock_settings()), \
         patch("app.buffer.processor._check_frustration_guardrail", return_value=False), \
         patch("app.buffer.processor._update_last_msg"):

        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "me manda o orçamento", "ch-fg-1")

        mock_followup.assert_not_called()


@pytest.mark.asyncio
async def test_followup_flag_cleared_on_handoff_path():
    """pop_interest_marked is still called on the handoff path (response=None) to avoid leaks."""

    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value=None), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.pop_interest_marked") as mock_pop_interest, \
         patch("app.buffer.processor.pop_deferred_media", return_value=[]), \
         patch("app.buffer.processor.get_supabase", return_value=_make_supabase_mock()), \
         patch("app.buffer.processor.settings", _mock_settings()), \
         patch("app.buffer.processor._check_frustration_guardrail", return_value=False), \
         patch("app.buffer.processor._update_last_msg"):

        mock_pop_interest.return_value = None
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        # Neutral text — frustration guardrail is patched anyway
        await process_buffered_messages("+5511999999999", "tudo bem obrigado", "ch-fg-1")

        # pop must have been called to drain any stale flag
        mock_pop_interest.assert_called_once_with("conv-fg-1")
        # no follow-up on handoff
        mock_followup.assert_not_called()

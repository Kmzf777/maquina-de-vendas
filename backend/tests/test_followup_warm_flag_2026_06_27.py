"""Erro 3 (processor): warm flag propagado a schedule_followup conforme interesse marcado."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_lead():
    return {"id": "lead-w", "phone": "+5511988887777", "stage": "atacado",
            "status": "active", "ai_enabled": True, "name": "Teste"}


def _make_channel():
    return {"id": "ch-w", "is_active": True, "mode": "ai",
            "agent_profiles": {"id": "p1", "stages": {}},
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"}}


def _make_conversation():
    return {"id": "conv-w", "lead_id": "lead-w", "channel_id": "ch-w",
            "stage": "atacado", "status": "active", "followup_enabled": True}


def _make_supabase_mock():
    return MagicMock(table=MagicMock(return_value=MagicMock(
        update=MagicMock(return_value=MagicMock(eq=MagicMock(return_value=MagicMock(
            execute=MagicMock(return_value=MagicMock()))))),
        select=MagicMock(return_value=MagicMock(eq=MagicMock(return_value=MagicMock(
            single=MagicMock(return_value=MagicMock(
                execute=MagicMock(return_value=MagicMock(data={"unread_count": 0})))))))),
    )))


def _mock_settings():
    s = MagicMock()
    s.ai_phone_number_id = None
    s.ai_phone_number_ids = frozenset()
    return s


@pytest.mark.asyncio
async def test_warm_true_when_interest_marked():
    interest_signal = {"nivel": "quente", "motivo": "perguntou preço"}
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="claro, te passo os valores"), \
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
        await process_buffered_messages("+5511988887777", "qual o preço?", "ch-w")
        mock_followup.assert_called_once_with(
            conversation_id="conv-w", lead_id="lead-w", channel_id="ch-w", warm=True,
        )


@pytest.mark.asyncio
async def test_warm_false_when_outbound_engaged_without_interest():
    """Outbound engajou-e-esfriou sem interesse → agenda, mas warm=False (suprime T1 same-day)."""
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="boa, e como o café entra no seu negócio"), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.pop_interest_marked", return_value=None), \
         patch("app.buffer.processor.pop_deferred_media", return_value=[]), \
         patch("app.buffer.processor.get_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_supabase", return_value=_make_supabase_mock()), \
         patch("app.buffer.processor.settings", _mock_settings()), \
         patch("app.buffer.processor._check_frustration_guardrail", return_value=False), \
         patch("app.buffer.processor.resolve_prompt_key", return_value="valeria_outbound"), \
         patch("app.buffer.processor._update_last_msg"):
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider
        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511988887777", "meu negócio", "ch-w")
        mock_followup.assert_called_once_with(
            conversation_id="conv-w", lead_id="lead-w", channel_id="ch-w", warm=False,
        )

"""Tests for channel mode='human' gate in processor."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_lead(ai_enabled=True):
    return {
        "id": "lead-1",
        "phone": "+5511999999999",
        "stage": "atacado",
        "status": "active",
        "ai_enabled": ai_enabled,
        "name": "Teste",
    }


def _make_channel(mode="ai"):
    return {
        "id": "ch-1",
        "is_active": True,
        "mode": mode,
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }


def _make_conversation():
    return {
        "id": "conv-1",
        "lead_id": "lead-1",
        "channel_id": "ch-1",
        "stage": "atacado",
        "status": "active",
        "followup_enabled": True,
    }


@pytest.mark.asyncio
async def test_human_channel_skips_agent():
    """Canal mode='human': run_agent nunca é chamado."""
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel(mode="human")), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.get_supabase") as mock_sb:

        mock_sb.return_value = MagicMock(
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
        mock_provider_fn.return_value = AsyncMock()

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi", "ch-1")

        mock_agent.assert_not_called()
        mock_followup.assert_not_called()


@pytest.mark.asyncio
async def test_human_channel_still_saves_user_message():
    """Canal mode='human': mensagem do usuário ainda é salva."""
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel(mode="human")), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent"), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup"), \
         patch("app.buffer.processor.get_supabase") as mock_sb:

        mock_sb.return_value = MagicMock(
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
        mock_provider_fn.return_value = AsyncMock()

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi tudo bem", "ch-1")

        assert mock_save.call_count == 1
        assert mock_save.call_args.args[2] == "user"


@pytest.mark.asyncio
async def test_ai_channel_runs_agent():
    """Canal mode='ai' (padrão): run_agent é chamado normalmente."""
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel(mode="ai")), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="Olá!") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup"), \
         patch("app.buffer.processor.get_supabase") as mock_sb:

        mock_sb.return_value = MagicMock(
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
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi", "ch-1")

        mock_agent.assert_called_once()


@pytest.mark.asyncio
async def test_channel_without_mode_runs_agent():
    """Canal sem campo mode (legado): funciona como 'ai'."""
    channel_without_mode = {
        "id": "ch-legado",
        "is_active": True,
        # sem 'mode'
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel_without_mode), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="Olá!") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup"), \
         patch("app.buffer.processor.get_supabase") as mock_sb:

        mock_sb.return_value = MagicMock(
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
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi", "ch-legado")

        mock_agent.assert_called_once()

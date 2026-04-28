import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


@pytest.mark.asyncio
async def test_processor_passa_metadata_como_lead_context():
    """process_buffered_messages deve passar lead.metadata como lead_context para run_agent."""
    from app.buffer.processor import process_buffered_messages

    lead_data = {
        "id": "lead-abc",
        "phone": "5511999990000",
        "stage": "secretaria",
        "status": "active",
        "human_control": False,
        "metadata": {"previous_stage": "secretaria", "notes": "interesse em atacado"},
    }
    conv_data = {
        "id": "conv-abc",
        "stage": "secretaria",
        "status": "active",
        "ai_enabled": True,
        "agent_profile_id": None,
    }

    captured = {}

    async def fake_run_agent(conv, text, lead_context=None, agent_profile_id=None):
        captured["lead_context"] = lead_context
        return "resposta"

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead_data), \
         patch("app.buffer.processor.get_channel_by_id", return_value={"id": "ch-1", "agent_profiles": None}), \
         patch("app.buffer.processor.get_provider") as mock_prov, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conv_data), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message", return_value={}), \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor.run_agent", side_effect=fake_run_agent), \
         patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)), \
         patch("app.buffer.processor.split_into_bubbles", return_value=["resposta"]):

        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_prov.return_value.send_text = AsyncMock()

        await process_buffered_messages("+5511999990000", "oi", channel_id="ch-1")

    assert captured.get("lead_context") == {"previous_stage": "secretaria", "notes": "interesse em atacado"}, (
        f"lead_context esperado era o metadata do lead, mas recebeu: {captured.get('lead_context')}"
    )


@pytest.mark.asyncio
async def test_processor_passa_dict_vazio_quando_metadata_none():
    """Se lead.metadata for None, lead_context deve ser {} (não None)."""
    from app.buffer.processor import process_buffered_messages

    lead_data = {
        "id": "lead-xyz",
        "phone": "5511888880000",
        "stage": "secretaria",
        "status": "active",
        "human_control": False,
        "metadata": None,
    }
    conv_data = {
        "id": "conv-xyz",
        "stage": "secretaria",
        "status": "active",
        "ai_enabled": True,
        "agent_profile_id": None,
    }

    captured = {}

    async def fake_run_agent(conv, text, lead_context=None, agent_profile_id=None):
        captured["lead_context"] = lead_context
        return "resposta"

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead_data), \
         patch("app.buffer.processor.get_channel_by_id", return_value={"id": "ch-2", "agent_profiles": None}), \
         patch("app.buffer.processor.get_provider") as mock_prov, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conv_data), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message", return_value={}), \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor.run_agent", side_effect=fake_run_agent), \
         patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)), \
         patch("app.buffer.processor.split_into_bubbles", return_value=["resposta"]):

        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_prov.return_value.send_text = AsyncMock()

        await process_buffered_messages("+5511888880000", "oi", channel_id="ch-2")

    assert captured.get("lead_context") == {}, (
        f"lead_context deveria ser {{}}, mas recebeu: {captured.get('lead_context')}"
    )

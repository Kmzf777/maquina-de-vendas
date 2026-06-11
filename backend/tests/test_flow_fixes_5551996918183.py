"""Tests for the three flow fixes introduced after investigation of lead 5551996918183.

Fix 1 — orchestrator returns None (sentinel) instead of "" when encaminhar_humano is called,
         so the processor can distinguish an intentional handoff from an unexpected empty response.

Fix 2 — orchestrator falls back to a tools=None call when the AI returns empty content
         after tool iterations (observed with Gemini + enviar_fotos).

Fix 3 — processor logs at WARNING (not INFO) for unexpected empty responses, and at INFO
         for intentional handoffs (None sentinel).
"""

import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fix 1: orchestrator returns None for encaminhar_humano
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_returns_none_when_encaminhar_humano_called():
    """run_agent must return None (not '') when encaminhar_humano is in tool_calls."""
    from app.agent.orchestrator import run_agent

    tool_call = MagicMock()
    tool_call.function.name = "encaminhar_humano"
    tool_call.function.arguments = '{"vendedor": "Joao", "motivo": "qualificado"}'
    tool_call.id = "tc-1"

    first_message = MagicMock()
    first_message.tool_calls = [tool_call]
    first_message.content = None

    first_response = MagicMock()
    first_response.choices = [MagicMock(message=first_message)]
    first_response.usage = None

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=first_response)

    conversation = {
        "id": "conv-handoff",
        "lead_id": "lead-handoff",
        "stage": "private_label",
        "leads": {"id": "lead-handoff", "phone": "5551996918183", "stage": "private_label"},
    }

    with patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-handoff", "ai_enabled": True}), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator._get_client", return_value=mock_client), \
         patch("app.agent.orchestrator.execute_tool", new=AsyncMock(return_value="encaminhado para Joao")):
        result = await run_agent(conversation, "quero fechar negocio")

    assert result is None, (
        f"run_agent deve retornar None (não '') quando encaminhar_humano é chamado, mas retornou: {result!r}"
    )


# ---------------------------------------------------------------------------
# Fix 2: orchestrator fallback when empty response after tool iterations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_fallback_when_empty_after_tool_iterations():
    """When AI returns empty content after a tool call, a second call without tools is made."""
    from app.agent.orchestrator import run_agent

    tool_call = MagicMock()
    tool_call.function.name = "enviar_fotos"
    tool_call.function.arguments = '{"categoria": "private_label"}'
    tool_call.id = "tc-foto"

    # First response: has a tool call
    msg_with_tool = MagicMock()
    msg_with_tool.tool_calls = [tool_call]
    msg_with_tool.content = None

    first_response = MagicMock()
    first_response.choices = [MagicMock(message=msg_with_tool)]
    first_response.usage = None

    # Second response (after tool execution): empty content — Gemini bug
    msg_empty = MagicMock()
    msg_empty.tool_calls = None
    msg_empty.content = ""

    second_response = MagicMock()
    second_response.choices = [MagicMock(message=msg_empty)]
    second_response.usage = None

    # Third response (fallback without tools): proper text
    msg_fallback = MagicMock()
    msg_fallback.content = "Aqui estao as fotos do private label!"

    third_response = MagicMock()
    third_response.choices = [MagicMock(message=msg_fallback)]
    third_response.usage = None

    call_count = {"n": 0}
    responses = [first_response, second_response, third_response]

    async def fake_create(**kwargs):
        resp = responses[call_count["n"]]
        call_count["n"] += 1
        return resp

    mock_client = AsyncMock()
    mock_client.chat.completions.create = fake_create

    conversation = {
        "id": "conv-foto",
        "lead_id": "lead-foto",
        "stage": "private_label",
        "leads": {"id": "lead-foto", "phone": "5511999990000", "stage": "private_label"},
    }

    with patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-foto", "ai_enabled": True}), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator._get_client", return_value=mock_client), \
         patch("app.agent.orchestrator.execute_tool", new=AsyncMock(return_value="fotos enviadas")):
        result = await run_agent(conversation, "me manda as fotos")

    assert result == "Aqui estao as fotos do private label!"
    assert call_count["n"] == 3, f"Esperava 3 chamadas ao LLM (tool, empty, fallback), mas fez {call_count['n']}"


@pytest.mark.asyncio
async def test_run_agent_no_fallback_when_no_tool_iterations():
    """Fallback is NOT triggered when there were no tool iterations (empty = genuinely empty)."""
    from app.agent.orchestrator import run_agent

    msg_empty = MagicMock()
    msg_empty.tool_calls = None
    msg_empty.content = ""

    response = MagicMock()
    response.choices = [MagicMock(message=msg_empty)]
    response.usage = None

    call_count = {"n": 0}

    async def fake_create(**kwargs):
        call_count["n"] += 1
        return response

    mock_client = AsyncMock()
    mock_client.chat.completions.create = fake_create

    conversation = {
        "id": "conv-empty",
        "lead_id": "lead-empty",
        "stage": "secretaria",
        "leads": {"id": "lead-empty", "phone": "5511999990000", "stage": "secretaria"},
    }

    with patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-empty", "ai_enabled": True}), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator._get_client", return_value=mock_client):
        result = await run_agent(conversation, "ola")

    assert result == ""
    assert call_count["n"] == 1, "Sem tool iterations, não deve fazer chamada extra de fallback"


# ---------------------------------------------------------------------------
# Fix 3: processor distinguishes None (handoff) from "" (unexpected empty)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_processor_logs_info_for_none_handoff_sentinel(caplog):
    """When run_agent returns None, processor logs at INFO level (intentional handoff)."""
    from app.buffer.processor import process_buffered_messages

    lead_data = {"id": "lead-ias", "phone": "+5551996918183", "ai_enabled": True, "human_control": False}
    conv_data = {
        "id": "conv-ias",
        "lead_id": "lead-ias",
        "stage": "private_label",
        "status": "active",
        "ai_enabled": True,
        "agent_profile_id": None,
    }
    # Include provider_config so the allowlist check can find a phone_number_id
    channel_data = {
        "id": "ch-1",
        "mode": "ai",
        "agent_profiles": None,
        "provider_config": {"phone_number_id": "test-ph-id"},
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead_data), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel_data), \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conv_data), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message", return_value={}), \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor.get_provider"), \
         patch("app.buffer.processor.run_agent", new=AsyncMock(return_value=None)), \
         patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)), \
         patch("app.buffer.processor.settings") as mock_settings:
        mock_settings.ai_phone_number_ids = []  # disable allowlist so channel gate is bypassed
        mock_settings.valeria_enabled = True
        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        with caplog.at_level(logging.INFO, logger="app.buffer.processor"):
            await process_buffered_messages("+5551996918183", "quero fechar", channel_id="ch-1")

    handoff_records = [r for r in caplog.records if "HANDOFF" in r.message and r.levelno == logging.INFO]
    assert handoff_records, "Esperava log INFO com 'HANDOFF' quando run_agent retorna None"

    warning_records = [r for r in caplog.records if "EMPTY RESPONSE" in r.message]
    assert not warning_records, "Não esperava log de EMPTY RESPONSE para retorno None (handoff intencional)"


@pytest.mark.asyncio
async def test_processor_logs_warning_for_empty_string_response(caplog):
    """When run_agent returns '', processor logs at WARNING level (unexpected empty)."""
    from app.buffer.processor import process_buffered_messages

    lead_data = {"id": "lead-x", "phone": "+5511999990000", "ai_enabled": True, "human_control": False}
    conv_data = {
        "id": "conv-x",
        "lead_id": "lead-x",
        "stage": "private_label",
        "status": "active",
        "ai_enabled": True,
        "agent_profile_id": None,
    }
    channel_data = {
        "id": "ch-2",
        "mode": "ai",
        "agent_profiles": None,
        "provider_config": {"phone_number_id": "test-ph-id-2"},
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead_data), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel_data), \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conv_data), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message", return_value={}), \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor.get_provider"), \
         patch("app.buffer.processor.run_agent", new=AsyncMock(return_value="")), \
         patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)), \
         patch("app.buffer.processor.settings") as mock_settings:
        mock_settings.ai_phone_number_ids = []  # disable allowlist
        mock_settings.valeria_enabled = True
        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        with caplog.at_level(logging.WARNING, logger="app.buffer.processor"):
            await process_buffered_messages("+5511999990000", "oi", channel_id="ch-2")

    warning_records = [r for r in caplog.records if "EMPTY RESPONSE" in r.message and r.levelno == logging.WARNING]
    assert warning_records, "Esperava log WARNING com 'EMPTY RESPONSE' quando run_agent retorna ''"

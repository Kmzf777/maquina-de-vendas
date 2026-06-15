"""
Tests for Task 2.5: contextual closing message after media tool calls.

Strategy:
1. Unit-test _empty_fallback_text directly (pure helper, no mocks needed).
2. Integration-style tests via run_agent with a mocked LLM client that returns
   a media tool_call then empty text — verify the correct fallback is chosen.
3. Prompt presence: build_base_prompt output contains the distinctive phrase from
   the new media-closing rule.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Unit tests for _empty_fallback_text (pure helper)
# ---------------------------------------------------------------------------

def test_empty_fallback_text_with_media_returns_media_message():
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_MEDIA
    result = _empty_fallback_text(media_tool_used=True)
    assert result == _SAFETY_FALLBACK_MEDIA


def test_empty_fallback_text_without_media_returns_generic_message():
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_MESSAGE
    result = _empty_fallback_text(media_tool_used=False)
    assert result == _SAFETY_FALLBACK_MESSAGE


def test_empty_fallback_text_messages_are_different():
    """The two fallback messages must be distinct so the choice is meaningful."""
    from app.agent.orchestrator import _SAFETY_FALLBACK_MEDIA, _SAFETY_FALLBACK_MESSAGE
    assert _SAFETY_FALLBACK_MEDIA != _SAFETY_FALLBACK_MESSAGE


def test_safety_fallback_media_constant_content():
    """Smoke-check: the media fallback contains a photo-related phrase."""
    from app.agent.orchestrator import _SAFETY_FALLBACK_MEDIA
    lower = _SAFETY_FALLBACK_MEDIA.lower()
    # Should reference something about photos or attention
    assert "foto" in lower or "imagem" in lower or "atenção" in lower or "chamou" in lower


# ---------------------------------------------------------------------------
# Integration: run_agent uses _SAFETY_FALLBACK_MEDIA after media tool + empty LLM
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, call_id: str = "tc-001") -> MagicMock:
    """Build a minimal OpenAI-style tool_call mock."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = "{}"
    return tc


def _make_response(content: str | None, tool_calls=None) -> MagicMock:
    """Build a minimal chat completion response mock."""
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    msg.model_dump.return_value = {
        "role": "assistant",
        "content": content,
        "tool_calls": None,
    }
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


@pytest.mark.asyncio
async def test_run_agent_media_tool_then_empty_uses_media_fallback():
    """LLM returns enviar_fotos tool_call then empty text → _SAFETY_FALLBACK_MEDIA."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_MEDIA

    conversation = {
        "id": "conv-media-001",
        "stage": "atacado",
        "leads": {
            "id": "lead-m01",
            "name": "Carla",
            "phone": "5511900000001",
            "ai_enabled": True,
        },
    }

    tool_call = _make_tool_call("enviar_fotos", "tc-enviar-001")

    # Call sequence:
    # 1st create → tool call (enviar_fotos)
    # 2nd create (after tool result) → empty text  [triggers AGENT EMPTY AFTER TOOLS]
    # 3rd create (fallback without tools) → empty   [triggers safety fallback]
    resp_with_tool = _make_response(content=None, tool_calls=[tool_call])
    resp_empty_after_tool = _make_response(content="", tool_calls=None)
    resp_empty_fallback = _make_response(content="", tool_calls=None)

    call_responses = [resp_with_tool, resp_empty_after_tool, resp_empty_fallback]
    call_index = {"i": 0}

    async def fake_create(**kwargs):
        resp = call_responses[call_index["i"]]
        call_index["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=[
        {
            "role": "user",
            "content": "me manda as fotos",
            "stage": "atacado",
            "created_at": "2026-01-01T10:00:00Z",
            "wamid": "wamid-x",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-m01",
             "phone": "5511900000001",
             "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="2 fotos enfileiradas para envio após o texto")), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(conversation, "me manda as fotos")

    assert result == _SAFETY_FALLBACK_MEDIA


@pytest.mark.asyncio
async def test_run_agent_non_media_tool_then_empty_uses_generic_fallback():
    """LLM calls a non-media tool then returns empty → _SAFETY_FALLBACK_MESSAGE."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_MESSAGE

    conversation = {
        "id": "conv-nonmedia-001",
        "stage": "secretaria",
        "leads": {
            "id": "lead-nm01",
            "name": "Bruno",
            "phone": "5511900000002",
            "ai_enabled": True,
        },
    }

    tool_call = _make_tool_call("marcar_interesse", "tc-interesse-001")

    resp_with_tool = _make_response(content=None, tool_calls=[tool_call])
    resp_empty_after_tool = _make_response(content="", tool_calls=None)
    resp_empty_fallback = _make_response(content="", tool_calls=None)

    call_responses = [resp_with_tool, resp_empty_after_tool, resp_empty_fallback]
    call_index = {"i": 0}

    async def fake_create(**kwargs):
        resp = call_responses[call_index["i"]]
        call_index["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=[
        {
            "role": "user",
            "content": "quero saber os preços",
            "stage": "secretaria",
            "created_at": "2026-01-01T10:00:00Z",
            "wamid": "wamid-y",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-nm01",
             "phone": "5511900000002",
             "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="interesse registrado")), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(conversation, "quero saber os preços")

    assert result == _SAFETY_FALLBACK_MESSAGE


@pytest.mark.asyncio
async def test_run_agent_enviar_foto_produto_also_triggers_media_fallback():
    """enviar_foto_produto (second media tool name) also selects _SAFETY_FALLBACK_MEDIA."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_MEDIA

    conversation = {
        "id": "conv-media-002",
        "stage": "atacado",
        "leads": {
            "id": "lead-m02",
            "name": "Diana",
            "phone": "5511900000003",
            "ai_enabled": True,
        },
    }

    tool_call = _make_tool_call("enviar_foto_produto", "tc-foto-prod-001")

    resp_with_tool = _make_response(content=None, tool_calls=[tool_call])
    resp_empty_after_tool = _make_response(content="", tool_calls=None)
    resp_empty_fallback = _make_response(content="", tool_calls=None)

    call_responses = [resp_with_tool, resp_empty_after_tool, resp_empty_fallback]
    call_index = {"i": 0}

    async def fake_create(**kwargs):
        resp = call_responses[call_index["i"]]
        call_index["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=[
        {
            "role": "user",
            "content": "tem foto do produto?",
            "stage": "atacado",
            "created_at": "2026-01-01T10:00:00Z",
            "wamid": "wamid-z",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-m02",
             "phone": "5511900000003",
             "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="foto do produto enfileirada para envio após o texto")), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(conversation, "tem foto do produto?")

    assert result == _SAFETY_FALLBACK_MEDIA


# ---------------------------------------------------------------------------
# Prompt presence test
# ---------------------------------------------------------------------------

def test_build_base_prompt_contains_media_closing_rule():
    """build_base_prompt must include the distinctive media-closing instruction."""
    from datetime import datetime, timezone, timedelta
    from app.agent.prompts.base import build_base_prompt

    now = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
    prompt = build_base_prompt(
        lead_name="Teste",
        lead_company=None,
        now=now,
    )
    # Check for a distinctive phrase from the new rule added to base.py
    assert "Fechamento obrigatorio apos envio de fotos" in prompt or \
           "NUNCA fique em silencio apos enviar midia" in prompt, (
        "A regra de fechamento após mídia não foi encontrada no prompt base."
    )

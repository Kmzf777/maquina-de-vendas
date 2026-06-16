"""
Tests for the contextual closing message after a SILENT funnel transition (mudar_stage).

Bug 2 (silent tool call): gemini-2.5-flash sometimes returns completion_tokens=0 right
after a mudar_stage tool call, leaving the lead mute even though the stage already changed.
The generic "verifico internamente" stall is nonsense after a silent transition — we want a
stage-coherent advance question instead (Solution 1), AND the agent must NEVER return empty
on a response turn, including a plain empty turn with no tool call (Solution 3 — atomicity).

Strategy mirrors test_post_media_closing.py:
1. Unit-test _empty_fallback_text directly (pure helper, no mocks).
2. Integration-style tests via run_agent with a mocked LLM client.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Unit tests for _empty_fallback_text (pure helper) — stage transition branch
# ---------------------------------------------------------------------------

def test_empty_fallback_after_atacado_transition_returns_stage_message():
    from app.agent.orchestrator import _empty_fallback_text, _STAGE_TRANSITION_FALLBACKS
    result = _empty_fallback_text(media_tool_used=False, transitioned_to_stage="atacado")
    assert result == _STAGE_TRANSITION_FALLBACKS["atacado"]


def test_stage_transition_takes_priority_over_media():
    """If the AI both moved stage AND queued media but went mute, the stage-coherent
    advance question wins — it is the semantically significant funnel event."""
    from app.agent.orchestrator import _empty_fallback_text, _STAGE_TRANSITION_FALLBACKS
    result = _empty_fallback_text(media_tool_used=True, transitioned_to_stage="atacado")
    assert result == _STAGE_TRANSITION_FALLBACKS["atacado"]


def test_no_transition_falls_back_to_generic():
    """Backward compatibility: no stage transition + no media → generic stall."""
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_MESSAGE
    assert _empty_fallback_text(media_tool_used=False, transitioned_to_stage=None) == _SAFETY_FALLBACK_MESSAGE


def test_unmapped_stage_falls_back_to_generic():
    """A transition to a stage without a dedicated message (e.g. secretaria) → generic."""
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_MESSAGE
    assert _empty_fallback_text(media_tool_used=False, transitioned_to_stage="secretaria") == _SAFETY_FALLBACK_MESSAGE


def test_all_commercial_stages_have_distinct_contextual_messages():
    """Each commercial funnel stage must have its own non-empty, distinct message."""
    from app.agent.orchestrator import _STAGE_TRANSITION_FALLBACKS
    for stage in ("atacado", "private_label", "exportacao", "consumo"):
        assert stage in _STAGE_TRANSITION_FALLBACKS, f"missing fallback for {stage}"
        assert _STAGE_TRANSITION_FALLBACKS[stage].strip()
    msgs = [_STAGE_TRANSITION_FALLBACKS[s] for s in ("atacado", "private_label", "exportacao", "consumo")]
    assert len(set(msgs)) == len(msgs), "stage messages must be distinct"


# ---------------------------------------------------------------------------
# Integration helpers (mirror test_post_media_closing.py)
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, arguments: str = "{}", call_id: str = "tc-001") -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def _make_response(content: str | None, tool_calls=None) -> MagicMock:
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    msg.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


# ---------------------------------------------------------------------------
# Integration: mudar_stage(atacado) then empty → contextual atacado fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_mudar_stage_then_empty_uses_stage_fallback():
    """Reproduces Elisangele/Ademilson/Renato: mudar_stage→atacado, then two empty
    completions. The agent must return the atacado-contextual advance, not silence."""
    from app.agent.orchestrator import run_agent, _STAGE_TRANSITION_FALLBACKS

    conversation = {
        "id": "conv-stage-001",
        "stage": "secretaria",
        "leads": {"id": "lead-s01", "name": "Renato", "phone": "5565996414453", "ai_enabled": True},
    }

    tool_call = _make_tool_call("mudar_stage", arguments='{"stage": "atacado"}', call_id="tc-stage-001")

    # 1st create → mudar_stage tool call
    # 2nd create (after tool) → empty  [AGENT EMPTY AFTER TOOLS]
    # 3rd create (fallback, no tools) → empty  [safety fallback fires]
    call_responses = [
        _make_response(content=None, tool_calls=[tool_call]),
        _make_response(content="", tool_calls=None),
        _make_response(content="", tool_calls=None),
    ]
    call_index = {"i": 0}

    async def fake_create(**kwargs):
        resp = call_responses[call_index["i"]]
        call_index["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=[
        {"role": "user", "content": "Ambos, tomo no dia dia e tenho a cafeteria",
         "stage": "secretaria", "created_at": "2026-06-15T13:30:00Z",
         "wamid": "wamid-r", "quoted_wamid": None, "message_type": "text", "metadata": None}
    ]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-s01", "phone": "5565996414453", "ai_enabled": True}), \
         patch("app.agent.orchestrator.update_lead", new=MagicMock()), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="Stage alterado para: atacado")), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(conversation, "Ambos, tomo no dia dia e tenho a cafeteria")

    assert result == _STAGE_TRANSITION_FALLBACKS["atacado"]


# ---------------------------------------------------------------------------
# Integration: atomicity — empty turn with NO tool call must never return ""
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_empty_without_tool_never_returns_void():
    """Reproduces Lanny: an empty user turn (e.g. sticker) yields completion_tokens=0
    with NO tool call. Previously run_agent returned '' and the lead got silence.
    The agent must now return the generic stall instead of an empty string."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_MESSAGE

    conversation = {
        "id": "conv-void-001",
        "stage": "secretaria",
        "leads": {"id": "lead-v01", "name": "Lanny", "phone": "5511943068615", "ai_enabled": True},
    }

    # Single create → empty content, NO tool calls (tool_iterations stays 0)
    call_responses = [_make_response(content="", tool_calls=None)]
    call_index = {"i": 0}

    async def fake_create(**kwargs):
        resp = call_responses[call_index["i"]]
        call_index["i"] += 1
        return resp

    with patch("app.agent.orchestrator.get_history", return_value=[
        {"role": "user", "content": "", "stage": "secretaria",
         "created_at": "2026-06-15T13:10:00Z", "wamid": "wamid-l",
         "quoted_wamid": None, "message_type": "text", "metadata": None}
    ]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-v01", "phone": "5511943068615", "ai_enabled": True}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
        result = await run_agent(conversation, "")

    assert result == _SAFETY_FALLBACK_MESSAGE
    assert result.strip() != ""

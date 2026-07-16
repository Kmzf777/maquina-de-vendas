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


def test_no_transition_returns_generic_fallback():
    """Sem stage transition + sem mídia → fallback genérico honesto (Change C 2026-06-30).
    Nunca mais retorna None: o lead sempre recebe texto de re-engajamento em vez de silêncio."""
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_GENERIC
    result = _empty_fallback_text(media_tool_used=False, transitioned_to_stage=None)
    assert result == _SAFETY_FALLBACK_GENERIC
    assert "cortada" not in result


def test_unmapped_stage_returns_generic_fallback():
    """Transição para stage sem mensagem dedicada (ex.: secretaria) → fallback genérico honesto."""
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_GENERIC
    result = _empty_fallback_text(media_tool_used=False, transitioned_to_stage="secretaria")
    assert result == _SAFETY_FALLBACK_GENERIC
    assert "cortada" not in result


def test_all_commercial_stages_have_distinct_contextual_messages():
    """Each commercial funnel stage must have its own non-empty, distinct message."""
    from app.agent.orchestrator import _STAGE_TRANSITION_FALLBACKS
    for stage in ("atacado", "private_label", "exportacao", "consumo"):
        assert stage in _STAGE_TRANSITION_FALLBACKS, f"missing fallback for {stage}"
        assert _STAGE_TRANSITION_FALLBACKS[stage].strip()
    msgs = [_STAGE_TRANSITION_FALLBACKS[s] for s in ("atacado", "private_label", "exportacao", "consumo")]
    assert len(set(msgs)) == len(msgs), "stage messages must be distinct"


# ---------------------------------------------------------------------------
# Integration (mirror test_post_media_closing.py)
#
# Contrato Gemini nativo (migração 09/07/2026): as chamadas ao LLM saem por
# `app.agent.orchestrator.generate` (gemini_client) — fakes de tests/gemini_fakes.py.
# ---------------------------------------------------------------------------

from tests.gemini_fakes import fake_text, fake_tool_call


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

    # 1st generate → mudar_stage function_call
    # 2nd generate (after tool) → empty  [AGENT EMPTY AFTER TOOLS]
    # 3rd generate (retry-on-empty, no thinking) → empty
    # 4th generate (retry2, Etapa 2, temperatura elevada) → empty  [safety fallback fires]
    m_gen = AsyncMock(side_effect=[
        fake_tool_call("mudar_stage", {"stage": "atacado"}),
        fake_text(""),
        fake_text(""),
        fake_text(""),
    ])

    with patch("app.agent.orchestrator.get_history", return_value=[
        {"role": "user", "content": "Ambos, tomo no dia dia e tenho a cafeteria",
         "stage": "secretaria", "created_at": "2026-06-15T13:30:00Z",
         "wamid": "wamid-r", "quoted_wamid": None, "message_type": "text", "metadata": None}
    ]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-s01", "phone": "5565996414453", "ai_enabled": True}), \
         patch("app.agent.orchestrator.update_lead", new=MagicMock()), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="Stage alterado para: atacado")), \
         patch("app.agent.orchestrator.generate", new=m_gen):

        result = await run_agent(conversation, "Ambos, tomo no dia dia e tenho a cafeteria")

    assert result == _STAGE_TRANSITION_FALLBACKS["atacado"]


# ---------------------------------------------------------------------------
# Integration: atomicity — empty turn with NO tool call must never return ""
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_empty_without_tool_retries_then_uses_generic_fallback():
    """Empty user turn (ex.: sticker) com completion_tokens=0 e SEM tool call. O agente faz
    UM retry silencioso (thinking off); se ainda vazio e sem contexto coerente, retorna o
    fallback genérico honesto (Change C 2026-06-30) — nunca "" nem "chegou cortada"."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

    conversation = {
        "id": "conv-void-001",
        "stage": "secretaria",
        "leads": {"id": "lead-v01", "name": "Lanny", "phone": "5511943068615", "ai_enabled": True},
    }

    # generate 1 → empty (initial, thinking on); generate 2 → empty (retry, thinking off);
    # generate 3 → empty (retry2, Etapa 2, temperatura elevada)
    m_gen = AsyncMock(side_effect=[
        fake_text(""),
        fake_text(""),
        fake_text(""),
    ])

    with patch("app.agent.orchestrator.get_history", return_value=[
        {"role": "user", "content": "", "stage": "secretaria",
         "created_at": "2026-06-15T13:10:00Z", "wamid": "wamid-l",
         "quoted_wamid": None, "message_type": "text", "metadata": None}
    ]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-v01", "phone": "5511943068615", "ai_enabled": True}), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=m_gen):

        result = await run_agent(conversation, "")

    # Change C: nunca mais retorna "" para turno com histórico — usa o genérico honesto
    assert result == _SAFETY_FALLBACK_GENERIC
    assert "cortada" not in result
    assert m_gen.await_count == 3, "deve ter feito o retry silencioso e o retry2 antes do fallback"

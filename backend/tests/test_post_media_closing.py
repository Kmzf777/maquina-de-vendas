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
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Unit tests for _empty_fallback_text (pure helper)
# ---------------------------------------------------------------------------

def test_empty_fallback_text_with_media_returns_media_message():
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_MEDIA
    result = _empty_fallback_text(media_tool_used=True)
    assert result == _SAFETY_FALLBACK_MEDIA


def test_empty_fallback_text_without_media_returns_generic():
    """Caso genérico (sem mídia, sem transição de stage): retorna o fallback genérico honesto.
    Change C (2026-06-30): nunca mais retorna None — o lead sempre recebe texto, nunca silêncio."""
    from app.agent.orchestrator import _empty_fallback_text, _SAFETY_FALLBACK_GENERIC
    result = _empty_fallback_text(media_tool_used=False)
    assert result is not None
    assert result == _SAFETY_FALLBACK_GENERIC
    assert "cortada" not in result


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
#
# Contrato Gemini nativo (migração 09/07/2026): as chamadas ao LLM saem por
# `app.agent.orchestrator.generate` (gemini_client) — fakes de tests/gemini_fakes.py.
# ---------------------------------------------------------------------------

from tests.gemini_fakes import fake_text, fake_tool_call


@pytest.mark.asyncio
async def test_run_agent_media_tool_then_empty_uses_media_fallback():
    """LLM returns enviar_fotos function_call then empty text → _SAFETY_FALLBACK_MEDIA."""
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

    # Call sequence:
    # 1st generate → tool call (enviar_fotos)
    # 2nd generate (after tool result) → empty text  [triggers AGENT EMPTY AFTER TOOLS]
    # 3rd generate (retry-on-empty, no thinking) → empty
    # 4th generate (retry2, Etapa 2, temperatura elevada) → empty  [triggers safety fallback]
    m_gen = AsyncMock(side_effect=[
        fake_tool_call("enviar_fotos", {}),
        fake_text(""),
        fake_text(""),
        fake_text(""),
    ])

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
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="2 fotos enfileiradas para envio após o texto")), \
         patch("app.agent.orchestrator.generate", new=m_gen):

        result = await run_agent(conversation, "me manda as fotos")

    assert result == _SAFETY_FALLBACK_MEDIA


@pytest.mark.asyncio
async def test_run_agent_non_media_tool_then_empty_uses_generic_fallback():
    """Non-media tool + empty (sem stage transition) → fallback genérico honesto (Change C).
    Nunca mais aborta em silêncio: o lead sempre recebe um texto de re-engajamento."""
    from app.agent.orchestrator import run_agent, _SAFETY_FALLBACK_GENERIC

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

    # tool não-mídia + turnos vazios (pós-tool, retry1, retry2 — Etapa 2)
    m_gen = AsyncMock(side_effect=[
        fake_tool_call("marcar_interesse", {}),
        fake_text(""),
        fake_text(""),
        fake_text(""),
    ])

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
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="interesse registrado")), \
         patch("app.agent.orchestrator.generate", new=m_gen):

        result = await run_agent(conversation, "quero saber os preços")

    # Change C: nunca mais retorna "" para um turno com histórico — usa o genérico honesto
    assert result == _SAFETY_FALLBACK_GENERIC
    assert "cortada" not in result


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

    # enviar_foto_produto + turnos vazios (pós-tool, retry1, retry2 — Etapa 2)
    m_gen = AsyncMock(side_effect=[
        fake_tool_call("enviar_foto_produto", {}),
        fake_text(""),
        fake_text(""),
        fake_text(""),
    ])

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
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="foto do produto enfileirada para envio após o texto")), \
         patch("app.agent.orchestrator.generate", new=m_gen):

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

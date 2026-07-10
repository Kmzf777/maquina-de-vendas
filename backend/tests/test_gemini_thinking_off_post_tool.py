"""
Solução 2 (causa raiz do Bug 2): gemini-2.5-flash gasta o budget de saída "pensando"
após uma tool e devolve completion_tokens=0. Desabilitamos o thinking SOMENTE nas
chamadas pós-tool (onde o texto ao cliente precisa ser gerado), preservando o thinking
na primeira chamada (escolha de tools).

Migração 09/07 (Gemini 100% nativo): o knob era `reasoning_effort="none"` na fachada
OpenAI (`_gemini_thinking_off(model) -> dict`); hoje é `thinking_off=True` na chamada
nativa (`_thinking_off_for(model) -> bool` → ThinkingConfig(thinking_budget=0) no
gemini_client). Vale para a família flash/lite; os modelos *pro* seguem pensando.
A INTENÇÃO original é a mesma: pós-tool sem thinking, 1ª chamada com thinking.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.gemini_fakes import fake_text, fake_tool_call


# ---------------------------------------------------------------------------
# Unit: _thinking_off_for(model)
# ---------------------------------------------------------------------------

def test_thinking_off_for_gemini_25_flash():
    from app.agent.orchestrator import _thinking_off_for
    assert _thinking_off_for("gemini-2.5-flash") is True


def test_thinking_off_for_gemini_25_flash_lite():
    from app.agent.orchestrator import _thinking_off_for
    assert _thinking_off_for("gemini-2.5-flash-lite") is True


def test_thinking_off_false_for_gemini_25_pro():
    """2.5-pro não suporta desligar o thinking — não devemos pedi-lo (evita 400)."""
    from app.agent.orchestrator import _thinking_off_for
    assert _thinking_off_for("gemini-2.5-pro") is False


def test_thinking_off_false_for_non_gemini_model():
    from app.agent.orchestrator import _thinking_off_for
    assert _thinking_off_for("gpt-4o") is False


# ---------------------------------------------------------------------------
# Integration: post-tool call carries thinking_off=True, first call does not
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_tool_call_disables_thinking_first_call_keeps_it(monkeypatch):
    from app.agent.orchestrator import run_agent

    # Baseline hermético: garante o default (thinking LIGADO na 1ª chamada),
    # independente de LLM_INITIAL_THINKING no ambiente do dev.
    monkeypatch.delenv("LLM_INITIAL_THINKING", raising=False)

    conversation = {
        "id": "conv-think-001",
        "stage": "secretaria",
        "leads": {"id": "lead-t01", "name": "Renato", "phone": "5565996414453", "ai_enabled": True},
    }

    # 1st → tool call ; 2nd (post-tool) → real text (no empty needed for this test)
    call_responses = [
        fake_tool_call("mudar_stage", {"stage": "atacado"}),
        fake_text("Show! Você procura para revenda?"),
    ]

    with patch("app.agent.orchestrator.get_history", return_value=[
        {"role": "user", "content": "tenho cafeteria", "stage": "secretaria",
         "created_at": "2026-06-15T13:30:00Z", "wamid": "w", "quoted_wamid": None,
         "message_type": "text", "metadata": None}
    ]), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-t01", "phone": "5565996414453", "ai_enabled": True}), \
         patch("app.agent.orchestrator.update_lead", new=MagicMock()), \
         patch("app.agent.orchestrator._schedule_memory_refresh", new=MagicMock()), \
         patch("app.agent.orchestrator.execute_tool",
               new=AsyncMock(return_value="Stage alterado para: atacado")), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(side_effect=call_responses)) as m_gen:
        await run_agent(conversation, "tenho cafeteria")

    assert m_gen.await_count == 2
    # First call: thinking preserved (thinking_off=False)
    assert m_gen.await_args_list[0].kwargs["thinking_off"] is False
    # Second call (post-tool): thinking disabled
    assert m_gen.await_args_list[1].kwargs["thinking_off"] is True

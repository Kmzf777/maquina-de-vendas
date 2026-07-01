"""TDD do fallback de handoff quando o LLM está fora (2026-07-01).

Antes: run_agent lançava (LLM fora) → processor caía em [AGENT FAILED] → return mudo;
o lead (ex.: Welita) recebia 'digitando…' e nada mais. Agora: LLMUnavailableError
aciona encaminhar_humano — o cartão de contato do João é disparado ao lead e a IA é
desativada — em vez do silêncio. Exceções não-LLM mantêm o comportamento antigo.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.agent.orchestrator import LLMUnavailableError
from app.buffer import processor as P


@pytest.mark.asyncio
async def test_handle_llm_down_dispara_encaminhar_humano():
    lead = {"id": "lead-1", "phone": "5564984794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    with patch("app.agent.tools.execute_tool", new=AsyncMock(return_value="Lead encaminhado para Joao Bras")) as mock_exec:
        await P._handle_llm_down(lead, "5564984794946", conversation)
    mock_exec.assert_awaited_once()
    args, kwargs = mock_exec.await_args
    assert args[0] == "encaminhar_humano"
    assert args[1]["vendedor"] == "Joao Bras"
    assert kwargs["lead_id"] == "lead-1"
    assert kwargs["conversation_id"] == "conv-1"


@pytest.mark.asyncio
async def test_handle_llm_down_fail_soft_quando_handoff_falha():
    lead = {"id": "lead-1", "phone": "556484794946"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    # Handoff que explode NÃO pode propagar (nunca escala a falha).
    with patch("app.agent.tools.execute_tool", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await P._handle_llm_down(lead, "556484794946", conversation)  # não levanta
